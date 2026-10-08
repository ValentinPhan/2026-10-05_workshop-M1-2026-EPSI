"""Analyseur factice : remplace le modèle IA tant qu'il n'existe pas.

Il ne reçoit que des données BRUTES (comme le vrai modèle) : matrice thermique + ultrason + DHT22.
Une "personne" = tache chaude sur la matrice ET obstacle plus proche que le mur.
Le DHT22 donne la vraie température ambiante et alimente la détection d'anomalies d'environnement.
"""
import random
import time

from ..providers.motor import clamp
from .env_anomaly import EnvDetector
from .threat import threat_score

GRID = 8
EMPTY_DISTANCE_CM = 300  # distance mesurée quand la pièce est vide


def _detect_person(snapshot: dict) -> list[dict]:
    thermal, distance = snapshot.get("thermal"), (snapshot.get("ultrasonic") or {}).get("distanceCm")
    if not thermal or distance is None:  # capteur muet (voir modules.py) : rien à analyser
        return []
    # Ambiante : mesure du DHT22 si disponible (fiable même si une personne remplit le champ),
    # sinon médiane de la matrice. +1 °C : la matrice lit un peu plus chaud que l'air (murs, objets).
    env_temp = (snapshot.get("environment") or {}).get("tempC")
    if isinstance(env_temp, (int, float)):
        ambient = env_temp + 1
    else:
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


class MockAnalyzer:
    name = "heuristique (mock)"

    def __init__(self) -> None:
        self._env = EnvDetector()

    def analyze(self, snapshot: dict) -> dict:
        time.sleep(random.uniform(0.15, 0.4))  # simule le temps de calcul d'un vrai modèle
        detections = _detect_person(snapshot)
        environment = self._env.update(snapshot.get("environment"))
        return {
            "detections": detections,
            "threat": threat_score(snapshot, detections, environment),
            "environment": environment,
        }
