"""Liaison MQTT avec le broker du Raspberry : validation, enregistrement idempotent, ACK, démarrage non bloquant.

Lancer (depuis backend/, venv actif) :  python -m pytest tests -q
"""
import asyncio
import json
import socket
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import PiMqttConfig
from app.db import Database
from app.pi_mqtt import PiMqttLink, parse_message
from conftest import TMP


def payload(**extra) -> bytes:
    return json.dumps({"event_id": "e-1", "timestamp": "2026-10-09T10:00:00+00:00", "event_type": "temperature", "value": 24.7, **extra}).encode()


# ---- parse_message ----
def test_valid_message():
    e = parse_message("sentinel/test-pc/telemetry", payload())
    assert (e["eventId"], e["deviceId"], e["category"], e["eventType"]) == ("e-1", "test-pc", "telemetry", "temperature")
    assert e["timestamp"].year == 2026 and e["payload"]["value"] == 24.7


@pytest.mark.parametrize("topic, body", [
    ("sentinel/pi/ack", payload()),  # notre propre ACK n'est pas une donnée
    ("sentinel/pi", payload()),
    ("autre/pi/telemetry", payload()),
    ("sentinel/pi/cyber", b"pas du json"),
    ("sentinel/pi/cyber", b"[1, 2]"),
    ("sentinel/pi/cyber", json.dumps({"timestamp": "2026-10-09T10:00:00Z"}).encode()),
    ("sentinel/pi/cyber", json.dumps({"event_id": "e", "timestamp": "hier"}).encode()),
    ("sentinel/pi/status", b"{" + b" " * 20000 + b"}"),
])
def test_invalid_messages(topic, body):
    with pytest.raises(ValueError):
        parse_message(topic, body)


# ---- base + ACK ----
@pytest.fixture
def db():
    d = Database(f"sqlite:///{Path(TMP, f'pi-{time.monotonic_ns()}.db').as_posix()}")
    d.init()
    return d


def test_save_is_idempotent(db):
    e = parse_message("sentinel/test-pc/telemetry", payload())
    assert db.save_pi_event(e) is True
    assert db.save_pi_event(e) is False  # renvoi QoS 1 : pas de doublon
    events = db.recent_pi_events(10)
    assert len(events) == 1 and events[0]["payload"]["value"] == 24.7


class FakeClient:
    def __init__(self):
        self.published = []

    def publish(self, topic, data, qos):
        self.published.append((topic, json.loads(data), qos))


def test_message_stored_then_acked(db):
    link = PiMqttLink(PiMqttConfig(password="x"), db)
    client = FakeClient()
    msg = SimpleNamespace(topic="sentinel/test-pc/cyber", payload=payload(event_type="scan"))
    link._on_message(client, None, msg)
    link._on_message(client, None, msg)  # doublon : ré-acquitté (déjà stocké), pas réenregistré
    assert client.published == [("sentinel/test-pc/ack", {"event_id": "e-1", "status": "stored"}, 1)] * 2
    s = link.state()
    assert (s["received"], s["stored"], s["byCategory"]["cyber"], s["last"]["eventType"]) == (2, 1, 2, "scan")


def test_invalid_message_not_acked(db):
    link = PiMqttLink(PiMqttConfig(password="x"), db)
    client = FakeClient()
    link._on_message(client, None, SimpleNamespace(topic="sentinel/pi/telemetry", payload=b"{}"))
    assert client.published == [] and link.state()["invalid"] == 1


# ---- jamais bloquant ----
def test_start_with_unreachable_broker_does_not_block():
    with socket.socket() as s:  # port libre, rien n'écoute dessus
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    ca = str(Path(__file__).resolve().parents[2] / "infra" / "pi-broker" / "ca.crt")
    link = PiMqttLink(replace(PiMqttConfig(), host="nom-introuvable.invalid", port=port, password="x", ca=ca, fallback_ip="127.0.0.1"))

    async def run():
        started = time.monotonic()
        await link.start()
        assert time.monotonic() - started < 1  # rend la main tout de suite
        await asyncio.sleep(1.5)
        await link.stop()

    asyncio.run(run())
    s = link.state()
    assert s["connected"] is False and "injoignable" in s["error"]


def test_missing_ca_disables_link_without_crash():
    link = PiMqttLink(replace(PiMqttConfig(), password="x", ca="introuvable.crt"))
    asyncio.run(link.start())
    assert link.state()["connected"] is False and "désactivée" in link.state()["error"]


def test_enabled_only_with_password():
    assert not replace(PiMqttConfig(), mode="auto", password="").enabled
    assert replace(PiMqttConfig(), mode="auto", password="x").enabled
    assert not replace(PiMqttConfig(), mode="off", password="x").enabled
