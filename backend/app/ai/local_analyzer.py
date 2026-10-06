"""Modèle IA local (YOLO + détection d'anomalies) — À IMPLÉMENTER par l'équipe IA.

Activation : lancer le backend avec ANALYZER=local.
Les poids du modèle vont dans backend/models/.

Contrat : une classe avec
  name : str
  analyze(snapshot: dict) -> dict      (SYNCHRONE et bloquante : c'est normal)

Le backend appelle analyze() dans un thread (asyncio.to_thread) : un modèle lent ne
bloque ni l'API ni l'affichage des données brutes. Si le modèle est occupé, les snapshots
intermédiaires sont sautés (pas de file d'attente). Si analyze() lève une exception, le
dashboard affiche « IA hors ligne » et continue de fonctionner.

Entrée  : le snapshot brut du Raspberry
          { ts, ultrasonic:{distanceCm,maxRangeCm}, thermal:{avgC,maxC,grid[8][8]},
            camera:{streamUrl,width,height,fps}, motor:{...}, system:{...} }
          L'image n'est pas dans le snapshot : lire le flux via camera.streamUrl
          (ou la webcam du PC en attendant).

Sortie  : { "detections": [{ "label": "person", "confidence": 0..1,
                             "bbox": {"x","y","w","h"} }],      # bbox normalisée 0..1
            "threat": { "score": 0..100, "label": "Calme" | "Vigilance" | "Menace" } }
"""


class LocalAnalyzer:
    name = "modèle IA local"

    def __init__(self) -> None:
        # TODO : charger le modèle depuis backend/models/ (une seule fois, ici).
        raise NotImplementedError("Modèle IA local non implémenté : lancer avec ANALYZER=mock")

    def analyze(self, snapshot: dict) -> dict:
        raise NotImplementedError
