"""API Sentinel-X : REST + WebSocket.

Lancer :  python -m uvicorn app.main:app --reload --port 4000   (depuis backend/)
Avec YOLO sur la caméra :  ANALYZER=local  (voir README) ; webcam du navigateur : + VISION_SOURCE=browser

Accès : tout est protégé par un compte. « agent » = consultation seule ; « admin » = tout (moteur / caméra, source
vidéo, simulations, comptes). Seul /api/health est public. Voir auth.py.
"""
import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .ai import create_analyzer
from .ai.threat import threat_score
from .auth import COOKIE, bootstrap_admin, current_user, device_token_ok, require_admin, router as auth_router, websocket_user
from .config import CAPTURES_DIR, config
from .db import database
from .hub import Hub
from .providers import create_provider
from .vision import create_vision

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

database.init()  # crée les tables si besoin (SQLite : un fichier ; PostgreSQL : DATABASE_URL)
provider = create_provider(config)
vision = create_vision(config)  # None sauf avec ANALYZER=local
analyzer = create_analyzer(config, vision)
hub = Hub(config, provider, analyzer, vision, database)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(bootstrap_admin)
    await hub.start()
    logging.getLogger("sentinel-x").info(
        "provider: %s, analyse: %s, vision: %s, base: %s, tick %d ms",
        provider.name,
        analyzer.name,
        f"YOLO sur {config.vision.source}" if vision else "off",
        database.dialect,
        config.tick_ms,
    )
    yield
    await hub.stop()


app = FastAPI(title="Sentinel-X API", lifespan=lifespan)
app.include_router(auth_router)


def error(status: int, message: str) -> JSONResponse:
    # le front lit `.error`
    return JSONResponse({"error": message}, status_code=status)


@app.exception_handler(StarletteHTTPException)
async def http_error(_request: Request, exc: StarletteHTTPException):
    return error(exc.status_code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    return error(400, "Données invalides : " + "; ".join(f"{'.'.join(map(str, e['loc'][1:]))} {e['msg']}" for e in exc.errors()))


async def audit(user: dict, action: str, detail: Any = "") -> None:
    text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
    try:
        await asyncio.to_thread(database.audit, user["username"], action, text)
    except Exception:  # noqa: BLE001 — l'audit ne doit pas bloquer une commande
        logging.getLogger("sentinel-x").exception("audit non enregistré")


# ---- API REST : consultation (admin ou agent) ----
@app.get("/api/health")
async def health():
    """Seule route publique : sert aux sondes de disponibilité, sans rien révéler."""
    return {"ok": True}


@app.get("/api/snapshot")
async def snapshot(_user: dict = Depends(current_user)):
    return hub.latest or error(503, "Pas encore de données")


@app.get("/api/analysis")
async def analysis(_user: dict = Depends(current_user)):
    return hub.analysis or error(503, "Pas encore d'analyse")


@app.get("/api/vision")
async def vision_status(_user: dict = Depends(current_user)):
    return hub.vision_status()


@app.get("/api/history")
async def history(_user: dict = Depends(current_user)):
    return {"sensors": list(hub.sensor_history), "threat": list(hub.threat_history)}


@app.get("/api/alerts")
async def alerts(_user: dict = Depends(current_user)):
    return hub.alerts.list()


@app.get("/api/captures/{name}")
def capture(name: str, _user: dict = Depends(current_user)):
    """Photo d'intrusion. Réservée aux comptes connectés (un montage de fichiers statiques n'aurait aucun contrôle)."""
    path = CAPTURES_DIR / name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.jpg", name) or not path.is_file():
        return error(404, "Photo introuvable")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# ---- API REST : actions (admin seulement) ----
@app.post("/api/motor")
async def motor(cmd: Any = Body(None), admin: dict = Depends(require_admin)):
    try:
        state = await provider.send_motor_command(cmd)
    except ValueError as err:
        return error(400, str(err))
    await hub.broadcast({"type": "motor", "data": state})
    await audit(admin, "motor", cmd)
    return state


@app.post("/api/vision/source")
async def vision_source(body: Any = Body(None), admin: dict = Depends(require_admin)):
    """Source des images de YOLO : {mode: 'browser'} (webcam du navigateur) ou {mode: 'default'} (caméra du backend)."""
    if vision is None:
        return error(404, "Vision désactivée : lancer avec ANALYZER=local")
    mode = body.get("mode") if isinstance(body, dict) else None
    if mode not in ("browser", "default"):
        return error(400, "mode attendu : 'browser' ou 'default'")
    status = vision.set_push_mode(mode == "browser")
    await audit(admin, "vision_source", mode)
    return status


@app.post("/api/vision/analyze")
async def vision_analyze(request: Request, annotated: bool = False, _admin: dict = Depends(require_admin)):
    """YOLO sur une image envoyée en entrée (corps de la requête = JPEG ou PNG).

    Retourne les positions des carrés / silhouettes (`detections`), la menace calculée avec les capteurs
    courants (`threat`) et, avec ?annotated=true, l'image avec les dessins de YOLO (`annotated`, JPEG base64).
    Exemple :  curl -b cookies.txt -X POST --data-binary @photo.jpg -H "Content-Type: image/jpeg" localhost:4000/api/vision/analyze
    """
    if vision is None:
        return error(404, "Vision désactivée : lancer avec ANALYZER=local")
    data = await request.body()
    if not data:
        return error(400, "image attendue dans le corps de la requête")
    try:
        result = await asyncio.to_thread(vision.analyze_image, data, annotated)
    except ValueError as err:
        return error(400, str(err))
    env = hub.analysis.get("environment") if hub.analysis else None
    threat = threat_score(hub.latest, result["detections"], env) if hub.latest else None
    return {**result, "threat": threat}


# Scénarios de démo (mock uniquement) : intruder | heat | window
@app.post("/api/mock/{scenario}")
async def mock_scenario(scenario: str, admin: dict = Depends(require_admin)):
    trigger = getattr(provider, "trigger_scenario", None)
    if trigger is None:
        return error(404, "Disponible uniquement avec PROVIDER=mock")
    try:
        trigger(scenario)
    except ValueError as err:
        return error(400, str(err))
    await audit(admin, "scenario", scenario)
    return {"ok": True}


# ---- WebSocket ----
async def _refuse(ws: WebSocket, code: int = 4401) -> None:
    """Refus après la poignée de main (le navigateur reçoit ainsi un vrai code de fermeture : 4401 = non connecté)."""
    await ws.accept()
    await ws.close(code=code)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    """Événements : hello, snapshot, analysis, alert, motor, vision (JSON). Compte connecté requis."""
    if await websocket_user(ws) is None:
        return await _refuse(ws)
    await hub.connect(ws, ws.cookies.get(COOKIE))
    try:
        while True:
            await ws.receive_text()  # le front n'envoie rien ; on détecte juste la déconnexion
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)


@app.websocket("/ws/camera")
async def ws_camera_endpoint(ws: WebSocket):
    """Entrée caméra : images JPEG (binaire) que YOLO traite. Autorisé : un admin connecté (webcam du navigateur)
    ou un appareil muni du jeton DEVICE_TOKEN (?token=..., le Raspberry)."""
    user = await websocket_user(ws)
    if not (device_token_ok(ws.query_params.get("token")) or (user and user["role"] == "admin")):
        return await _refuse(ws, 4403 if user else 4401)
    await ws.accept()
    if vision is None:
        await ws.close(code=1008, reason="Vision désactivée : lancer avec ANALYZER=local")
        return
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                vision.push_frame(message["bytes"])
    except WebSocketDisconnect:
        pass


@app.websocket("/ws/video")
async def ws_video_endpoint(ws: WebSocket):
    """Vidéo : une image + ses résultats YOLO par message binaire, format décrit dans hub.py. Compte connecté requis."""
    if await websocket_user(ws) is None:
        return await _refuse(ws)
    client = await hub.connect_video(ws, ws.cookies.get(COOKIE))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect_video(client)
