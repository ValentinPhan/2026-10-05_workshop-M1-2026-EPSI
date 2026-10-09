"""Edge Node ESP8266 : gaz (MQ-2), présence (PIR) et Wi-Fi, reçus en MQTTS depuis le broker Mosquitto.

Indépendant du provider du Raspberry : l'ESP a sa propre liaison (MQTT, TLS + certificat client) et son propre
rythme (télémétrie toutes les 2 s, événement immédiat quand le PIR change). Contrat des messages :
docs/mqtt-contract.md.

  MqttEdge  client paho-mqtt dans son propre thread (comme la vision) ; ses callbacks repassent dans la boucle
            asyncio du Hub via `notify` (call_soon_threadsafe). Reconnexion automatique (1 s à 30 s).
  MockEdge  ESP simulé (EDGE=mock) : même état, scénarios « gas » et « presence » pour la démo sans matériel.

Contrat commun : name, async start(notify), async stop(), state(), et trigger_scenario(name) pour le mock.
state() = {source, broker, connected, error, gasThreshold, nodes: [{node, online, fw, ip, seq, lost, readAt,
lastSeenMs, gasRaw, pir, rssi, tempC, humidityPct}]}  (clés en camelCase = contrat avec le front).
"""
import asyncio
import copy
import json
import math
import random
import ssl
import threading
import time
from typing import Callable

from .clock import now_ms
from .config import EdgeConfig
from .logger import logger

MAX_PAYLOAD = 512  # octets ; l'ESP envoie < 256
TOPICS = ("telemetry", "event", "status")

Notify = Callable[[dict], None]  # reçoit {"kind": ..., "node": ...} ; appelée dans la boucle asyncio


def _int(v, lo: int, hi: int) -> int | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return int(v) if lo <= v <= hi else None


def _float(v, lo: float, hi: float) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return round(float(v), 1) if lo <= v <= hi else None


def new_node(node: str) -> dict:
    return {
        "node": node, "online": False, "fw": None, "ip": None, "seq": None, "lost": 0, "readAt": None,
        "lastSeenMs": None, "gasRaw": None, "pir": None, "rssi": None, "tempC": None, "humidityPct": None,
    }


def apply_message(nodes: dict[str, dict], topic: str, payload: bytes, now_ms: int) -> dict:
    """Applique un message MQTT à l'état des boîtiers ; renvoie {kind, node, ...} ou lève ValueError (message ignoré).

    Logique pure (sans I/O) : testée directement. Le broker garantit déjà, par ses ACL, qu'un boîtier n'écrit que sur
    ses propres topics ; on revalide quand même tout ce qui arrive (types, bornes, taille).
    """
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != "sentinel" or parts[2] not in TOPICS or not parts[1]:
        raise ValueError(f"topic inattendu : {topic}")
    node, kind = parts[1], parts[2]
    if len(payload) > MAX_PAYLOAD:
        raise ValueError(f"message trop long ({len(payload)} octets)")
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ValueError("JSON invalide") from err
    if not isinstance(data, dict):
        raise ValueError("JSON invalide (objet attendu)")

    state = nodes.setdefault(node, new_node(node))
    if kind == "status":
        if data.get("state") not in ("online", "offline"):
            raise ValueError("statut invalide")
        was = state["online"]
        state["online"] = data["state"] == "online"
        if state["online"]:
            state["fw"] = str(data.get("fw"))[:20] if data.get("fw") is not None else state["fw"]
            state["ip"] = str(data.get("ip"))[:45] if data.get("ip") is not None else state["ip"]
            state["lastSeenMs"] = now_ms
        return {"kind": "status", "node": node, "online": state["online"], "changed": was != state["online"]}

    seq = _int(data.get("seq"), 0, 2**31)
    if seq is None:
        raise ValueError("seq manquant ou invalide")
    previous = state["seq"]
    if previous is not None and seq > previous + 1:
        state["lost"] += seq - previous - 1  # messages perdus (QoS 0) ; un seq plus petit = redémarrage de l'ESP
    state["seq"] = seq
    state["online"] = True  # un message prouve que le boîtier est là (même si son statut retenu dit le contraire)
    state["lastSeenMs"] = now_ms
    ts = _int(data.get("ts"), 0, 2**40)
    read_at = ts * 1000 if ts else now_ms  # ts = 0 : l'ESP n'a pas encore l'heure, on prend l'heure de réception

    if kind == "event":
        if data.get("type") != "pir":
            return {"kind": "event", "node": node, "type": str(data.get("type"))[:20]}
        pir = _int(data.get("v"), 0, 1)
        if pir is None:
            raise ValueError("valeur PIR invalide")
        changed = state["pir"] != pir
        state["pir"] = pir
        return {"kind": "event", "node": node, "type": "pir", "pir": pir, "changed": changed}

    pir = _int(data.get("pir"), 0, 1)
    state.update({
        "readAt": read_at,
        "gasRaw": _int(data.get("gas"), 0, 1023),
        "pir": pir if pir is not None else state["pir"],
        "rssi": _int(data.get("rssi"), -120, 0),
        "tempC": _float(data.get("t"), -40, 85),  # optionnels : seulement si l'ESP porte un capteur de température
        "humidityPct": _float(data.get("h"), 0, 100),
    })
    return {"kind": "telemetry", "node": node}


class _EdgeBase:
    name = "edge"

    def __init__(self, config: EdgeConfig, gas_threshold: float):
        self._config = config
        self._gas_threshold = gas_threshold
        self._lock = threading.Lock()
        self._nodes: dict[str, dict] = {}
        self._connected = False
        self._error: str | None = None
        self._notify: Notify | None = None

    def state(self) -> dict:
        with self._lock:
            return {
                "source": self.name,
                "broker": f"{self._config.host}:{self._config.port}" if self.name == "mqtt" else None,
                "connected": self._connected,
                "error": self._error,
                "gasThreshold": self._gas_threshold,
                "nodes": [copy.copy(n) for n in sorted(self._nodes.values(), key=lambda n: n["node"])],
            }

    def _emit(self, info: dict) -> None:
        if self._notify:
            self._notify(info)


class MqttEdge(_EdgeBase):
    name = "mqtt"

    def __init__(self, config: EdgeConfig, gas_threshold: float):
        super().__init__(config, gas_threshold)
        self._client = None
        self._last_invalid: dict[str, float] = {}  # anti-spam du journal : une ligne par raison toutes les 30 s

    async def start(self, notify: Notify) -> None:
        import paho.mqtt.client as mqtt  # importé ici : inutile avec EDGE=mock|off

        self._notify = notify
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self._config.client_id)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_connect_fail = self._on_connect_fail
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        try:
            client.tls_set(
                ca_certs=self._config.ca, certfile=self._config.cert, keyfile=self._config.key,
                cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT,
            )
        except (OSError, ssl.SSLError) as err:
            self._fail(f"certificats MQTT illisibles ({err}) : lancer infra/pki/gen-certs.sh")
            return
        self._client = client
        client.connect_async(self._config.host, self._config.port, keepalive=15)
        client.loop_start()  # thread paho : connexion, reconnexion, réception

    def _fail(self, error: str) -> None:
        with self._lock:
            self._error = error
        logger.emit("edge.error", f"Edge Node : {error}", level="error")
        self._emit({"kind": "broker", "connected": False})

    async def stop(self) -> None:
        if self._client:
            self._client.disconnect()
            self._client.loop_stop()

    # ---- callbacks paho (thread MQTT) ----
    def _on_connect(self, client, _userdata, _flags, reason_code, _properties) -> None:
        if reason_code.is_failure:
            with self._lock:
                self._connected, self._error = False, f"connexion refusée par le broker : {reason_code}"
            logger.emit("edge.error", f"Broker MQTT : connexion refusée ({reason_code})", level="error")
            return
        client.subscribe([(f"sentinel/+/{t}", 1) for t in TOPICS])
        with self._lock:
            self._connected, self._error = True, None
        logger.emit("edge.connected", f"Connecté au broker MQTT {self._config.host}:{self._config.port} (TLS)")
        self._emit({"kind": "broker", "connected": True})

    def _on_connect_fail(self, _client, _userdata) -> None:
        """Broker injoignable ou poignée de main TLS refusée (certificat) : paho réessaie tout seul."""
        with self._lock:
            self._connected = False
            self._error = f"broker MQTT injoignable ({self._config.host}:{self._config.port}) ou certificat refusé"

    def _on_disconnect(self, _client, _userdata, _flags, reason_code, _properties) -> None:
        with self._lock:
            was, self._connected = self._connected, False
            self._error = f"broker MQTT injoignable ({reason_code})"
        if was:
            logger.emit("edge.disconnected", "Déconnecté du broker MQTT", level="warning", reason=str(reason_code))
        self._emit({"kind": "broker", "connected": False})

    def _on_message(self, _client, _userdata, msg) -> None:
        try:
            with self._lock:
                info = apply_message(self._nodes, msg.topic, msg.payload, now_ms())
        except ValueError as err:
            reason = str(err)
            now = time.monotonic()
            if now - self._last_invalid.get(reason, -math.inf) > 30:
                self._last_invalid[reason] = now
                logger.emit("edge.invalid", f"Message MQTT ignoré : {reason}", level="warning", topic=msg.topic)
            return
        self._emit(info)


class MockEdge(_EdgeBase):
    """ESP8266 simulé : MQ-2 au repos (~180), PIR au repos, RSSI qui fluctue. Un message toutes les 2 s."""

    name = "mock"
    NODE = "esp-node-01"
    PERIOD_S = 2

    def __init__(self, config: EdgeConfig, gas_threshold: float):
        super().__init__(config, gas_threshold)
        self._task: asyncio.Task | None = None
        self._seq = 0
        self._gas = 180.0
        self._leak_s = 0.0  # fuite de gaz simulée : temps restant
        self._presence_s = 0.0  # présence PIR simulée : temps restant

    async def start(self, notify: Notify) -> None:
        self._notify = notify
        with self._lock:
            self._connected = True
            apply_message(self._nodes, f"sentinel/{self.NODE}/status", b'{"state":"online","fw":"mock","ip":"-"}', now_ms())
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def trigger_scenario(self, name: str) -> None:
        if name == "gas":
            self._leak_s = 20
        elif name == "presence":
            self._presence_s = 8
        else:
            raise ValueError(f"Scénario inconnu : {name}")

    def _publish(self, kind: str, data: dict) -> None:
        self._seq += 1
        payload = json.dumps({"seq": self._seq, "ts": int(time.time()), **data}).encode()
        with self._lock:
            info = apply_message(self._nodes, f"sentinel/{self.NODE}/{kind}", payload, now_ms())
        self._emit(info)

    async def _run(self) -> None:
        pir = 0
        while True:
            target = 820 if self._leak_s > 0 else 180
            self._gas += (target - self._gas) * 0.25 + random.uniform(-6, 6)  # le MQ-2 réagit en quelques secondes
            self._leak_s = max(0.0, self._leak_s - self.PERIOD_S)
            new_pir = 1 if self._presence_s > 0 else 0
            self._presence_s = max(0.0, self._presence_s - self.PERIOD_S)
            if new_pir != pir:
                pir = new_pir
                self._publish("event", {"type": "pir", "v": pir})
            self._publish("telemetry", {"gas": round(max(0, min(1023, self._gas))), "pir": pir, "rssi": random.randint(-62, -54)})
            await asyncio.sleep(self.PERIOD_S)


def create_edge(config: EdgeConfig, gas_threshold: float):
    if config.source == "off":
        return None
    if config.source == "mqtt":
        return MqttEdge(config, gas_threshold)
    if config.source == "mock":
        return MockEdge(config, gas_threshold)
    raise ValueError(f"EDGE inconnu : {config.source} (mqtt | mock | off)")
