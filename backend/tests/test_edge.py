"""Edge Node ESP8266 : messages MQTT, alertes gaz / PIR, santé du module, API avec l'ESP simulé.

Lancer (depuis backend/, venv actif) :  pip install pytest httpx  puis  python -m pytest tests -q
"""
import json
import time

import pytest

from app.alerts import AlertEngine
from app.config import Thresholds
from app.edge import apply_message
from app.modules import ModuleMonitor
from conftest import ADMIN_PASSWORD


def msg(nodes, kind, data, node="esp-node-01", now=1_000):
    return apply_message(nodes, f"sentinel/{node}/{kind}", json.dumps(data).encode(), now)


# ---- apply_message ----
def test_telemetry_updates_node():
    nodes = {}
    info = msg(nodes, "telemetry", {"seq": 1, "ts": 1791201600, "gas": 312, "pir": 0, "rssi": -58, "t": 23.44})
    assert info == {"kind": "telemetry", "node": "esp-node-01"}
    n = nodes["esp-node-01"]
    assert (n["gasRaw"], n["pir"], n["rssi"], n["tempC"], n["online"]) == (312, 0, -58, 23.4, True)
    assert n["readAt"] == 1791201600 * 1000 and n["lastSeenMs"] == 1_000


def test_ts_zero_uses_reception_time_and_optional_fields_absent():
    nodes = {}
    msg(nodes, "telemetry", {"seq": 1, "ts": 0, "gas": 100}, now=5_000)
    n = nodes["esp-node-01"]
    assert n["readAt"] == 5_000 and n["tempC"] is None and n["humidityPct"] is None


def test_lost_messages_counted_and_reboot_tolerated():
    nodes = {}
    for seq in (1, 2, 5):  # 3 et 4 perdus
        msg(nodes, "telemetry", {"seq": seq, "gas": 100})
    assert nodes["esp-node-01"]["lost"] == 2
    msg(nodes, "telemetry", {"seq": 0, "gas": 100})  # redémarrage de l'ESP
    msg(nodes, "telemetry", {"seq": 1, "gas": 100})
    assert nodes["esp-node-01"]["lost"] == 2


def test_status_and_lwt():
    nodes = {}
    info = msg(nodes, "status", {"state": "online", "fw": "0.1.0", "ip": "192.168.137.20"})
    assert info["changed"] and nodes["esp-node-01"]["fw"] == "0.1.0"
    info = msg(nodes, "status", {"state": "offline"})
    assert info == {"kind": "status", "node": "esp-node-01", "online": False, "changed": True}


def test_pir_event():
    nodes = {}
    info = msg(nodes, "event", {"seq": 1, "type": "pir", "v": 1})
    assert info["pir"] == 1 and info["changed"] and nodes["esp-node-01"]["pir"] == 1


@pytest.mark.parametrize("topic,payload", [
    ("sentinel/esp-node-01/cmd", b'{"seq":1}'),  # topic non prévu
    ("autre/esp-node-01/telemetry", b'{"seq":1}'),
    ("sentinel/esp-node-01/telemetry", b"pas du json"),
    ("sentinel/esp-node-01/telemetry", b"[1,2]"),
    ("sentinel/esp-node-01/telemetry", b'{"gas":100}'),  # seq manquant
    ("sentinel/esp-node-01/telemetry", b'{"seq":true}'),
    ("sentinel/esp-node-01/telemetry", b'{"seq":1,"pad":"' + b"x" * 600 + b'"}'),  # trop long
    ("sentinel/esp-node-01/status", b'{"state":"hacked"}'),
    ("sentinel/esp-node-01/event", b'{"seq":1,"type":"pir","v":7}'),
])
def test_invalid_messages_rejected(topic, payload):
    with pytest.raises(ValueError):
        apply_message({}, topic, payload, 0)


def test_out_of_range_values_dropped():
    nodes = {}
    msg(nodes, "telemetry", {"seq": 1, "gas": 5000, "rssi": 10, "t": 999, "pir": 3})
    n = nodes["esp-node-01"]
    assert (n["gasRaw"], n["rssi"], n["tempC"], n["pir"]) == (None, None, None, None)


# ---- alertes ----
def edge_state(**node):
    return {"connected": True, "nodes": [{"node": "esp-node-01", "online": True, "gasRaw": 200, "pir": 0, **node}]}


def test_gas_and_presence_alerts_on_rising_edge_only():
    engine = AlertEngine(Thresholds(gas_raw=600), 50)
    assert engine.evaluate_edge(edge_state()) == []
    created = engine.evaluate_edge(edge_state(gasRaw=700, pir=1))
    assert {a["key"]: a["level"] for a in created} == {"gas_esp-node-01": "critical", "presence_esp-node-01": "warning"}
    assert engine.evaluate_edge(edge_state(gasRaw=720, pir=1)) == []  # toujours vraie : pas de doublon
    assert engine.evaluate_edge(edge_state(gasRaw=200, pir=0)) == [] and engine.active() == []


def test_offline_node_keeps_its_alerts():
    engine = AlertEngine(Thresholds(gas_raw=600), 50)
    engine.evaluate_edge(edge_state(gasRaw=700))
    assert engine.evaluate_edge(edge_state(online=False, gasRaw=None)) == []
    assert "gas_esp-node-01" in engine.active()


# ---- santé du module ----
def esp_health(edge, now, started=0, timeout_s=10):
    monitor = ModuleMonitor(5, 30, started, edge_timeout_s=timeout_s)
    monitor.check(now, None, None, None, None, edge)
    return monitor.states().get("esp8266", {}).get("state")


def test_module_grace_then_lost_when_broker_down():
    down = {"connected": False, "error": "broker MQTT injoignable", "nodes": []}
    assert esp_health(down, now=5_000) == "unknown"
    assert esp_health(down, now=20_000) == "lost"


def test_module_ok_lost_on_silence_or_lwt():
    def edge(**n):
        return {"connected": True, "nodes": [{"node": "esp-node-01", "online": True, "lastSeenMs": 100_000, **n}]}
    assert esp_health(edge(), now=105_000) == "ok"
    assert esp_health(edge(), now=120_000) == "lost"
    assert esp_health(edge(online=False), now=101_000) == "lost"


def test_module_absent_when_edge_off():
    assert esp_health(None, now=60_000) is None


# ---- API avec l'ESP simulé (EDGE=mock) ----
@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 200
        yield c


def test_api_edge_mock_end_to_end(client):
    state = client.get("/api/edge").json()
    assert state["source"] == "mock" and state["connected"] and state["nodes"][0]["node"] == "esp-node-01"

    with client.websocket_connect("/ws") as ws:
        hello = json.loads(ws.receive_text())
        assert hello["type"] == "hello" and hello["data"]["edge"]["source"] == "mock"

        assert client.post("/api/mock/gas").json() == {"ok": True}
        assert client.post("/api/mock/presence").json() == {"ok": True}
        deadline, keys = time.time() + 20, set()
        while time.time() < deadline and not {"gas_esp-node-01", "presence_esp-node-01"} <= keys:
            m = json.loads(ws.receive_text())
            if m["type"] == "alert":
                keys.add(m["data"]["key"])
        assert {"gas_esp-node-01", "presence_esp-node-01"} <= keys

    assert client.get("/api/modules").json()["esp8266"]["state"] in ("ok", "unknown")
    assert client.post("/api/mock/nope").status_code == 400


def test_api_gas_raises_threat_score(client):
    """La fuite de gaz simulée sur l'ESP fait monter le score de menace jusqu'à « Menace » (plancher du gaz)."""
    with client.websocket_connect("/ws") as ws:
        json.loads(ws.receive_text())  # hello
        client.post("/api/mock/gas")
        deadline, best = time.time() + 25, 0
        while time.time() < deadline and best < 60:
            m = json.loads(ws.receive_text())
            if m["type"] == "analysis" and m["data"]["ok"]:
                best = max(best, m["data"]["threat"]["score"])
        assert best >= 60
