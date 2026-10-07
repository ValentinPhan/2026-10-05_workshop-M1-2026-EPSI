"""Score de menace : fusion des capteurs (partagée par le faux modèle et le modèle local)."""
from ..providers.motor import clamp


def threat_score(snapshot: dict, detections: list[dict], env: dict | None) -> dict:
    """Présence (caméra) 45 %, proximité (ultrason) 25 %, chaleur (thermique) 15 %, environnement (DHT22) 15 %."""
    person = max([d["confidence"] for d in detections if d["label"] == "person"], default=0)
    # un capteur muet (voir modules.py) ne compte pas dans le score au lieu de faire échouer toute l'analyse
    distance = (snapshot.get("ultrasonic") or {}).get("distanceCm")
    max_c = (snapshot.get("thermal") or {}).get("maxC")
    prox = clamp((200 - distance) / 150, 0, 1) if distance is not None else 0
    heat = clamp((max_c - 30) / 25, 0, 1) if max_c is not None else 0
    env_risk = env["score"] / 100 if env else 0
    score = round(100 * (0.45 * person + 0.25 * prox + 0.15 * heat + 0.15 * env_risk))
    label = "Calme" if score < 30 else "Vigilance" if score < 60 else "Menace"
    return {"score": score, "label": label}
