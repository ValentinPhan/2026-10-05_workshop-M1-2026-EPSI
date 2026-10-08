#!/usr/bin/env python3
"""Serveur de flux vidéo MJPEG pour la caméra du Raspberry Pi (bibliothèque standard uniquement).

  http://<ip du Pi>:8080/stream.mjpg   flux MJPEG (affichable tel quel dans une balise <img>, ouvrable par OpenCV / YOLO)
  http://<ip du Pi>:8080/snapshot.jpg  dernière image
  http://<ip du Pi>:8080/health        état (JSON)

La caméra n'est démarrée que lorsqu'un client regarde le flux, et arrêtée 5 s après le départ du dernier :
le Pi reste libre quand personne ne regarde. Aucun traitement d'image ici, le Pi ne fait que diffuser.

Encodeur (détecté automatiquement) : rpicam-vid (Raspberry Pi OS récent), libcamera-vid, ou raspivid (ancien système).
--cmd (ou la variable SENTINEL_CAMERA_CMD) remplace l'encodeur par une commande qui écrit du MJPEG sur stdout,
par exemple une webcam USB :  --cmd "ffmpeg -loglevel error -f v4l2 -i /dev/video0 -f mjpeg -q:v 5 -"

Usage : python3 camera_stream.py [--port 8080] [--width 640] [--height 480] [--fps 15]
"""
import argparse
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOUNDARY = b"sentinelframe"
IDLE_STOP_S = 5.0
FRAME_END_START = b"\xff\xd9\xff\xd8"  # fin d'une image JPEG immédiatement suivie du début de la suivante


def log(msg):
    print(f"[camera] {msg}", file=sys.stderr, flush=True)


def encoder_command(args):
    if args.cmd:
        return shlex.split(args.cmd)
    size = ["--width", str(args.width), "--height", str(args.height)]
    for tool in ("rpicam-vid", "libcamera-vid"):
        if shutil.which(tool):
            return [tool, "-t", "0", "--nopreview", "--codec", "mjpeg", *size, "--framerate", str(args.fps),
                    "--quality", str(args.quality), "--inline", "-o", "-"]
    if shutil.which("raspivid"):  # ancien système (pile caméra héritée)
        return ["raspivid", "-t", "0", "-n", "-cd", "MJPEG", "-w", str(args.width), "-h", str(args.height),
                "-fps", str(args.fps), "-o", "-"]
    return None


class Hub:
    """Dernière image + réveil des clients ; démarre / arrête l'encodeur selon l'audience."""

    def __init__(self, args):
        self.args = args
        self.cond = threading.Condition()
        self.frame = None
        self.seq = 0
        self.clients = 0
        self.proc = None
        self.error = None
        self.last_client_at = time.monotonic()
        threading.Thread(target=self._supervise, daemon=True).start()

    # -- appelés par les gestionnaires HTTP
    def join(self):
        with self.cond:
            self.clients += 1

    def leave(self):
        with self.cond:
            self.clients -= 1
            self.last_client_at = time.monotonic()

    def wait_frame(self, last_seq, timeout=5.0):
        with self.cond:
            self.cond.wait_for(lambda: self.seq != last_seq, timeout)
            return self.seq, self.frame

    # -- cycle de vie de l'encodeur
    def _supervise(self):
        while True:
            time.sleep(0.25)
            with self.cond:
                wanted = self.clients > 0 or time.monotonic() - self.last_client_at < IDLE_STOP_S
                running = self.proc is not None and self.proc.poll() is None
            if wanted and not running and self.clients > 0:
                self._start()
            elif not wanted and running:
                self._stop()
            elif self.proc is not None and not running:
                self.proc = None  # l'encodeur s'est arrêté seul : on le relancera si un client attend

    def _start(self):
        cmd = encoder_command(self.args)
        if not cmd:
            self.error = "aucun encodeur trouvé (rpicam-vid, libcamera-vid, raspivid) : installer rpicam-apps ou utiliser --cmd"
            log(self.error)
            time.sleep(2)
            return
        log("démarrage : " + " ".join(cmd))
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=sys.stderr, bufsize=0)
        except OSError as err:
            self.error = str(err)
            log(f"échec du démarrage : {err}")
            time.sleep(2)
            return
        self.error = None
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _stop(self):
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            log("plus de spectateur : caméra arrêtée")
            proc.terminate()
            try:
                proc.wait(2)
            except subprocess.TimeoutExpired:
                proc.kill()
        with self.cond:
            self.frame = None

    def _read(self, proc):
        """Découpe le flux MJPEG continu en images JPEG."""
        buf = b""
        started = False
        while True:
            chunk = proc.stdout.read(65536)
            if not chunk:
                break
            buf += chunk
            if not started:
                i = buf.find(b"\xff\xd8")
                if i < 0:
                    buf = buf[-1:]
                    continue
                buf, started = buf[i:], True
            while True:
                i = buf.find(FRAME_END_START)
                if i < 0:
                    break
                frame, buf = buf[: i + 2], buf[i + 2 :]
                with self.cond:
                    self.frame = frame
                    self.seq += 1
                    self.cond.notify_all()
            if len(buf) > 8_000_000:  # flux corrompu : on repart de zéro
                buf, started = b"", False
        log(f"encodeur terminé (code {proc.poll()})")


class Handler(BaseHTTPRequestHandler):
    hub = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *a):  # silence : le journal est réservé aux événements utiles
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        hub = self.hub
        if path == "/health":
            ok = hub.error is None
            self._send(200 if ok else 503, "application/json",
                       ('{"ok":%s,"clients":%d,"error":%s}' % ("true" if ok else "false", hub.clients,
                                                              '"%s"' % hub.error.replace('"', "'") if hub.error else "null")).encode())
        elif path == "/snapshot.jpg":
            hub.join()
            try:
                seq, frame = hub.wait_frame(-1, timeout=8.0)
            finally:
                hub.leave()
            if frame:
                self._send(200, "image/jpeg", frame)
            else:
                self._send(503, "text/plain", (hub.error or "pas d'image").encode())
        elif path in ("/stream.mjpg", "/"):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=" + BOUNDARY.decode())
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Connection", "close")
            self.end_headers()
            hub.join()
            seq = -1
            try:
                while True:
                    seq, frame = hub.wait_frame(seq)
                    if not frame:
                        if hub.error:
                            break
                        continue
                    self.wfile.write(b"--" + BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                     + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                pass
            finally:
                hub.leave()
        else:
            self._send(404, "text/plain", b"not found")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--quality", type=int, default=60, help="qualité JPEG 1-100 (rpicam-vid)")
    ap.add_argument("--cmd", default=os.environ.get("SENTINEL_CAMERA_CMD"), help="commande d'encodage MJPEG vers stdout")
    ap.add_argument("--parent-pid", type=int, default=0, help="quitte quand ce processus disparaît (lancé par l'agent)")
    args = ap.parse_args()

    Handler.hub = Hub(args)
    server = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    server.daemon_threads = True
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))

    if args.parent_pid:
        def watch():
            while True:
                time.sleep(1)
                if os.getppid() != args.parent_pid:
                    Handler.hub._stop()
                    os._exit(0)
        threading.Thread(target=watch, daemon=True).start()

    log(f"flux sur http://0.0.0.0:{args.port}/stream.mjpg ({args.width}x{args.height} @ {args.fps} fps)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        Handler.hub._stop()


if __name__ == "__main__":
    main()
