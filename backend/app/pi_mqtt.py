"""Liaison MQTT avec le broker Mosquitto du Raspberry (repris du backend Docker de l'équipe infra).

Protocole (identique à leur backend, voir leur compose.yaml / install.ps1 / test_mqtt.py) :
  - MQTT 3.1.1 sur TLS (port 8883), certificat du broker vérifié avec leur CA (infra/pi-broker/ca.crt) et le nom
    « sentinel-x » ; authentification identifiant / mot de passe (leur .env, voir config.PiMqttConfig).
  - Abonnements QoS 1 : sentinel/+/telemetry, sentinel/+/cyber, sentinel/+/status.
  - Message = JSON avec au moins event_id et timestamp (ISO 8601) ; event_type optionnel.
  - Enregistré dans la table `events` (même schéma que la leur), puis ACK applicatif QoS 1 sur
    sentinel/<device>/ack : {"event_id": ..., "status": "stored"} (aussi pour un doublon : déjà stocké).

Jamais bloquant : tout tourne dans le thread de paho (connexion asynchrone, reconnexion 1 s à 30 s). Broker absent,
nom introuvable, certificat ou mot de passe refusé = une ligne dans le journal et l'état `connected: false` ; le reste
du backend (SSH, vision, alertes) fonctionne exactement comme avant.
"""
import json
import logging
import socket
import ssl
import threading
from datetime import datetime, timezone

from .clock import now_ms
from .config import PiMqttConfig
from .console import green, red
from .logger import logger

log = logging.getLogger("sentinel-x")
TOPICS = ("telemetry", "cyber", "status")
MAX_PAYLOAD = 16 * 1024


def parse_message(topic: str, payload: bytes) -> dict:
    """Valide un message reçu ; renvoie {eventId, deviceId, category, eventType, timestamp, payload} ou lève ValueError.

    Logique pure (testée). Mêmes exigences minimales que le backend de l'infra : topic sentinel/<device>/<catégorie>,
    JSON objet, event_id et timestamp présents.
    """
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "sentinel" or not parts[1] or parts[2] not in TOPICS:
        raise ValueError(f"topic inattendu : {topic}")
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"message trop long ({len(payload)} octets)")
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ValueError("JSON invalide") from err
    if not isinstance(data, dict):
        raise ValueError("JSON invalide (objet attendu)")
    event_id = data.get("event_id")
    if not isinstance(event_id, str) or not 0 < len(event_id) <= 100:
        raise ValueError("event_id manquant ou invalide")
    try:
        timestamp = datetime.fromisoformat(str(data.get("timestamp")))
    except ValueError as err:
        raise ValueError("timestamp manquant ou invalide (ISO 8601 attendu)") from err
    if timestamp.tzinfo is not None:
        timestamp = timestamp.astimezone(timezone.utc)  # SQLite ne garde pas le fuseau : on stocke tout en UTC
    event_type = data.get("event_type")
    return {
        "eventId": event_id, "deviceId": parts[1][:100], "category": parts[2],
        "eventType": str(event_type)[:100] if event_type is not None else None,
        "timestamp": timestamp, "payload": data,
    }


def _client_class():
    import paho.mqtt.client as mqtt  # importé ici : inutile avec PI_MQTT=off

    class PinnedClient(mqtt.Client):
        """Si le nom du broker ne se résout pas, se connecte à l'adresse de secours ; le certificat TLS est toujours
        vérifié avec le NOM (même effet que `extra_hosts: sentinel-x:<ip>` dans le compose de l'infra)."""

        fallback_ip = ""

        def _create_socket_connection(self):
            try:
                return super()._create_socket_connection()
            except socket.gaierror:
                if not self.fallback_ip:
                    raise
                return socket.create_connection((self.fallback_ip, self._port), timeout=self._connect_timeout)

    return mqtt, PinnedClient


class PiMqttLink:
    def __init__(self, config: PiMqttConfig, database=None):
        self._config = config
        self._db = database
        self._lock = threading.Lock()
        self._client = None
        self._connected = False
        self._error: str | None = None
        self._received = 0
        self._stored = 0
        self._invalid = 0
        self._by_category = {t: 0 for t in TOPICS}
        self._last: dict | None = None
        self._last_seen_ms: int | None = None
        self._warned_fail = False  # une seule ligne de journal par série d'échecs de connexion

    def state(self) -> dict:
        with self._lock:
            return {
                "broker": f"{self._config.host}:{self._config.port}",
                "fallbackIp": self._config.fallback_ip or None,
                "connected": self._connected,
                "error": self._error,
                "received": self._received,
                "stored": self._stored,
                "invalid": self._invalid,
                "byCategory": dict(self._by_category),
                "lastSeenMs": self._last_seen_ms,
                "last": self._last,
            }

    async def start(self) -> None:
        try:
            mqtt, client_class = _client_class()
            client = client_class(mqtt.CallbackAPIVersion.VERSION2, client_id=self._config.client_id, protocol=mqtt.MQTTv311)
            client.fallback_ip = self._config.fallback_ip
            client.username_pw_set(self._config.username, self._config.password)
            client.tls_set(ca_certs=self._config.ca, cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
        except Exception as err:  # noqa: BLE001 — paquet absent, CA illisible : on continue sans cette liaison
            self._fail(f"liaison MQTT du Raspberry désactivée : {err}")
            return
        client.on_connect = self._on_connect
        client.on_connect_fail = self._on_connect_fail
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client = client
        client.connect_async(self._config.host, self._config.port, keepalive=60)
        client.loop_start()  # thread paho : connexion, reconnexion, réception

    async def stop(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client.loop_stop()

    def _fail(self, error: str) -> None:
        with self._lock:
            self._connected, self._error = False, error
        log.warning(red(f"MQTT Raspberry : {error}"))
        logger.emit("pimqtt.error", error, level="warning")

    # ---- callbacks paho (thread MQTT) ----
    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:  # mauvais mot de passe, client non autorisé...
            with self._lock:
                self._connected, self._error = False, f"connexion refusée par le broker : {reason_code}"
            if not self._warned_fail:
                self._warned_fail = True
                log.warning(red(f"MQTT Raspberry : connexion refusée ({reason_code}) — vérifier le mot de passe"))
                logger.emit("pimqtt.error", f"Broker MQTT du Raspberry : connexion refusée ({reason_code})", level="warning")
            return
        client.subscribe([(f"sentinel/+/{t}", 1) for t in TOPICS])
        with self._lock:
            self._connected, self._error = True, None
        self._warned_fail = False
        log.info(green(f"MQTT Raspberry connecté ({self._config.host}:{self._config.port}, TLS)"))
        logger.emit("pimqtt.connected", f"Connecté au broker MQTT du Raspberry {self._config.host}:{self._config.port} (TLS)")

    def _on_connect_fail(self, _client, _userdata) -> None:
        """Nom introuvable, Pi éteint, broker arrêté, certificat refusé : paho réessaie tout seul."""
        error = f"broker MQTT du Raspberry injoignable ({self._config.host}:{self._config.port}) ou certificat refusé"
        with self._lock:
            self._connected, self._error = False, error
        if not self._warned_fail:
            self._warned_fail = True
            log.warning(red(f"MQTT Raspberry injoignable ({self._config.host}:{self._config.port}) — le backend continue sans, nouvel essai en arrière-plan"))
            logger.emit("pimqtt.error", error + " — nouvelles tentatives en arrière-plan", level="warning")

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        with self._lock:
            was, self._connected = self._connected, False
            if was:
                self._error = f"connexion perdue ({reason_code})"
        if was:
            log.warning(red("MQTT Raspberry déconnecté — reconnexion automatique"))
            logger.emit("pimqtt.disconnected", "Déconnecté du broker MQTT du Raspberry", level="warning", reason=str(reason_code))

    def _on_message(self, client, _userdata, msg) -> None:
        with self._lock:
            self._received += 1
            self._last_seen_ms = now_ms()
        try:
            event = parse_message(msg.topic, msg.payload)
        except ValueError as err:
            with self._lock:
                self._invalid += 1
            logger.emit("pimqtt.invalid", f"Message MQTT du Raspberry ignoré : {err}", level="warning", topic=msg.topic)
            return
        try:
            new = self._db.save_pi_event(event) if self._db else True
        except Exception as err:  # noqa: BLE001 — base en panne : pas d'ACK, l'émetteur pourra renvoyer
            logger.emit("pimqtt.error", f"Message MQTT non enregistré : {err}", level="error", eventId=event["eventId"])
            return
        summary = {k: event[k] for k in ("eventId", "deviceId", "category", "eventType")}
        with self._lock:
            self._by_category[event["category"]] += 1
            self._stored += 1 if new else 0
            self._last = {**summary, "timestamp": event["timestamp"].isoformat(), "receivedMs": self._last_seen_ms}
        client.publish(f"sentinel/{event['deviceId']}/ack", json.dumps({"event_id": event["eventId"], "status": "stored"}), qos=1)
        if new and event["category"] != "telemetry":  # la télémétrie (fréquente) ne va qu'en base, pas dans le journal
            logger.emit(
                f"pimqtt.{event['category']}", f"Raspberry {event['deviceId']} : {event['category']} {event['eventType'] or ''}".strip(),
                level="warning" if event["category"] == "cyber" else "info", **summary, payload=event["payload"],
            )


def create_pi_mqtt(config: PiMqttConfig, database=None) -> PiMqttLink | None:
    return PiMqttLink(config, database) if config.enabled else None
