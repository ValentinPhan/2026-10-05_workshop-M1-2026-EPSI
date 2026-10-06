"""Analyseur local : détections YOLO réelles + fusion des capteurs.

Activation : lancer le backend avec ANALYZER=local (nécessite `pip install -r requirements-vision.txt`).

Les détections viennent du service de vision (app/vision/ : caméra + YOLOv8 dans un thread dédié) ;
ici on les combine avec les capteurs du Pi pour produire le même résultat que le faux modèle :

  Entrée  : le snapshot brut du Raspberry
            { ts, ultrasonic:{distanceCm,maxRangeCm}, thermal:{avgC,maxC,grid[8][8]},
              camera:{streamUrl,width,height,fps}, motor:{...},
              environment:{tempC,humidityPct,readAt}, system:{...} }

  Sortie  : { "detections": [{ "label": "person", "confidence": 0..1,
                               "bbox": {"x","y","w","h"} }],      # bbox normalisée 0..1
              "threat": { "score": 0..100, "label": "Calme" | "Vigilance" | "Menace" },
              "environment": { "score": 0..100, "label", "dewPointC", "reasons": [str] } }  # optionnel

`analyze()` est synchrone : le hub l'appelle dans un thread, un traitement long ne bloque pas l'API.

Pour remplacer la détection d'anomalies d'environnement par le modèle entraîné (Isolation Forest,
ml/environment/env_model.py) : charger env_model.joblib depuis backend/models/ dans __init__ et appeler
score_window(fenêtre glissante de 15 min des snapshot["environment"], modèle) à la place de EnvDetector.
"""
from ..vision.service import VisionService
from .env_anomaly import EnvDetector
from .threat import threat_score


class LocalAnalyzer:
    name = "YOLO + fusion capteurs"

    def __init__(self, vision: VisionService | None) -> None:
        if vision is None:
            raise ValueError("ANALYZER=local nécessite le service de vision (app/vision/)")
        self._vision = vision
        self._env = EnvDetector()

    def analyze(self, snapshot: dict) -> dict:
        detections = self._vision.latest_detections()  # [] si la caméra ou YOLO ne répond plus
        environment = self._env.update(snapshot.get("environment"))
        return {
            "detections": detections,
            "threat": threat_score(snapshot, detections, environment),
            "environment": environment,
        }
