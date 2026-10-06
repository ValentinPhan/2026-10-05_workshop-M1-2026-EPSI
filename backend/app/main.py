"""API Sentinel-X : REST + WebSocket.

Lancer :  python -m uvicorn app.main:app --reload --port 4000   (depuis backend/)
Avec YOLO sur la caméra :  ANALYZER=local  (voir README) ; webcam du navigateur : + VISION_SOURCE=browser
"""
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .ai import create_analyzer
from .ai.threat import threat_score
from .config import CAPTURES_DIR, config
from .hub import Hub
from .providers import create_provider
from .vision import create_vision

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

provider = create_provider(config)
vision = create_vision(config)  # None sauf avec ANALYZER=local
analyzer = create_analyzer(config, vision)
hub = Hub(config, provider, analyzer, vision)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await hub.start()
    logging.getLogger("sentinel-x").info(
        "provider: %s, analyse: %s, vision: %s, tick %d ms",
        provider.name,
        analyzer.name,
        f"YOLO sur {config.vision.source}" if vision else "off",
        config.tick_ms,
    )
    yield
    await hub.stop()


app = FastAPI(title="Sentinel-X API", lifespan=lifespan)

CAPTURES_DIR.mkdir(parents=True, exist_ok=True)  # StaticFiles exige que le dossier existe
app.mount("/api/captures", StaticFiles(directory=CAPTURES_DIR), name="captures")  # photos d'intrusion


def error(status: int, message: str) -> JSONResponse:
    # même forme d'erreur que l'ancien backend : le front lit `.error`
    return JSONResponse({"error": message}, status_code=status)


# ---- API REST ----
@app.get("/api/health")
async def health():
    return {
        "ok": True,
        "provider": provider.name,
        "analyzer": analyzer.name,
        "vision": hub.vision_status(),
        "tickMs": config.tick_ms,
    }


@app.get("/api/snapshot")
async def snapshot():
    return hub.latest or error(503, "Pas encore de données")


@app.get("/api/analysis")
async def analysis():
    return hub.analysis or error(503, "Pas encore d'analyse")


@app.get("/api/vision")
async def vision_status():
    return hub.vision_status()


@app.post("/api/vision/source")
async def vision_source(body: Any = Body(None)):
    """Source des images de YOLO : {mode: 'browser'} (webcam du navigateur) ou {mode: 'default'} (caméra du backend)."""
    if vision is None:
        return error(404, "Vision désactivée : lancer avec ANALYZER=local")
    mode = body.get("mode") if isinstance(body, dict) else None
    if mode not in ("browser", "default"):
        return error(400, "mode attendu : 'browser' ou 'default'")
    return vision.set_push_mode(mode == "browser")


@app.post("/api/vision/analyze")
async def vision_analyze(request: Request, annotated: bool = False):
    """YOLO sur une image envoyée en entrée (corps de la requête = JPEG ou PNG).

    Retourne les positions des carrés / silhouettes (`detections`), la menace calculée avec les capteurs
    courants (`threat`) et, avec ?annotated=true, l'image avec les dessins de YOLO (`annotated`, JPEG base64).
    Exemple :  curl -X POST --data-binary @photo.jpg -H "Content-Type: image/jpeg" localhost:4000/api/vision/analyze
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


@app.get("/api/history")
async def history():
    return {"sensors": list(hub.sensor_history), "threat": list(hub.threat_history)}


@app.get("/api/alerts")
async def alerts():
    return hub.alerts.list()


@app.post("/api/motor")
async def motor(cmd: Any = Body(None)):
    try:
        state = await provider.send_motor_command(cmd)
    except ValueError as err:
        return error(400, str(err))
    await hub.broadcast({"type": "motor", "data": state})
    return state


# Scénarios de démo (mock uniquement) : intruder | heat | window
@app.post("/api/mock/{scenario}")
async def mock_scenario(scenario: str):
    trigger = getattr(provider, "trigger_scenario", None)
    if trigger is None:
        return error(404, "Disponible uniquement avec PROVIDER=mock")
    try:
        trigger(scenario)
    except ValueError as err:
        return error(400, str(err))
    return {"ok": True}


# ---- WebSocket ----
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    """Événements : hello, snapshot, analysis, alert, motor, vision (JSON)."""
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # le front n'envoie rien ; on détecte juste la déconnexion
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)


@app.websocket("/ws/camera")
async def ws_camera_endpoint(ws: WebSocket):
    """Entrée caméra : le navigateur envoie ses images JPEG (binaire) pour que YOLO les traite."""
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
    """Vidéo : une image + ses résultats YOLO par message binaire, format décrit dans hub.py (rien si la vision est désactivée)."""
    client = await hub.connect_video(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect_video(client)
