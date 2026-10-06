from ultralytics import YOLO
import cv2
from datetime import datetime
import os
import time
import json

# =========================
# CONFIGURATION
# =========================

model = YOLO("yolov8n.pt")

CAMERA = 0
CONFIDENCE_THRESHOLD = 0.5
INTRUSION_TIMEOUT = 3

os.makedirs("captures", exist_ok=True)

# =========================
# CAMERA
# =========================

camera = cv2.VideoCapture(CAMERA)

if not camera.isOpened():
    print("❌ Impossible d'ouvrir la webcam")
    exit()

intrusion_active = False
last_detection_time = 0

# =========================
# BOUCLE PRINCIPALE
# =========================

while True:

    ret, frame = camera.read()

    if not ret:
        print("❌ Erreur webcam")
        break

    # YOLO détecte uniquement les personnes
    results = model(
        frame,
        classes=[0],
        conf=CONFIDENCE_THRESHOLD,
        verbose=False
    )

    result = results[0]

    # Image avec les bounding boxes
    annotated_frame = result.plot()

    # =========================
    # PERSONNE DETECTEE
    # =========================

    if len(result.boxes) > 0:

        confidence = float(result.boxes.conf[0])

        last_detection_time = time.time()

        # Nouvelle intrusion
        if not intrusion_active:

            intrusion_active = True

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            filename = f"captures/intrusion_{timestamp}.jpg"

            # Sauvegarde de la photo
            cv2.imwrite(filename, frame)

            print()
            print("🚨 INTRUSION DETECTED")
            print(f"📊 Confidence : {confidence:.2f}")
            print(f"📸 Photo : {filename}")

            # =========================
            # EVENEMENT SENTINEL-X
            # =========================

            event = {
                "ts": datetime.now().isoformat(),
                "event": "intrusion",
                "confidence": round(confidence, 2),
                "zone": "camera_1",
                "snapshot": filename
            }

            print("📡 EVENEMENT :")
            print(json.dumps(event, indent=2))

        # Affichage sur la vidéo
        cv2.putText(
            annotated_frame,
            "INTRUSION DETECTED",
            (30, 50),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 0, 255),
            3
        )

    # =========================
    # FIN DE L'INTRUSION
    # =========================

    else:

        if intrusion_active:

            if time.time() - last_detection_time > INTRUSION_TIMEOUT:

                intrusion_active = False

                print("✅ Intrusion terminée")

    # =========================
    # AFFICHAGE
    # =========================

    cv2.imshow(
        "SENTINEL-X - Intrusion Detection",
        annotated_frame
    )

    # Q pour quitter
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break


# =========================
# FERMETURE
# =========================

camera.release()
cv2.destroyAllWindows()