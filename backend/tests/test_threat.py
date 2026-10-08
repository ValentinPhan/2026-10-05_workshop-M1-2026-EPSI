"""Score de menace : poids des capteurs, PIR de l'ESP8266 et plancher du gaz."""
import time

from app.ai.threat import threat_score

CALM = {"ultrasonic": {"distanceCm": 300}, "thermal": {"maxC": 25}}  # rien devant l'ultrason, rien de chaud


def edge(gas=180, pir=0, online=True, age_s=1, threshold=600):
    node = {"node": "esp-node-01", "online": online, "lastSeenMs": time.time() * 1000 - age_s * 1000, "gasRaw": gas, "pir": pir}
    return {"connected": True, "gasThreshold": threshold, "nodes": [node]}


def score(snapshot=CALM, persons=(), env=None, **edge_kw):
    detections = [{"label": "person", "confidence": c} for c in persons]
    return threat_score({**snapshot, "edge": edge(**edge_kw)} if edge_kw else snapshot, detections, env)


def test_calm_without_edge_and_with_quiet_edge():
    assert score() == {"score": 0, "label": "Calme"}
    assert score(gas=180) == {"score": 0, "label": "Calme"}


def test_weights_of_intrusion_signals():
    assert score(persons=[1.0])["score"] == 40
    assert score(pir=1)["score"] == 10
    assert score({"ultrasonic": {"distanceCm": 50}, "thermal": {"maxC": 25}})["score"] == 20
    assert score({"ultrasonic": {"distanceCm": 50}, "thermal": {"maxC": 55}}, persons=[1.0], env={"score": 100}, pir=1)["score"] == 100


def test_gas_floor():
    assert score(gas=300)["score"] == 0  # moitié du seuil : pas encore de plancher
    assert score(gas=450)["score"] == 35  # à mi-chemin : « Vigilance »
    assert score(gas=600) == {"score": 70, "label": "Menace"}  # au seuil d'alerte
    assert score(gas=1000)["score"] == 70
    # le plancher ne s'ajoute pas : un score déjà plus haut reste tel quel
    assert score(persons=[1.0], pir=1, gas=1000, env={"score": 100}, snapshot={"ultrasonic": {"distanceCm": 50}, "thermal": {"maxC": 25}})["score"] == 85


def test_offline_or_stale_esp_ignored():
    assert score(gas=1000, pir=1, online=False)["score"] == 0
    assert score(gas=1000, pir=1, age_s=60)["score"] == 0
    assert score(gas=None, pir=None)["score"] == 0  # valeurs hors bornes (None) ignorées
