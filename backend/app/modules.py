"""Santé des modules : détecte qu'un module ne donne plus signe de vie, et quand il revient.

Modules surveillés (une entrée chacun dans l'état renvoyé) :
  raspberry   plus aucun snapshot reçu depuis MODULE_TIMEOUT_S secondes (liaison / Pi / provider coupé)
  ultrasonic  snapshot reçu mais sans mesure de distance valide
  thermal     snapshot reçu mais sans matrice thermique valide
  dht22       aucune mesure, ou dernière lecture plus vieille que DHT_STALE_S secondes
  motor       état moteur absent du snapshot
  camera      caméra externe : flux interrompu / injoignable, ou plus d'images alors qu'elle en envoyait
  ai          le modèle d'analyse ne répond plus

Quand le Raspberry est injoignable, ses capteurs ne sont pas évalués (indéterminés) : une seule perte est signalée,
la bonne. Chaque état est « ok », « lost » ou « unknown » (pas encore de preuve dans un sens ou dans l'autre).
Seuls les passages ok/unknown -> lost et lost -> ok produisent une transition (donc un événement du journal).
Logique pure, sans I/O : le Hub l'appelle périodiquement et journalise / alerte (voir hub._watch_modules).
"""
from typing import Any

LABELS = {
    "raspberry": "Raspberry Pi",
    "ultrasonic": "capteur ultrason",
    "thermal": "caméra thermique",
    "dht22": "capteur DHT22",
    "motor": "moteur",
    "camera": "caméra",
    "ai": "modèle IA",
}
CRITICAL = {"raspberry", "camera"}  # niveau d'alerte « critical » ; les autres sont « warning »

Health = tuple[bool | None, str | None]  # (ok ?, raison) ; ok=None : indéterminé


def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class ModuleMonitor:
    def __init__(self, timeout_s: float, dht_stale_s: float, started_ms: int):
        self._timeout_ms = timeout_s * 1000
        self._dht_stale_ms = dht_stale_s * 1000
        self._started_ms = started_ms
        self._camera_was_running = False
        self._states: dict[str, dict] = {}

    def states(self) -> dict[str, dict]:
        return {name: dict(state) for name, state in self._states.items()}

    def reset_camera(self) -> None:
        """Changement de source vidéo voulu par un admin : l'attente d'images qui suit n'est pas une perte."""
        self._camera_was_running = False

    # ---- évaluation ----
    def _health(self, now: int, snapshot: dict | None, snapshot_at: int | None, vision: dict | None, analysis: dict | None) -> dict[str, Health]:
        health: dict[str, Health] = {}

        age = now - (snapshot_at if snapshot_at is not None else self._started_ms)
        if age > self._timeout_ms:
            reason = f"aucune donnée depuis {age / 1000:.0f} s" if snapshot_at is not None else "aucune donnée reçue depuis le démarrage"
            health["raspberry"] = (False, reason)
        else:
            health["raspberry"] = (True, None)
        up = health["raspberry"][0] is True and snapshot is not None

        def sensor(name: str, ok: bool, reason: str) -> None:
            health[name] = (None, None) if not up else ((True, None) if ok else (False, reason))

        s = snapshot or {}
        u, t, m = s.get("ultrasonic"), s.get("thermal"), s.get("motor")
        sensor("ultrasonic", isinstance(u, dict) and _num(u.get("distanceCm")), "aucune mesure de distance valide")
        sensor("thermal", isinstance(t, dict) and _num(t.get("avgC")) and isinstance(t.get("grid"), list), "aucune matrice thermique valide")
        sensor("motor", isinstance(m, dict) and _num(m.get("angle")), "état moteur absent")

        env = s.get("environment")
        if not up:
            health["dht22"] = (None, None)
        elif not env or env.get("tempC") is None:
            # le DHT22 met quelques secondes à fournir sa première mesure : pas d'alarme pendant ce délai
            health["dht22"] = (None, None) if now - self._started_ms < self._dht_stale_ms else (False, "aucune mesure")
        elif _num(env.get("readAt")) and now - env["readAt"] > self._dht_stale_ms:
            health["dht22"] = (False, f"dernière mesure il y a {(now - env['readAt']) / 1000:.0f} s")
        else:
            health["dht22"] = (True, None)

        if vision and vision.get("enabled", True) and "state" in vision:
            state = vision["state"]
            if state == "running":
                self._camera_was_running = True
                health["camera"] = (True, None)
            elif state == "error":
                health["camera"] = (False, vision.get("error") or "erreur caméra")
            elif state == "waiting" and self._camera_was_running:
                health["camera"] = (False, "plus d'images reçues de la caméra")
            else:
                health["camera"] = (None, None)  # chargement, arrêt, ou en attente d'une première connexion

        if analysis is not None:
            health["ai"] = (True, None) if analysis.get("ok") else (False, analysis.get("error") or "modèle IA indisponible")
        return health

    def check(self, now: int, snapshot: dict | None, snapshot_at: int | None, vision: dict | None, analysis: dict | None) -> list[dict]:
        """Met à jour les états et renvoie les transitions {module, label, to, reason, ...} survenues."""
        transitions = []
        for name, (ok, reason) in self._health(now, snapshot, snapshot_at, vision, analysis).items():
            state = self._states.setdefault(name, {"state": "unknown", "sinceMs": now, "lastOkMs": None, "reason": None})
            if ok is None:
                continue
            new = "ok" if ok else "lost"
            if ok:
                state["lastOkMs"] = now
            state["reason"] = reason
            if new == state["state"]:
                continue
            previous, since = state["state"], state["sinceMs"]
            state["state"], state["sinceMs"] = new, now
            if new == "lost":
                transitions.append({"module": name, "label": LABELS[name], "to": "lost", "reason": reason, "lastOkMs": state["lastOkMs"], "downMs": None})
            elif previous == "lost":
                transitions.append({"module": name, "label": LABELS[name], "to": "ok", "reason": None, "lastOkMs": now, "downMs": now - since})
        return transitions
