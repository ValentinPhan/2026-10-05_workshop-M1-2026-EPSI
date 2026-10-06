"""Moteur d'alertes, indépendant du provider et du modèle IA.

Deux chemins :
  - evaluate_sensors(snapshot)  : seuils sur la donnée brute (immédiat, marche sans IA)
  - evaluate_analysis(analysis) : règles qui dépendent du modèle IA (intrusion, anomalie d'environnement)
Une alerte est émise au passage "condition fausse -> vraie" (pas à chaque tick).
"""
from .config import Thresholds


class AlertEngine:
    def __init__(self, thresholds: Thresholds, size: int):
        self._th = thresholds
        self._size = size
        self._alerts: list[dict] = []
        self._active: set[str] = set()
        self._next_id = 1

    def _run(self, rules: list[dict], ts: int) -> list[dict]:
        created = []
        for rule in rules:
            if rule["on"] and rule["key"] not in self._active:
                self._active.add(rule["key"])
                alert = {
                    "id": self._next_id,
                    "ts": ts,
                    "level": rule["level"],
                    "key": rule["key"],
                    "message": rule["message"],
                }
                self._next_id += 1
                self._alerts.insert(0, alert)
                created.append(alert)
            elif not rule["on"]:
                self._active.discard(rule["key"])
        del self._alerts[self._size :]
        return created

    def evaluate_sensors(self, s: dict) -> list[dict]:
        distance, max_c = s["ultrasonic"]["distanceCm"], s["thermal"]["maxC"]
        return self._run(
            [
                {
                    "key": "proximity",
                    "level": "warning",
                    "on": distance < self._th.proximity_cm,
                    "message": f"Objet à {round(distance)} cm du capteur ultrason",
                },
                {
                    "key": "heat",
                    "level": "warning",
                    "on": max_c > self._th.heat_max_c,
                    "message": f"Pic thermique : {max_c} °C (seuil {self._th.heat_max_c:g} °C)",
                },
            ],
            s["ts"],
        )

    def evaluate_analysis(self, a: dict) -> list[dict]:
        # Modèle indisponible : on ne touche pas aux alertes IA, rien n'est analysé.
        if not a["ok"]:
            return []
        person = next(
            (d for d in a["detections"] if d["label"] == "person" and d["confidence"] >= self._th.person_confidence),
            None,
        )
        env = a.get("environment")
        return self._run(
            [
                {
                    "key": "intrusion",
                    "level": "critical",
                    "on": person is not None,
                    "message": (
                        f"Intrusion détectée par le modèle IA (personne, {round(person['confidence'] * 100)} %)"
                        if person
                        else ""
                    ),
                },
                {
                    "key": "environment",
                    "level": "warning",
                    "on": bool(env and env["score"] >= self._th.env_anomaly_score),
                    "message": (
                        f"Anomalie d'environnement (DHT22, score {env['score']}) : "
                        f"{', '.join(env['reasons']) or 'écart à la normale'}"
                        if env
                        else ""
                    ),
                },
            ],
            a["ts"],
        )

    def list(self) -> list[dict]:
        return self._alerts
