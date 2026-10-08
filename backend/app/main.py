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
from dataclasses import asdict
from typing import Any

from fastapi import Body, Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .ai import create_analyzer
from .ai.threat import threat_score
from .auth import COOKIE, bootstrap_admin, current_user, device_token_ok, require_admin, router as auth_router, websocket_user
from .config import CAPTURES_DIR, LOG_DIR, VIDEOS_DIR, config
from .db import database
from .edge import create_edge
from .hub import Hub
from .logger import logger
from .providers import create_provider
from .vision import create_vision

logger.setup()  # console + journal JSON (backend/data/logs/), voir logger.py

database.init()  # crée les tables si besoin (SQLite : un fichier ; PostgreSQL : DATABASE_URL)
provider = create_provider(config)
vision = create_vision(config)  # None sauf avec ANALYZER=local
analyzer = create_analyzer(config, vision)
edge = create_edge(config.edge, config.thresholds.gas_raw)  # Edge Node ESP8266 (MQTTS), None si EDGE=off
hub = Hub(config, provider, analyzer, vision, database, edge)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await asyncio.to_thread(bootstrap_admin)
    await hub.start()
    logging.getLogger("sentinel-x").info(
        "env: %s%s, provider: %s, analyse: %s, vision: %s, edge: %s, base: %s, tick %d ms",
        config.env,
        " (photos d'intrusion désactivées)" if config.env == "dev" else "",
        provider.name,
        analyzer.name,
        f"YOLO sur {config.vision.source}" if vision else "off",
        f"ESP8266 via MQTTS {config.edge.host}:{config.edge.port}" if config.edge.source == "mqtt" else config.edge.source,
        database.dialect,
        config.tick_ms,
    )
    logger.emit(
        "app.start", f"Sentinel-X démarré (env {config.env})",
        env=config.env, provider=provider.name, analyzer=analyzer.name, database=database.dialect, tickMs=config.tick_ms,
        edge={"source": config.edge.source, "broker": f"{config.edge.host}:{config.edge.port}"},
        vision={"enabled": bool(vision), "source": config.vision.source, "model": config.vision.model, "imgsz": config.vision.imgsz},
        thresholds=asdict(config.thresholds),
        photosEnabled=config.env == "prod", logDir=str(LOG_DIR),
    )
    yield
    logger.emit("app.stop", "Sentinel-X arrêté")
    await hub.stop()


app = FastAPI(title="Sentinel-X API", lifespan=lifespan)
app.include_router(auth_router)


def error(status: int, message: str) -> JSONResponse:
    # le front lit `.error`
    return JSONResponse({"error": message}, status_code=status)


def _peer(conn) -> str | None:
    return conn.client.host if conn.client else None


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    # accès refusés et erreurs serveur sont journalisés (404 et le 401 de /api/auth/me au chargement : trop bruyants)
    if exc.status_code in (401, 403, 429) and request.url.path != "/api/auth/me" or exc.status_code >= 500:
        logger.emit(
            "http.denied" if exc.status_code < 500 else "http.error", f"{request.method} {request.url.path} → {exc.status_code}",
            level="warning" if exc.status_code < 500 else "error",
            method=request.method, path=request.url.path, status=exc.status_code, detail=str(exc.detail), ip=_peer(request),
        )
    return error(exc.status_code, str(exc.detail))


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    logging.getLogger("sentinel-x").error("exception non gérée sur %s %s", request.method, request.url.path, exc_info=exc)
    return error(500, "Erreur interne")


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


@app.get("/api/videos")
def videos(_user: dict = Depends(current_user)):
    """Clips vidéo des intrusions, du plus récent au plus ancien (nom, taille, date, lien)."""
    files = sorted(VIDEOS_DIR.glob("intrusion_*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) if VIDEOS_DIR.is_dir() else []
    return [{"name": p.name, "bytes": p.stat().st_size, "modifiedMs": int(p.stat().st_mtime * 1000), "url": f"/api/videos/{p.name}"} for p in files]


@app.get("/api/videos/{name}")
def video(name: str, _user: dict = Depends(current_user)):
    """Un clip vidéo (MP4 H.264, lecture progressive avec Range). Réservé aux comptes connectés."""
    path = VIDEOS_DIR / name
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.mp4", name) or not path.is_file():
        return error(404, "Vidéo introuvable")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/edge")
async def edge_status(_user: dict = Depends(current_user)):
    """Edge Node ESP8266 : liaison MQTT et dernières mesures de chaque boîtier (null si EDGE=off)."""
    return hub.edge_state()


@app.get("/api/modules")
async def modules(_user: dict = Depends(current_user)):
    """Santé de chaque module : state = ok | lost | unknown, depuis quand, dernière fois ok, raison."""
    return hub.monitor.states()


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
    hub.monitor.reset_camera()  # changement voulu : l'attente d'images qui suit n'est pas une perte de connexion
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


# Scénarios de démo (mock uniquement) : intruder | heat | window (PROVIDER=mock) ; gas | presence (EDGE=mock)
EDGE_SCENARIOS = ("gas", "presence")


@app.post("/api/mock/{scenario}")
async def mock_scenario(scenario: str, admin: dict = Depends(require_admin)):
    source = edge if scenario in EDGE_SCENARIOS else provider
    trigger = getattr(source, "trigger_scenario", None)
    if trigger is None:
        return error(404, f"Disponible uniquement avec {'EDGE' if scenario in EDGE_SCENARIOS else 'PROVIDER'}=mock")
    try:
        trigger(scenario)
    except ValueError as err:
        return error(400, str(err))
    await audit(admin, "scenario", scenario)
    return {"ok": True}


# ---- WebSocket ----
async def _refuse(ws: WebSocket, code: int = 4401) -> None:
    """Refus après la poignée de main (le navigateur reçoit ainsi un vrai code de fermeture : 4401 = non connecté)."""
    logger.emit(
        "ws.refused", f"Connexion refusée sur {ws.url.path} (code {code})", level="warning",
        path=ws.url.path, code=code, ip=_peer(ws),
    )
    await ws.accept()
    await ws.close(code=code)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    """Événements : hello, snapshot, analysis, alert, motor, vision (JSON). Compte connecté requis."""
    user = await websocket_user(ws)
    if user is None:
        return await _refuse(ws)
    await hub.connect(ws, ws.cookies.get(COOKIE))
    logger.emit("ws.connect", f"{user['username']} connecté au flux de données", channel="/ws", user=user["username"], role=user["role"], ip=_peer(ws))
    try:
        while True:
            await ws.receive_text()  # le front n'envoie rien ; on détecte juste la déconnexion
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)
        logger.emit("ws.disconnect", f"{user['username']} déconnecté du flux de données", channel="/ws", user=user["username"], ip=_peer(ws))


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
    origin = f"admin {user['username']}" if user and user["role"] == "admin" else "appareil (jeton)"
    logger.emit("camera.push_connect", f"Envoi d'images ouvert par {origin}", channel="/ws/camera", origin=origin, ip=_peer(ws))
    frames = 0
    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes"):
                vision.push_frame(message["bytes"])
                frames += 1
    except WebSocketDisconnect:
        pass
    finally:
        logger.emit("camera.push_disconnect", f"Envoi d'images fermé ({frames} images reçues)", channel="/ws/camera", origin=origin, frames=frames, ip=_peer(ws))


@app.websocket("/ws/video")
async def ws_video_endpoint(ws: WebSocket):
    """Vidéo : une image + ses résultats YOLO par message binaire, format décrit dans hub.py. Compte connecté requis."""
    user = await websocket_user(ws)
    if user is None:
        return await _refuse(ws)
    client = await hub.connect_video(ws, ws.cookies.get(COOKIE))
    logger.emit("ws.connect", f"{user['username']} connecté au flux vidéo", channel="/ws/video", user=user["username"], role=user["role"], ip=_peer(ws))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect_video(client)
        logger.emit("ws.disconnect", f"{user['username']} déconnecté du flux vidéo", channel="/ws/video", user=user["username"], ip=_peer(ws))
