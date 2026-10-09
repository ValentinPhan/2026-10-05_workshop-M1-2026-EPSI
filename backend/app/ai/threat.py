"""Score de menace : fusion des capteurs (partagée par le faux modèle et le modèle local).

Trois familles de signaux :
  - intrusion, en somme pondérée : personne vue par la caméra 40 %, proximité (ultrason) 20 %, présence (PIR de
    l'ESP8266) 10 %, chaleur (thermique) 15 %, anomalie d'environnement (DHT22) 15 % ;
  - présence confirmée, en plancher : une personne détectée avec la confiance qui déclenche l'alerte d'intrusion
    (config.thresholds.person_confidence) impose « Menace » (60 à 70 selon la confiance). La caméra seule plafonnait à
    40 (« Vigilance ») : une personne vue ne déclenchait jamais l'alerte ;
  - danger immédiat, en plancher : le gaz (MQ-2 de l'ESP8266) impose un score minimal. Une fuite de gaz est une
    menace même sans personne dans la pièce ; dans une somme pondérée elle serait diluée (« Calme » à 15 points).
    Plancher : 0 sous la moitié du seuil d'alerte, 70 (« Menace ») au seuil, linéaire entre les deux.

Les planchers ne s'additionnent pas : un score déjà plus haut reste tel quel.

L'Edge Node arrive dans `snapshot["edge"]` (état de edge.py, joint par le Hub au moment de l'analyse). Un boîtier
hors ligne ou muet depuis plus de EDGE_TIMEOUT_S ne compte pas, comme un capteur muet du Pi.
"""
from ..clock import now_ms
from ..config import config
from ..providers.motor import clamp

VIGILANCE_FROM, MENACE_FROM = 30, 60  # scores à partir desquels le niveau est « Vigilance » / « Menace »
GAS_FLOOR_AT_THRESHOLD = 70  # score minimal quand le gaz atteint le seuil d'alerte (≥ MENACE_FROM = « Menace »)


def _edge_signals(edge: dict | None) -> tuple[float, float]:
    """(présence PIR 0|1, risque gaz 0..1) sur les boîtiers en ligne et récents ; (0, 0) sans Edge Node."""
    if not edge:
        return 0.0, 0.0
    now = now_ms()
    threshold = edge.get("gasThreshold") or 0
    pir = gas = 0.0
    for n in edge.get("nodes") or []:
        seen = n.get("lastSeenMs")
        if not n.get("online") or not isinstance(seen, (int, float)) or now - seen > config.edge.timeout_s * 1000:
            continue
        if n.get("pir") == 1:
            pir = 1.0
        if isinstance(n.get("gasRaw"), (int, float)) and threshold > 0:
            gas = max(gas, clamp((n["gasRaw"] - threshold / 2) / (threshold / 2), 0, 1))
    return pir, gas


def threat_score(snapshot: dict, detections: list[dict], env: dict | None) -> dict:
    person = max([d["confidence"] for d in detections if d["label"] == "person"], default=0)
    # un capteur muet (voir modules.py) ne compte pas dans le score au lieu de faire échouer toute l'analyse
    distance = (snapshot.get("ultrasonic") or {}).get("distanceCm")
    max_c = (snapshot.get("thermal") or {}).get("maxC")
    prox = clamp((200 - distance) / 150, 0, 1) if distance is not None else 0
    heat = clamp((max_c - 30) / 25, 0, 1) if max_c is not None else 0
    env_risk = env["score"] / 100 if env else 0
    pir, gas = _edge_signals(snapshot.get("edge"))
    weighted = 100 * (0.40 * person + 0.20 * prox + 0.10 * pir + 0.15 * heat + 0.15 * env_risk)
    score = round(max(weighted, GAS_FLOOR_AT_THRESHOLD * gas))
    if person >= config.thresholds.person_confidence:
        score = max(score, MENACE_FROM + round(10 * person))
    label = "Calme" if score < VIGILANCE_FROM else "Vigilance" if score < MENACE_FROM else "Menace"
    return {"score": score, "label": label}
