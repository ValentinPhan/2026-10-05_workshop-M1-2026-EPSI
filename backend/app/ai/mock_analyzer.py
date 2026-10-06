"""Analyseur factice : remplace le modèle IA tant qu'il n'existe pas.

Il ne reçoit que des données BRUTES (comme le vrai modèle) : matrice thermique + ultrason.
Une "personne" = tache chaude sur la matrice ET obstacle plus proche que le mur.
"""
import random
import time

from ..providers.motor import clamp

GRID = 8
EMPTY_DISTANCE_CM = 300  # distance mesurée quand la pièce est vide


def _detect_person(snapshot: dict) -> list[dict]:
    thermal, distance = snapshot["thermal"], snapshot["ultrasonic"]["distanceCm"]
    flat = [v for row in thermal["grid"] for v in row]
    ambient = sorted(flat)[len(flat) // 2]  # médiane
    body = thermal["maxC"] - ambient
    if body < 4 or distance > EMPTY_DISTANCE_CM - 30:
        return []

    # centre de la tache chaude -> position horizontale dans l'image
    total = weighted_col = 0.0
    for row in thermal["grid"]:
        for c, v in enumerate(row):
            w = max(0.0, v - ambient - 1)
            total += w
            weighted_col += w * c
    x = weighted_col / total / (GRID - 1) if total else 0.5

    prox = clamp((EMPTY_DISTANCE_CM - distance) / 250, 0, 1)
    h = 0.35 + 0.5 * prox
    w = h * 0.45
    return [
        {
            "label": "person",
            "confidence": round(clamp(0.5 + body / 25, 0, 0.99), 2),
            "bbox": {"x": clamp(x - w / 2, 0, 1 - w), "y": clamp(0.95 - h, 0, 1 - h), "w": w, "h": h},
        }
    ]


def _threat_score(snapshot: dict, detections: list[dict]) -> dict:
    """Fusion de capteurs : présence 50 %, proximité 30 %, chaleur 20 %."""
    person = max([d["confidence"] for d in detections if d["label"] == "person"], default=0)
    prox = clamp((200 - snapshot["ultrasonic"]["distanceCm"]) / 150, 0, 1)
    heat = clamp((snapshot["thermal"]["maxC"] - 30) / 25, 0, 1)
    score = round(100 * (0.5 * person + 0.3 * prox + 0.2 * heat))
    label = "Calme" if score < 30 else "Vigilance" if score < 60 else "Menace"
    return {"score": score, "label": label}


class MockAnalyzer:
    name = "heuristique (mock)"

    def analyze(self, snapshot: dict) -> dict:
        time.sleep(random.uniform(0.15, 0.4))  # simule le temps de calcul d'un vrai modèle
        detections = _detect_person(snapshot)
        return {"detections": detections, "threat": _threat_score(snapshot, detections)}
