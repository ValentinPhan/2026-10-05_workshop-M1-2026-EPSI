"""Moteur d'alertes, indépendant du provider et du modèle IA.

Deux chemins :
  - evaluate_sensors(snapshot)  : seuils sur la donnée brute (immédiat, marche sans IA)
  - evaluate_analysis(analysis) : règles qui dépendent du modèle IA (intrusion, anomalie d'environnement)
  - evaluate_edge(edge)         : Edge Node ESP8266 (gaz MQ-2, présence PIR), à chaque message MQTT
Une alerte est émise au passage "condition fausse -> vraie" (pas à chaque tick).

Avec le service de vision (ANALYZER=local), l'intrusion vient directement de ses événements
(intrusion_started / intrusion_ended : immédiat, avec la photo) et non du résultat d'analyse en différé.
"""
import time

from .config import Thresholds
from .logger import logger
from .modules import CRITICAL, LABELS


class AlertEngine:
    def __init__(
        self, thresholds: Thresholds, size: int, intrusion_from_vision: bool = False, initial: list[dict] | None = None
    ):
        self._th = thresholds
        self._size = size
        self._intrusion_from_vision = intrusion_from_vision
        # `initial` : historique relu en base (les plus récentes d'abord), pour que le journal survive à un redémarrage
        self._alerts: list[dict] = list(initial or [])[:size]
        self._active: set[str] = set()
        self._next_id = max((a["id"] for a in initial or []), default=0) + 1

    def active(self) -> list[str]:
        """Clés des alertes dont la condition est toujours vraie."""
        return sorted(self._active)

    def _add(self, ts: int, level: str, key: str, message: str, **extra) -> dict:
        alert = {"id": self._next_id, "ts": ts, "level": level, "key": key, "message": message, **extra}
        self._next_id += 1
        self._alerts.insert(0, alert)
        del self._alerts[self._size :]
        return alert

    def _run(self, rules: list[dict], ts: int) -> list[dict]:
        created = []
        for rule in rules:
            if rule["on"] and rule["key"] not in self._active:
                self._active.add(rule["key"])
                created.append(self._add(ts, rule["level"], rule["key"], rule["message"]))
            elif not rule["on"]:
                if rule["key"] in self._active:
                    logger.emit("alert.resolved", f"Fin de l'alerte « {rule['key']} »", key=rule["key"], alertLevel=rule["level"])
                self._active.discard(rule["key"])
        return created

    def intrusion_started(self, event: dict) -> dict:
        """Intrusion (ou personne de plus) détectée par la caméra ; `event["snapshot"]` = URL de la photo."""
        self._active.add("intrusion")
        n = event.get("personCount", 1)
        confidence = round(event["confidence"] * 100)
        if event.get("event") == "new_person":
            message = f"Nouvelle personne détectée ({n} au total, {confidence} %)"
        else:
            message = f"Intrusion détectée par la caméra ({n} personne{'s' if n > 1 else ''}, {confidence} %)"
        extra = {"snapshot": event["snapshot"]} if event.get("snapshot") else {}  # pas de photo en mode dev
        return self._add(event["ts"], "critical", "intrusion", message, **extra)

    def evaluate_modules(self, states: dict[str, dict]) -> list[dict]:
        """Une alerte « perte de connexion » par module dont l'état est « lost » (retirée quand il revient)."""
        return self._run(
            [
                {
                    "key": f"module_{name}",
                    "level": "critical" if name in CRITICAL else "warning",
                    "on": state["state"] == "lost",
                    "message": f"Perte de connexion : {LABELS[name]} ({state['reason']})",
                }
                for name, state in states.items()
            ],
            int(time.time() * 1000),
        )

    def intrusion_ended(self) -> None:
        self._active.discard("intrusion")

    def evaluate_sensors(self, s: dict) -> list[dict]:
        distance = (s.get("ultrasonic") or {}).get("distanceCm")
        max_c = (s.get("thermal") or {}).get("maxC")
        rules = []
        # capteur muet : pas de règle (l'alerte en cours reste telle quelle, la perte est signalée par modules.py)
        if distance is not None:
            rules.append({
                "key": "proximity",
                "level": "warning",
                "on": distance < self._th.proximity_cm,
                "message": f"Objet à {round(distance)} cm du capteur ultrason",
            })
        if max_c is not None:
            rules.append({
                "key": "heat",
                "level": "warning",
                "on": max_c > self._th.heat_max_c,
                "message": f"Pic thermique : {max_c} °C (seuil {self._th.heat_max_c:g} °C)",
            })
        return self._run(rules, s["ts"])

    def evaluate_edge(self, edge: dict) -> list[dict]:
        """Gaz au-delà du seuil et présence PIR, par boîtier. Un boîtier hors ligne ne touche pas à ses alertes
        (sa perte est signalée par modules.py)."""
        rules = []
        for n in edge.get("nodes") or []:
            if not n.get("online"):
                continue
            node, gas = n["node"], n.get("gasRaw")
            if gas is not None:
                rules.append({
                    "key": f"gas_{node}",
                    "level": "critical",
                    "on": gas >= self._th.gas_raw,
                    "message": f"Gaz détecté par {node} : MQ-2 à {gas} / 1023 (seuil {self._th.gas_raw:g})",
                })
            if n.get("pir") is not None:
                rules.append({
                    "key": f"presence_{node}",
                    "level": "warning",
                    "on": n["pir"] == 1,
                    "message": f"Présence détectée par le capteur PIR de {node}",
                })
        return self._run(rules, int(time.time() * 1000))

    def evaluate_analysis(self, a: dict) -> list[dict]:
        # Modèle indisponible : on ne touche pas aux alertes IA, rien n'est analysé.
        if not a["ok"]:
            return []
        person = next(
            (d for d in a["detections"] if d["label"] == "person" and d["confidence"] >= self._th.person_confidence),
            None,
        )
        env = a.get("environment")

        rules = []
        if not self._intrusion_from_vision:
            rules.append(
                {
                    "key": "intrusion",
                    "level": "critical",
                    "on": person is not None,
                    "message": (
                        f"Intrusion détectée par le modèle IA (personne, {round(person['confidence'] * 100)} %)"
                        if person
                        else ""
                    ),
                }
            )
        rules.append(
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
            }
        )
        return self._run(rules, a["ts"])

    def list(self) -> list[dict]:
        return self._alerts
