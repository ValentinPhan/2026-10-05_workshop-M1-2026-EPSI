"""
Sentinel-X - Brique vision - Etape 1 : test webcam + YOLOv8n
Lance la webcam, detecte les personnes, affiche les FPS.
Appuie sur la touche Q pour quitter.
"""
import time
from pathlib import Path

import cv2
from ultralytics import YOLO

# --- Reglages que tu pourras modifier ---
CAMERA = 0          # 0 = webcam par defaut. Essaie 1 si ca ne marche pas.
SEUIL_CONFIANCE = 0.5   # 0.5 = on garde les detections sures a 50 % ou plus
TAILLE_IMAGE = 320      # plus petit = plus rapide (320, 416, 640)

# Memes poids que le backend : une seule copie dans backend/models/
modele = YOLO(str(Path(__file__).resolve().parents[2] / "backend" / "models" / "yolov8n.pt"))

camera = cv2.VideoCapture(CAMERA)
if not camera.isOpened():
    print("Impossible d'ouvrir la webcam. Essaie CAMERA = 1.")
    raise SystemExit

temps_precedent = time.time()

while True:
    ok, image = camera.read()
    if not ok:
        print("Plus d'image de la webcam.")
        break

    # classes=[0] : on ne garde que la classe "personne"
    resultat = modele(
        image,
        imgsz=TAILLE_IMAGE,
        conf=SEUIL_CONFIANCE,
        classes=[0],
        verbose=False,
    )[0]

    nb_personnes = len(resultat.boxes)
    image_annotee = resultat.plot()  # dessine les cadres + la confiance

    # Calcul des FPS (images par seconde)
    maintenant = time.time()
    fps = 1 / (maintenant - temps_precedent)
    temps_precedent = maintenant

    cv2.putText(image_annotee, f"FPS: {fps:.1f}", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
    cv2.putText(image_annotee, f"Personnes: {nb_personnes}", (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

    cv2.imshow("Sentinel-X - Vision", image_annotee)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()