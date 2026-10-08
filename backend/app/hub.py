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
from .auth import user_from_token
from .config import Config
from .console import green, red
from .logger import logger
from .modules import ModuleMonitor

log = logging.getLogger("sentinel-x")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _sensor_point(raw: dict) -> dict:
    """Point d'historique compact (même forme que sensorPoint dans frontend/src/hooks/useSentinel.js)."""
    env = raw.get("environment") or {}
    ultrasonic, thermal = raw.get("ultrasonic") or {}, raw.get("thermal") or {}  # un capteur muet donne des None
    return {
        "ts": raw["ts"],
        "distanceCm": ultrasonic.get("distanceCm"),
        "avgC": thermal.get("avgC"),
        "maxC": thermal.get("maxC"),
        "envTempC": env.get("tempC"),
        "humidityPct": env.get("humidityPct"),
    }


MODULE_CHECK_S = 1  # fréquence de la surveillance des modules (voir modules.py)
SESSION_CHECK_S = 15  # les WebSocket ouvertes sont revérifiées à cet intervalle (session fermée, compte supprimé...)


@dataclass(eq=False)
class VideoClient:
    ws: WebSocket
    token: str | None = None  # jeton de session du client, pour revérifier qu'il est toujours valide
    busy: bool = False  # une image est en cours d'envoi : on saute les suivantes (pas de retard cumulé)


class Hub:
    def __init__(self, config: Config, provider, analyzer, vision=None, database=None):
        self.provider = provider
        self.analyzer = analyzer
        self.vision = vision
        self.db = database  # historique des alertes (optionnel : sans base, tout reste en mémoire)
        self.alerts = AlertEngine(
            config.thresholds,
            config.alerts_size,
            intrusion_from_vision=vision is not None,
            initial=database.recent_alerts(config.alerts_size) if database else None,
        )
        self.sensor_history: deque[dict] = deque(maxlen=config.history_size)
        self.threat_history: deque[dict] = deque(maxlen=config.history_size)  # {ts, score}
        self.latest: dict | None = None  # dernier snapshot brut du Raspberry
        self.analysis: dict | None = None  # dernier résultat du modèle IA (arrive en différé)
        self._analyzing = False
        self._clients: set[WebSocket] = set()
        self._tokens: dict[WebSocket, str | None] = {}  # jeton de session de chaque client /ws
        self._video_clients: set[VideoClient] = set()
        self._sweeper: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_snapshot_ms: int | None = None  # dernier snapshot reçu du Pi (pour détecter sa perte)
        absent = frozenset(getattr(provider, "absent_modules", ()))  # capteurs non montés sur le boîtier réel
        self.monitor = ModuleMonitor(config.module_timeout_s, config.dht_stale_s, _now_ms(), absent)
        self._watchdog: asyncio.Task | None = None
        self._monitor_task: asyncio.Task | None = None
        self._monitor_interval_s = config.monitor_interval_s
        self._intrusion: dict | None = None  # intrusion en cours : début, pic de personnes, nombre de photos
        logger.set_context(self.context)  # chaque ligne du journal JSON embarque cet état complet

    def context(self) -> dict:
        """État complet de l'application, joint à chaque événement du journal (voir logger.py)."""
        return {
            "provider": self.provider.name,
            "analyzer": self.analyzer.name,
            "sensors": self.latest,  # dernier snapshot du Pi : ultrason, thermique, environnement, moteur, système, caméra
            "analysis": self.analysis,  # dernière analyse IA : menace, anomalies d'environnement, détections
            "vision": self.vision_status(),
            "activeAlerts": self.alerts.active(),
            "modules": self.monitor.states(),  # santé de chaque module (ok / lost / unknown, depuis quand, pourquoi)
            "clients": {"events": len(self._clients), "video": len(self._video_clients)},
        }

    # ---- WebSocket événements (/ws) ----
    async def connect(self, ws: WebSocket, token: str | None = None) -> None:
        await ws.accept()
        self._clients.add(ws)
        self._tokens[ws] = token
        log.info(green(f"front connecté au back ({len(self._clients)} client(s))"))
        await ws.send_text(json.dumps({"type": "hello", "data": self.hello()}))

    def disconnect(self, ws: WebSocket) -> None:
        self._tokens.pop(ws, None)
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
        if created and self.db:
            try:
                await asyncio.to_thread(self.db.save_alerts, created)
            except Exception as err:  # noqa: BLE001 — une base en panne ne doit pas couper les alertes en direct
                log.warning(red(f"alerte non enregistrée en base : {err}"))
        for alert in created:
            logger.emit("alert.created", alert["message"], level=alert["level"], alert=alert)
            await self.broadcast({"type": "alert", "data": alert})

    # ---- WebSocket vidéo (/ws/video) : images JPEG annotées, en binaire ----
    async def connect_video(self, ws: WebSocket, token: str | None = None) -> VideoClient:
        await ws.accept()
        client = VideoClient(ws, token)
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
        if self._intrusion is None or event.get("event") != "new_person":
            self._intrusion = {"startedMs": event["ts"], "peakPersons": 0, "photos": 0}
        self._intrusion["peakPersons"] = max(self._intrusion["peakPersons"], event["personCount"])
        self._intrusion["photos"] += 1 if event.get("snapshot") else 0
        logger.emit(
            f"vision.{event.get('event', 'intrusion')}", f"{title} détectée ({event['personCount']} personne(s))",
            level="critical", alertId=alert["id"], snapshotSaved=bool(event.get("snapshot")),
            **{k: v for k, v in event.items() if k != "event"},  # `event` est le nom de l'événement (déjà dans la ligne)
        )
        photo = f"photo {event['snapshot']}" if event.get("snapshot") else "mode dev activé : capture d'écran désactivée"
        log.info(red(f"{title} détectée ({event['personCount']} personne(s), {round(event['confidence'] * 100)} %) — {photo}"))
        asyncio.create_task(self._broadcast_alerts([alert]))

    def _on_intrusion_end(self) -> None:
        self.alerts.intrusion_ended()
        log.info(green("intrusion terminée"))
        started, self._intrusion = self._intrusion, None
        logger.emit(
            "vision.intrusion_ended", "Intrusion terminée",
            **({"startedMs": started["startedMs"], "durationMs": _now_ms() - started["startedMs"],
                "peakPersons": started["peakPersons"], "photos": started["photos"]} if started else {}),
        )

    def _on_clip(self, info: dict) -> None:
        """Un clip vidéo d'intrusion est terminé : trace dans le journal (fichier, poids, durée, qualité)."""
        recovered = info.get("recovered", False)
        what = "Clip vidéo récupéré après un arrêt brutal" if recovered else "Clip vidéo de l'intrusion enregistré"
        text = f"{what} ({info['durationS']} s, {info['bytes'] / 1024:.0f} Ko)"
        (log.warning if recovered else log.info)(green(f"{text} : {info['name']}"))
        logger.emit("vision.clip", text, level="warning" if recovered else "info", **{**info, "recovered": recovered})

    def _on_vision_status(self, status: dict) -> None:
        log_fn = log.warning if status["state"] == "error" else log.info
        log_fn("vision : %s%s", status["state"], f" — {status['error']}" if status.get("error") else "")
        logger.emit("vision.status", f"Vision : {status['state']}", level="error" if status["state"] == "error" else "info", status=status)
        asyncio.create_task(self.broadcast({"type": "vision", "data": status}))

    # ---- chemin rapide ----
    async def on_snapshot(self, raw: dict) -> None:
        self.latest = raw
        self._last_snapshot_ms = _now_ms()
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
                logger.emit("analysis.recovered", "Modèle IA de nouveau disponible", analyzer=source)
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

    # ---- sessions des WebSocket ouvertes ----
    async def _sweep_sessions(self) -> None:
        """Une WebSocket n'est authentifiée qu'à son ouverture : sans ce balayage, un compte supprimé, un mot de passe
        réinitialisé ou une déconnexion laisserait les flux (données, vidéo) ouverts jusqu'à la prochaine
        reconnexion. On ferme avec le code 4401, le dashboard revient alors à la page de connexion."""
        while True:
            await asyncio.sleep(SESSION_CHECK_S)
            sockets = [(ws, self._tokens.get(ws), lambda w=ws: self.disconnect(w)) for ws in list(self._clients)]
            sockets += [(c.ws, c.token, lambda c=c: self.disconnect_video(c)) for c in list(self._video_clients)]
            for ws, token, forget in sockets:
                if await asyncio.to_thread(user_from_token, token) is None:
                    forget()
                    logger.emit("ws.session_closed", "Flux fermé : session invalide, expirée ou compte supprimé", level="warning", code=4401)
                    try:
                        await ws.close(code=4401)
                    except Exception:  # noqa: BLE001 — déjà fermée
                        pass

    # ---- santé des modules ----
    async def _watch_modules(self) -> None:
        """Toutes les secondes : un module qui ne répond plus est journalisé (module.lost), signalé par une alerte
        « Perte de connexion », et son retour est journalisé aussi (module.recovered)."""
        while True:
            await asyncio.sleep(MODULE_CHECK_S)
            try:
                await self._check_modules()
            except Exception:  # noqa: BLE001 — la surveillance ne doit jamais s'arrêter
                log.exception("surveillance des modules")

    async def _check_modules(self) -> None:
        vision = self.vision_status() if self.vision else None
        transitions = self.monitor.check(_now_ms(), self.latest, self._last_snapshot_ms, vision, self.analysis)
        for t in transitions:
            if t["to"] == "lost":
                since = f"depuis {(_now_ms() - t['lastOkMs']) / 1000:.0f} s" if t["lastOkMs"] else "jamais joint"
                log.info(red(f"PERTE DE CONNEXION : {t['label']} — {t['reason']}"))
                logger.emit(
                    "module.lost", f"Perte de connexion : {t['label']} — {t['reason']}", level="error",
                    module=t["module"], label=t["label"], reason=t["reason"], lastOkMs=t["lastOkMs"], silence=since,
                )
            else:
                log.info(green(f"connexion rétablie : {t['label']} (coupure de {t['downMs'] / 1000:.0f} s)"))
                logger.emit(
                    "module.recovered", f"Connexion rétablie : {t['label']}", module=t["module"], label=t["label"], downMs=t["downMs"],
                )
        if transitions:
            await self._broadcast_alerts(self.alerts.evaluate_modules(self.monitor.states()))

    # ---- relevé périodique ----
    async def _monitor_log(self) -> None:
        """Une ligne « monitor.snapshot » toutes les MONITOR_INTERVAL_S secondes (60 par défaut), même sans événement :
        toutes les données des capteurs, l'analyse IA, la vision et la santé des modules (dans `context`)."""
        started = time.monotonic()
        while True:
            await asyncio.sleep(self._monitor_interval_s)
            try:
                age = _now_ms() - self._last_snapshot_ms if self._last_snapshot_ms else None
                logger.emit(
                    "monitor.snapshot", "Relevé périodique", intervalS=self._monitor_interval_s,
                    uptimeS=round(time.monotonic() - started), snapshotAgeMs=age,
                    threat=(self.analysis or {}).get("threat"),
                )
            except Exception:  # noqa: BLE001 — le relevé ne doit jamais faire tomber l'API
                log.exception("relevé périodique")

    # ---- cycle de vie ----
    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._sweeper = asyncio.create_task(self._sweep_sessions())
        self._watchdog = asyncio.create_task(self._watch_modules())
        self._monitor_task = asyncio.create_task(self._monitor_log())
        await self.provider.start(self.on_snapshot)
        if self.vision:
            self.vision.start(
                on_frame=lambda jpeg, meta: self._from_vision_thread(self._on_frame, jpeg, meta),
                on_intrusion=lambda event: self._from_vision_thread(self._on_intrusion, event),
                on_intrusion_end=lambda: self._from_vision_thread(self._on_intrusion_end),
                on_status=lambda status: self._from_vision_thread(self._on_vision_status, status),
                on_clip=lambda info: self._from_vision_thread(self._on_clip, info),
            )

    async def stop(self) -> None:
        if self._sweeper:
            self._sweeper.cancel()
        if self._watchdog:
            self._watchdog.cancel()
        if self._monitor_task:
            self._monitor_task.cancel()
        if self.vision:
            await asyncio.to_thread(self.vision.stop)
        await self.provider.stop()
