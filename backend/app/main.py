"""API Sentinel-X : REST + WebSocket.

Lancer :  python -m uvicorn app.main:app --reload --port 4000   (depuis backend/)
"""
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .ai import create_analyzer
from .config import config
from .hub import Hub
from .providers import create_provider

logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

provider = create_provider(config)
analyzer = create_analyzer(config)
hub = Hub(config, provider, analyzer)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await hub.start()
    logging.getLogger("sentinel-x").info(
        "provider: %s, IA: %s, tick %d ms", provider.name, analyzer.name, config.tick_ms
    )
    yield
    await hub.stop()


app = FastAPI(title="Sentinel-X API", lifespan=lifespan)


def error(status: int, message: str) -> JSONResponse:
    # même forme d'erreur que l'ancien backend : le front lit `.error`
    return JSONResponse({"error": message}, status_code=status)


# ---- API REST ----
@app.get("/api/health")
async def health():
    return {"ok": True, "provider": provider.name, "analyzer": analyzer.name, "tickMs": config.tick_ms}


@app.get("/api/snapshot")
async def snapshot():
    return hub.latest or error(503, "Pas encore de données")


@app.get("/api/analysis")
async def analysis():
    return hub.analysis or error(503, "Pas encore d'analyse")


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


# Scénarios de démo (mock uniquement) : intruder | heat
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
    await hub.connect(ws)
    try:
        while True:
            await ws.receive_text()  # le front n'envoie rien ; on détecte juste la déconnexion
    except WebSocketDisconnect:
        pass
    finally:
        hub.disconnect(ws)
