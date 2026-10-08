#!/usr/bin/env python3
"""Envoie la caméra du Raspberry au backend : images JPEG en WebSocket (binaire) vers /ws/camera.

Le backend (lancé avec VISION_SOURCE=push) les passe à YOLO ; le dashboard affiche le résultat.
Le Pi ne fait aucun calcul d'IA : il capture, compresse en JPEG et envoie.

Installation sur le Pi (Raspberry Pi OS Bookworm) :
    sudo apt install python3-picamera2        # souvent déjà présent
    pip install websockets                    # >= 12
    # webcam USB à la place de la caméra CSI :  sudo apt install python3-opencv

Le backend n'accepte le Pi que s'il présente le jeton DEVICE_TOKEN (défini dans backend/.env) : --token.

Usage :
    python3 camera_push.py --url ws://192.168.137.1:4000/ws/camera --token <DEVICE_TOKEN>
    python3 camera_push.py --url ws://<ip-du-pc>:4000/ws/camera --token ... --fps 8 --size 640x480 --quality 70
    python3 camera_push.py --url ... --source 0            # webcam USB (OpenCV, index 0)
    python3 camera_push.py --url ... --source video.avi    # fichier vidéo rejoué en boucle (test sans caméra)

Pas de file d'attente : on capture juste avant d'envoyer, donc si le réseau ou YOLO ralentit, le Pi envoie
simplement moins d'images au lieu d'en accumuler (la latence reste basse). Reconnexion automatique.
"""
import argparse
import io
import sys
import time
from urllib.parse import quote

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect


class PiCamera:
    """Caméra CSI via picamera2 : JPEG produit directement par la bibliothèque."""

    def __init__(self, size, quality):
        from picamera2 import Picamera2  # import tardif : absent hors Raspberry

        self._cam = Picamera2()
        self._cam.configure(self._cam.create_video_configuration(main={"size": size}))
        self._cam.options["quality"] = quality
        self._cam.start()

    def read_jpeg(self) -> bytes:
        buf = io.BytesIO()
        self._cam.capture_file(buf, format="jpeg")
        return buf.getvalue()

    def close(self):
        self._cam.stop()


class OpenCvCamera:
    """Webcam USB (index) ou fichier vidéo (rejoué en boucle) via OpenCV."""

    def __init__(self, source, size, quality):
        import cv2  # import tardif

        self._cv2 = cv2
        self._cap = cv2.VideoCapture(int(source) if str(source).isdigit() else source)
        if not self._cap.isOpened():
            raise OSError(f"source vidéo introuvable : {source}")
        self._is_file = not str(source).isdigit()
        self._size = size
        self._params = [cv2.IMWRITE_JPEG_QUALITY, quality]
        if not self._is_file:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])

    def read_jpeg(self) -> bytes:
        ok, frame = self._cap.read()
        if not ok and self._is_file:
            self._cap.set(self._cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._cap.read()
        if not ok:
            raise OSError("plus d'image de la caméra")
        if frame.shape[1] != self._size[0]:
            frame = self._cv2.resize(frame, self._size)
        ok, jpeg = self._cv2.imencode(".jpg", frame, self._params)
        return jpeg.tobytes()

    def close(self):
        self._cap.release()


def open_camera(args, size):
    if args.source == "picamera":
        return PiCamera(size, args.quality)
    return OpenCvCamera(args.source, size, args.quality)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="ws://<ip-du-pc>:4000/ws/camera")
    ap.add_argument("--token", default="", help="jeton DEVICE_TOKEN du backend (obligatoire : sans lui /ws/camera refuse le Pi)")
    ap.add_argument("--source", default="picamera", help="picamera (défaut) | index webcam USB | fichier vidéo")
    ap.add_argument("--fps", type=float, default=10, help="images par seconde maximum (défaut 10)")
    ap.add_argument("--size", default="640x480", help="LARGEURxHAUTEUR (défaut 640x480)")
    ap.add_argument("--quality", type=int, default=70, help="qualité JPEG 1-100 (défaut 70, ~15 Ko par image)")
    args = ap.parse_args()
    size = tuple(int(v) for v in args.size.lower().split("x"))
    period = 1 / args.fps

    url = args.url + (("&" if "?" in args.url else "?") + f"token={quote(args.token)}" if args.token else "")
    camera = open_camera(args, size)
    print(f"caméra prête ({args.source}, {args.size}, {args.fps:g} img/s) -> {args.url}")
    retry = 0
    try:
        while True:
            try:
                with connect(url, max_size=None, open_timeout=5) as ws:
                    print("connecté au backend")
                    retry, sent, window = 0, 0, time.monotonic()
                    while True:
                        started = time.monotonic()
                        ws.send(camera.read_jpeg())  # capture juste avant l'envoi : pas de retard cumulé
                        sent += 1
                        if time.monotonic() - window >= 5:
                            print(f"{sent / (time.monotonic() - window):.1f} img/s envoyées")
                            sent, window = 0, time.monotonic()
                        time.sleep(max(0.0, period - (time.monotonic() - started)))
            except (OSError, WebSocketException) as err:
                delay = min(5, 0.5 * 2**retry)
                retry += 1
                print(f"liaison perdue ({err}) ; nouvel essai dans {delay:g} s", file=sys.stderr)
                time.sleep(delay)
    except KeyboardInterrupt:
        pass
    finally:
        camera.close()


if __name__ == "__main__":
    main()
