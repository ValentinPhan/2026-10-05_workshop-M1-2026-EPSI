"""Détection d'anomalies sur le DHT22 (température + humidité de la pièce).

Version "en ligne" sans dépendance, utilisée par l'analyseur mock : elle apprend en continu
la normale de chaque variable (moyenne et variance glissantes, EWMA) et note l'écart de la
mesure courante (z-score). Le modèle entraîné hors ligne (Isolation Forest, ml/environment/env_model.py)
utilise les mêmes variables dérivées et le même format de sortie.

Sortie : {score: 0..100, label: 'Apprentissage'|'Normal'|'Inhabituel'|'Anomalie',
          dewPointC, reasons: [str], learning: bool}
"""
import math

from ..providers.motor import clamp

WINDOW_MS = 15 * 60_000  # historique conservé pour les pentes
SLOPE_MS = 60_000  # pente calculée sur 1 min
WARMUP = 30  # nb de mesures avant de noter (le temps d'apprendre la normale)
ALPHA = 0.02  # vitesse d'apprentissage de la normale


def _high_low(subject: str):
    return lambda d: f"{subject} {'anormalement haute' if d > 0 else 'anormalement basse'}"


# Variables suivies ; `floor` = écart-type minimal (évite les z-scores énormes sur un signal très stable)
FEATURES = {
    "tempC": (0.4, _high_low("température")),
    "humidityPct": (2.0, _high_low("humidité")),
    "dTempPerMin": (0.15, lambda d: "température qui monte vite" if d > 0 else "température qui chute vite"),
    "dHumPerMin": (0.6, lambda d: "humidité qui monte vite" if d > 0 else "humidité qui chute vite"),
}


def dew_point(temp_c: float, humidity_pct: float, a: float = 17.62, b: float = 243.12) -> float:
    """Point de rosée (formule de Magnus) : en dessous, l'air condense."""
    g = math.log(max(humidity_pct, 1) / 100) + (a * temp_c) / (b + temp_c)
    return (b * g) / (a - g)


class EnvDetector:
    def __init__(self) -> None:
        self._readings: list[dict] = []  # {ts, tempC, humidityPct} — une entrée par mesure DHT22 réelle
        self._stats = {k: {"mean": 0.0, "var": 0.0} for k in FEATURES}
        self._count = 0
        self._last: dict | None = None  # {readAt, result}

    def _slope(self, key: str, now: dict) -> float:
        """Pente (unité / min) entre la mesure courante et celle d'il y a ~1 min."""
        ref = next((r for r in self._readings if now["ts"] - r["ts"] <= SLOPE_MS), None)
        if ref is None and self._readings:
            ref = self._readings[0]
        if ref is None:
            return 0.0
        dt_min = (now["ts"] - ref["ts"]) / 60_000
        return (now[key] - ref[key]) / dt_min if dt_min > 0.1 else 0.0

    def _evaluate(self, env: dict) -> dict:
        dew = round(dew_point(env["tempC"], env["humidityPct"]), 1)
        now = {"ts": env["readAt"], "tempC": env["tempC"], "humidityPct": env["humidityPct"]}
        x = {
            "tempC": now["tempC"],
            "humidityPct": now["humidityPct"],
            "dTempPerMin": self._slope("tempC", now),
            "dHumPerMin": self._slope("humidityPct", now),
        }

        # 1) Score statistique : plus grand écart à la normale apprise
        max_z = 0.0
        reasons: list[str] = []
        if self._count >= WARMUP:
            for k, (floor, text) in FEATURES.items():
                sd = max(math.sqrt(self._stats[k]["var"]), floor)
                z = (x[k] - self._stats[k]["mean"]) / sd
                if abs(z) > 3:
                    reasons.append(text(z))
                max_z = max(max_z, abs(z))
        score = round(clamp(((max_z - 2.5) / 4) * 100, 0, 100))

        # 2) Garde-fous déterministes (marchent même pendant l'apprentissage)
        if env["tempC"] > 45 or x["dTempPerMin"] > 2:
            score = 100
            reasons.insert(0, "montée de température critique (risque incendie / surchauffe)")
        if env["tempC"] - dew < 1.5:
            score = max(score, 70)
            reasons.append("air proche de la saturation (risque de condensation)")

        # 3) Apprentissage : la normale n'apprend pas des anomalies, sinon elle finirait par les accepter
        if self._count < WARMUP or score < 40:
            for k in FEATURES:
                s = self._stats[k]
                if self._count == 0:
                    s["mean"] = x[k]
                    continue
                a = 1 / (self._count + 1) if self._count < WARMUP else ALPHA  # moyenne simple pendant l'apprentissage
                d = x[k] - s["mean"]
                s["mean"] += a * d
                s["var"] = (1 - a) * (s["var"] + a * d * d)
            self._count += 1

        learning = self._count < WARMUP
        label = "Apprentissage" if learning else "Normal" if score < 40 else "Inhabituel" if score < 70 else "Anomalie"
        return {"score": score, "label": label, "dewPointC": dew, "reasons": reasons, "learning": learning}

    def update(self, env: dict | None) -> dict | None:
        """`env` = snapshot["environment"] du Pi. Ne recalcule que si une nouvelle mesure DHT22 est arrivée."""
        if not env or not isinstance(env.get("tempC"), (int, float)) or not isinstance(env.get("humidityPct"), (int, float)):
            return None
        if self._last and env["readAt"] == self._last["readAt"]:
            return self._last["result"]

        # lecture aberrante (glitch du protocole) : saut de plus de 5 °C entre deux mesures proches
        prev = self._readings[-1] if self._readings else None
        glitch = bool(prev) and env["readAt"] - prev["ts"] < 10_000 and abs(env["tempC"] - prev["tempC"]) > 5
        if env["humidityPct"] < 0 or env["humidityPct"] > 100 or glitch:
            return self._last["result"] if self._last else None

        result = self._evaluate(env)
        self._readings.append({"ts": env["readAt"], "tempC": env["tempC"], "humidityPct": env["humidityPct"]})
        while self._readings and env["readAt"] - self._readings[0]["ts"] > WINDOW_MS:
            self._readings.pop(0)
        self._last = {"readAt": env["readAt"], "result": result}
        return result
