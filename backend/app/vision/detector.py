"""Détecteur YOLO : une image BGR en entrée -> détections de personnes en sortie.

Chaque détection : {label, confidence, bbox: {x, y, w, h}, polygon?}  (coordonnées normalisées 0..1)
  - bbox    : le carré autour de la personne (coin haut-gauche + taille) ;
  - polygon : sa silhouette, seulement avec un modèle de segmentation (yolov8n-seg.pt).

Le dashboard redessine lui-même carrés et silhouettes à partir de ces positions (en rouge). Pour obtenir
en plus l'image avec les dessins incrustés par YOLO, `detect(frame, annotate=True)`.
"""
import threading
from pathlib import Path

PERSON_CLASS = 0  # classe COCO "person"
MAX_POLYGON_POINTS = 60  # une silhouette est simplifiée à ce nombre de points (assez pour un contour lisse)


class YoloDetector:
    def __init__(self, model_path: Path, confidence: float, imgsz: int):
        # Import tardif : ultralytics (et torch) est une dépendance optionnelle, voir requirements-vision.txt
        from ultralytics import YOLO
        from ultralytics.utils.downloads import attempt_download_asset

        if not model_path.is_file():
            # poids officiels Ultralytics (ex. yolov8n-seg.pt) : téléchargés une fois dans backend/models/ (internet requis)
            try:
                attempt_download_asset(str(model_path))
            except Exception:  # noqa: BLE001 — message clair ci-dessous
                pass
        if not model_path.is_file():
            raise FileNotFoundError(f"poids YOLO introuvables et non téléchargeables : {model_path}")
        self._model = YOLO(str(model_path))
        self._confidence = confidence
        self._imgsz = imgsz
        self._lock = threading.Lock()  # le modèle n'est pas thread-safe : thread de vision et requêtes /analyze s'alternent

    def detect(self, frame, annotate: bool = False):
        """Retourne (détections, image annotée par YOLO ou None si annotate=False)."""
        with self._lock:
            result = self._model(
                frame, classes=[PERSON_CLASS], conf=self._confidence, imgsz=self._imgsz, verbose=False
            )[0]
            annotated = result.plot() if annotate else None

        polygons = result.masks.xyn if result.masks is not None else []
        detections = []
        for i, box in enumerate(result.boxes):
            x1, y1, x2, y2 = box.xyxyn[0].tolist()
            detection = {
                "label": "person",
                "confidence": round(float(box.conf[0]), 2),
                "bbox": {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
            }
            if i < len(polygons) and len(polygons[i]) >= 3:
                detection["polygon"] = _simplify(polygons[i])
            detections.append(detection)
        return detections, annotated


def _simplify(points) -> list[list[float]]:
    """Réduit un contour à ~MAX_POLYGON_POINTS points en gardant les angles (Douglas-Peucker).

    Un simple échantillonnage un point sur N saute les coins (ex. personne coupée par le bord de l'image)
    et trace des diagonales fausses.
    """
    import cv2
    import numpy as np

    contour = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    epsilon = 0.002  # en coordonnées normalisées : 0,2 % de la taille de l'image
    simplified = contour
    while epsilon < 0.05:
        simplified = cv2.approxPolyDP(contour, epsilon, True)
        if len(simplified) <= MAX_POLYGON_POINTS:
            break
        epsilon *= 1.5
    return [[round(float(x), 4), round(float(y), 4)] for x, y in simplified.reshape(-1, 2)]
