"""Cœur de l'API : état courant, diffusion WebSocket, et les chemins de données.

  Chemin rapide : snapshot brut du Pi -> front, sans attendre le modèle.
  Chemin lent   : le même snapshot part à l'analyseur (dans un thread) ; son résultat est diffusé
                  plus tard (message `analysis`, avec `forTs` = snapshot analysé).
  Chemin vidéo  : le service de vision (caméra + YOLO, thread dédié) pousse sur /ws/video (binaire) chaque
                  image avec ses propres résultats (positions des carrés, silhouettes, menace) : le
                  dashboard dessine les carrés rouges lui-même, synchronisés avec l'image. Ses
                  événements d'intrusion (alerte avec photo) partent sur /ws.

Format d'un message /ws/video :  [4 octets : taille N de l'en-tête, big-endian] [N octets : JSON UTF-8] [JPEG]
  en-tête = {ts, width, height, annotated, personCount, detections: [{label, confidence, bbox, polygon?}], threat}
"""
import asyncio
import json
import logging
import struct
import time
from collections import deque
from dataclasses import dataclass

from fastapi import WebSocket

from .alerts import AlertEngine
from .config import Config
from .console import green, red

log = logging.getLogger("sentinel-x")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sensor_point(raw: dict) -> dict:
    """Point d'historique compact (même forme que sensorPoint dans frontend/src/hooks/useSentinel.js)."""
    env = raw.get("environment") or {}
    return {
        "ts": raw["ts"],
        "distanceCm": raw["ultrasonic"]["distanceCm"],
        "avgC": raw["thermal"]["avgC"],
        "maxC": raw["thermal"]["maxC"],
        "envTempC": env.get("tempC"),
        "humidityPct": env.get("humidityPct"),
    }


@dataclass(eq=False)
class VideoClient:
    ws: WebSocket
    busy: bool = False  # une image est en cours d'envoi : on saute les suivantes (pas de retard cumulé)


class Hub:
    def __init__(self, config: Config, provider, analyzer, vision=None):
        self.provider = provider
        self.analyzer = analyzer
        self.vision = vision
        self.alerts = AlertEngine(config.thresholds, config.alerts_size, intrusion_from_vision=vision is not None)
        self.sensor_history: deque[dict] = deque(maxlen=config.history_size)
        self.threat_history: deque[dict] = deque(maxlen=config.history_size)  # {ts, score}
        self.latest: dict | None = None  # dernier snapshot brut du Raspberry
        self.analysis: dict | None = None  # dernier résultat du modèle IA (arrive en différé)
        self._analyzing = False
        self._clients: set[WebSocket] = set()
        self._video_clients: set[VideoClient] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    # ---- WebSocket événements (/ws) ----
    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        log.info(green(f"front connecté au back ({len(self._clients)} client(s))"))
        await ws.send_text(json.dumps({"type": "hello", "data": self.hello()}))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._clients:
            self._clients.discard(ws)
            log.info(red(f"front déconnecté du back ({len(self._clients)} client(s))"))

    def vision_status(self) -> dict:
        return self.vision.status() if self.vision else {"enabled": False}

    def hello(self) -> dict:
        return {
            "provider": self.provider.name,
            "snapshot": self.latest,
            "analysis": self.analysis,
            "vision": self.vision_status(),
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

    # ---- WebSocket vidéo (/ws/video) : images JPEG annotées, en binaire ----
    async def connect_video(self, ws: WebSocket) -> VideoClient:
        await ws.accept()
        client = VideoClient(ws)
        self._video_clients.add(client)
        return client

    def disconnect_video(self, client: VideoClient) -> None:
        self._video_clients.discard(client)

    async def _send_frame(self, client: VideoClient, payload: bytes) -> None:
        client.busy = True
        try:
            await client.ws.send_bytes(payload)
        except Exception:  # noqa: BLE001 — client parti
            self.disconnect_video(client)
        finally:
            client.busy = False

    # ---- callbacks du service de vision : appelés depuis son thread, exécutés dans la boucle de l'API ----
    def _from_vision_thread(self, fn, *args) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(fn, *args)

    def _on_frame(self, jpeg: bytes, meta: dict) -> None:
        clients = [c for c in self._video_clients if not c.busy]
        if not clients:
            return
        # menace : dernier résultat de l'analyseur (arrive en différé des capteurs), jointe à chaque image
        threat = self.analysis["threat"] if self.analysis and self.analysis["ok"] else None
        header = json.dumps({**meta, "threat": threat}).encode()
        payload = struct.pack(">I", len(header)) + header + jpeg
        for client in clients:
            asyncio.create_task(self._send_frame(client, payload))

    def _on_intrusion(self, event: dict) -> None:
        alert = self.alerts.intrusion_started(event)
        title = "NOUVELLE PERSONNE" if event.get("event") == "new_person" else "INTRUSION"
        log.info(red(f"{title} détectée ({event['personCount']} personne(s), {round(event['confidence'] * 100)} %) — photo {event['snapshot']}"))
        asyncio.create_task(self._broadcast_alerts([alert]))

    def _on_intrusion_end(self) -> None:
        self.alerts.intrusion_ended()
        log.info(green("intrusion terminée"))

    def _on_vision_status(self, status: dict) -> None:
        log_fn = log.warning if status["state"] == "error" else log.info
        log_fn("vision : %s%s", status["state"], f" — {status['error']}" if status.get("error") else "")
        asyncio.create_task(self.broadcast({"type": "vision", "data": status}))

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
                "personCount": sum(1 for d in out["detections"] if d["label"] == "person"),
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
                "personCount": 0,
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
        self._loop = asyncio.get_running_loop()
        await self.provider.start(self.on_snapshot)
        if self.vision:
            self.vision.start(
                on_frame=lambda jpeg, meta: self._from_vision_thread(self._on_frame, jpeg, meta),
                on_intrusion=lambda event: self._from_vision_thread(self._on_intrusion, event),
                on_intrusion_end=lambda: self._from_vision_thread(self._on_intrusion_end),
                on_status=lambda status: self._from_vision_thread(self._on_vision_status, status),
            )

    async def stop(self) -> None:
        if self.vision:
            await asyncio.to_thread(self.vision.stop)
        await self.provider.stop()
