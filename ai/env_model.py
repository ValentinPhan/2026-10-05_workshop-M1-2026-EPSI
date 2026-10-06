#!/usr/bin/env python3
"""Détection d'anomalies d'environnement sur le DHT22 (Isolation Forest, non supervisé).

Principe : on enregistre quelques jours de fonctionnement NORMAL de la pièce (pi/dht22_reader.py --csv),
le modèle apprend seul à quoi ressemble la normale, puis note chaque nouvelle mesure de 0 à 100.
Pas besoin d'étiqueter des incendies ou des fenêtres ouvertes. Léger : tourne aussi sur le Pi.

Variables (mêmes idées que la version en ligne backend/app/ai/env_anomaly.py) :
  temp, hum, écart au point de rosée, pentes sur 1 / 5 / 15 min, écart-type sur 5 min,
  heure de la journée en sin/cos (le modèle apprend le cycle jour / nuit).

Usage :
  python3 env_model.py train dht22_log.csv            # -> env_model.joblib
  python3 env_model.py score dht22_log.csv             # note la dernière mesure du fichier
  python3 env_model.py demo                            # données synthétiques, sans capteur

Dans le backend (LocalAnalyzer, voir backend/app/ai/local_analyzer.py) :
  garder une fenêtre glissante de 15 min des `snapshot["environment"]` reçus et renvoyer
  `environment = score_window(window_df, model)` dans le résultat de analyze().
  Copier env_model.joblib dans backend/models/ pour que le backend le charge.
"""
import math
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

MODEL_PATH = "env_model.joblib"


def dew_point(t, rh, a=17.62, b=243.12):
    """Point de rosée (formule de Magnus)."""
    g = np.log(np.clip(rh, 1, 100) / 100) + a * t / (b + t)
    return b * g / (a - g)


def features(df):
    """df : index datetime, colonnes temp, hum (une ligne toutes les ~2 s)."""
    df = df[["temp", "hum"]].rolling(5, center=True, min_periods=1).median()  # anti-glitch
    f = pd.DataFrame(index=df.index)
    f["temp"], f["hum"] = df.temp, df.hum
    f["dew_gap"] = df.temp - dew_point(df.temp, df.hum)
    for w in ("1min", "5min", "15min"):
        f[f"dT_{w}"] = df.temp.diff().rolling(w).sum()  # variation sur la fenêtre (°C)
        f[f"dH_{w}"] = df.hum.diff().rolling(w).sum()
    f["std_T_5min"] = df.temp.rolling("5min").std()
    h = df.index.hour + df.index.minute / 60
    f["h_sin"], f["h_cos"] = np.sin(2 * np.pi * h / 24), np.cos(2 * np.pi * h / 24)
    return f.dropna()


REASONS = {
    "temp": ("température anormalement haute", "température anormalement basse"),
    "hum": ("humidité anormalement haute", "humidité anormalement basse"),
    "dT_1min": ("température qui monte vite", "température qui chute vite"),
    "dH_1min": ("humidité qui monte vite", "humidité qui chute vite"),
}


def train(df):
    X = features(df)
    model = IsolationForest(n_estimators=200, contamination=0.01, random_state=0).fit(X)
    # Calibration : le score "brut" des données normales sert de référence pour l'échelle 0..100
    raw = -model.score_samples(X)
    model.calib_ = (float(np.percentile(raw, 50)), float(np.percentile(raw, 99.5)))
    # Moyenne / écart-type de la normale, pour expliquer le score (raisons lisibles)
    model.ref_ = {k: (float(X[k].mean()), max(float(X[k].std()), 1e-6)) for k in REASONS}
    return model


def score_window(df, model):
    """Note la dernière mesure de `df` -> même format que backend/app/ai/env_anomaly.py."""
    X = features(df)
    x = X.iloc[[-1]]
    lo, hi = model.calib_
    raw = -model.score_samples(x)[0]  # plus grand = plus anormal
    score = int(np.clip((raw - lo) / (hi - lo) * 70, 0, 100))  # 70 = limite des 0,5 % les plus rares
    t, h, slope = (float(x[k].iloc[0]) for k in ("temp", "hum", "dT_1min"))
    dew = float(dew_point(t, h))

    # Raisons lisibles : variables les plus éloignées de leur distribution normale
    reasons = []
    for k, (up, down) in REASONS.items():
        mean, std = model.ref_[k]
        z = (x[k].iloc[0] - mean) / std
        if abs(z) > 3:
            reasons.append(up if z > 0 else down)

    # Garde-fous déterministes
    if t > 45 or slope > 2:
        score = 100
        reasons.insert(0, "montée de température critique (risque incendie / surchauffe)")
    if t - dew < 1.5:
        score = max(score, 70)
        reasons.append("air proche de la saturation (risque de condensation)")

    label = "Normal" if score < 40 else "Inhabituel" if score < 70 else "Anomalie"
    return {"score": score, "label": label, "dewPointC": round(dew, 1), "reasons": reasons}


def load_csv(path):
    return pd.read_csv(path, index_col="ts", parse_dates=True).sort_index()


def synthetic(days=3, anomaly=None):
    """Pièce simulée : cycle jour/nuit + bruit ; `anomaly` = 'fire' | 'window' sur les 10 dernières minutes."""
    idx = pd.date_range("2026-10-01", periods=int(days * 86400 / 2), freq="2s")
    hours = np.asarray(idx.hour + idx.minute / 60)
    rng = np.random.default_rng(0)
    temp = 22 + 1.5 * np.sin(2 * np.pi * (hours - 9) / 24) + rng.normal(0, 0.1, len(idx))
    hum = 48 - 4 * np.sin(2 * np.pi * (hours - 9) / 24) + rng.normal(0, 0.3, len(idx))
    if anomaly:
        n = 300  # 10 min
        ramp = np.linspace(0, 1, n)
        if anomaly == "fire":
            temp[-n:] += 25 * ramp
            hum[-n:] -= 30 * ramp
        elif anomaly == "window":
            temp[-n:] -= 6 * np.minimum(ramp * 4, 1)
            hum[-n:] += 25 * np.minimum(ramp * 4, 1)
    return pd.DataFrame({"temp": temp, "hum": np.clip(hum, 0, 100)}, index=idx)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "demo"
    if cmd == "train":
        model = train(load_csv(argv[2]))
        joblib.dump(model, MODEL_PATH)
        print(f"modèle enregistré dans {MODEL_PATH}")
    elif cmd == "score":
        model = joblib.load(MODEL_PATH)
        df = load_csv(argv[2])
        print(score_window(df[df.index >= df.index[-1] - pd.Timedelta("15min")], model))
    elif cmd == "demo":
        model = train(synthetic())
        for name in (None, "window", "fire"):
            df = synthetic(days=0.05, anomaly=name)
            df.index = df.index + pd.Timedelta(hours=14)  # mêmes heures que l'entraînement
            print(f"{name or 'normal':>7} -> {score_window(df, model)}")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
