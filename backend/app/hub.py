"""Cœur de l'API : état courant, diffusion WebSocket, et les deux chemins de données.

  Chemin rapide : snapshot brut du Pi -> front, sans attendre le modèle.
  Chemin lent   : le même snapshot part au modèle IA local (dans un thread) ; son résultat
                  est diffusé plus tard (message `analysis`, avec `forTs` = snapshot analysé).
"""
import asyncio
import json
import logging
import time
from collections import deque

from fastapi import WebSocket

from .alerts import AlertEngine
from .config import Config
from .console import green, red

log = logging.getLogger("sentinel-x")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sensor_point(raw: dict) -> dict:
    """Point d'historique compact (même forme que sensorPoint dans client/src/hooks/useSentinel.js)."""
    env = raw.get("environment") or {}
    return {
        "ts": raw["ts"],
        "distanceCm": raw["ultrasonic"]["distanceCm"],
        "avgC": raw["thermal"]["avgC"],
        "maxC": raw["thermal"]["maxC"],
        "envTempC": env.get("tempC"),
        "humidityPct": env.get("humidityPct"),
    }


class Hub:
    def __init__(self, config: Config, provider, analyzer):
        self.provider = provider
        self.analyzer = analyzer
        self.alerts = AlertEngine(config.thresholds, config.alerts_size)
        self.sensor_history: deque[dict] = deque(maxlen=config.history_size)
        self.threat_history: deque[dict] = deque(maxlen=config.history_size)  # {ts, score}
        self.latest: dict | None = None  # dernier snapshot brut du Raspberry
        self.analysis: dict | None = None  # dernier résultat du modèle IA (arrive en différé)
        self._analyzing = False
        self._clients: set[WebSocket] = set()

    # ---- WebSocket ----
    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        log.info(green(f"front connecté au back ({len(self._clients)} client(s))"))
        await ws.send_text(json.dumps({"type": "hello", "data": self.hello()}))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._clients:
            self._clients.discard(ws)
            log.info(red(f"front déconnecté du back ({len(self._clients)} client(s))"))

    def hello(self) -> dict:
        return {
            "provider": self.provider.name,
            "snapshot": self.latest,
            "analysis": self.analysis,
            "history": {"sensors": list(self.sensor_history), "threat": list(self.threat_history)},
            "alerts": self.alerts.list(),
        }

    async def broadcast(self, message: dict) -> None:
        if not self._clients:
            return
        payload = json.dumps(message)
        clients = list(self._clients)
        results = await asyncio.gather(*(c.send_text(payload) for c in clients), return_exceptions=True)
        for client, result in zip(clients, results):
            if isinstance(result, Exception):
                self.disconnect(client)

    async def _broadcast_alerts(self, created: list[dict]) -> None:
        for alert in created:
            await self.broadcast({"type": "alert", "data": alert})

    # ---- chemin rapide ----
    async def on_snapshot(self, raw: dict) -> None:
        self.latest = raw
        self.sensor_history.append(_sensor_point(raw))
        await self.broadcast({"type": "snapshot", "data": raw})
        await self._broadcast_alerts(self.alerts.evaluate_sensors(raw))
        asyncio.create_task(self._run_analysis(raw))  # volontairement non attendu

    # ---- chemin lent ----
    async def _run_analysis(self, raw: dict) -> None:
        # Pas de file d'attente : si le modèle est occupé, on saute ce snapshot.
        if self._analyzing:
            return
        self._analyzing = True
        started = time.monotonic()
        was_ok = self.analysis["ok"] if self.analysis else True
        source = self.analyzer.name
        try:
            out = await asyncio.to_thread(self.analyzer.analyze, raw)
            if not isinstance(out.get("detections"), list) or not isinstance(
                (out.get("threat") or {}).get("score"), (int, float)
            ):
                raise ValueError("réponse du modèle invalide")
            self.analysis = {
                "ok": True,
                "source": source,
                "forTs": raw["ts"],  # snapshot analysé (pour corréler avec les données brutes)
                "ts": _now_ms(),
                "latencyMs": round((time.monotonic() - started) * 1000),
                "detections": out["detections"],
                "threat": out["threat"],
                "environment": out.get("environment"),  # anomalies DHT22, optionnel
            }
            self.threat_history.append({"ts": raw["ts"], "score": out["threat"]["score"]})
            await self.broadcast({"type": "analysis", "data": self.analysis})
            await self._broadcast_alerts(self.alerts.evaluate_analysis(self.analysis))
            if not was_ok:
                log.info(green("modèle IA de nouveau disponible"))
        except Exception as err:  # noqa: BLE001 — le modèle ne doit jamais faire tomber l'API
            self.analysis = {
                "ok": False,
                "source": source,
                "forTs": raw["ts"],
                "ts": _now_ms(),
                "error": str(err) or type(err).__name__,
                "detections": [],
                "threat": None,
                "environment": None,
            }
            await self.broadcast({"type": "analysis", "data": self.analysis})
            if was_ok:
                log.warning(red(f"modèle IA indisponible : {self.analysis['error']}"))
        finally:
            self._analyzing = False

    # ---- cycle de vie ----
    async def start(self) -> None:
        await self.provider.start(self.on_snapshot)

    async def stop(self) -> None:
        await self.provider.stop()
