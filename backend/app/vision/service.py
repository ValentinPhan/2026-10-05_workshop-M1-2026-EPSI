"""Service de vision : capture caméra + YOLO dans un thread dédié.

Il tourne à son propre rythme (~10 images/s), indépendamment du tick des capteurs (1/s), et publie
vers le hub, depuis son thread :
  - on_frame(jpeg, meta) image + ses résultats YOLO (positions des carrés, silhouettes), diffusées en
                         WebSocket sur /ws/video ; le dashboard dessine lui-même les carrés rouges
  - on_intrusion(event)  début d'une intrusion, ou personne de plus dans une intrusion en cours
                         (`event["event"]` = "intrusion" | "new_person"), avec la photo enregistrée dans CAPTURES_DIR
  - on_intrusion_end()   fin d'une intrusion (plus de détection depuis `intrusion_timeout_s`)
  - on_status(status)    changement d'état du service (chargement, en marche, attente, erreur...)

Deux sources d'images, commutables à chaud :
  - la caméra du backend (VISION_SOURCE : "0" = webcam du PC, URL du flux du Pi, fichier vidéo) ;
  - des images POUSSÉES sur /ws/camera (JPEG binaire) -> push_frame() : par le navigateur (webcam du PC
    qui ouvre le dashboard) ou par le Raspberry (raspberry-pi/camera_push.py). Utile quand la caméra
    n'est pas sur la machine du backend. VISION_SOURCE=browser | push démarre directement dans ce mode.
    En passant en mode navigateur, le backend relâche sa caméra (une webcam ne peut être ouverte que
    par un programme à la fois).

La logique d'intrusion vient du script de l'équipe IA (ml/vision/yolo_intrusion.py).
"""
import base64
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from ..config import VisionConfig
from .detector import YoloDetector

log = logging.getLogger("sentinel-x.vision")

BROWSER = "browser"  # images envoyées par la webcam du navigateur (commutable à chaud depuis le dashboard)
PUSH = "push"  # images envoyées par un client externe, ex. le Raspberry (raspberry-pi/camera_push.py)
RETRY_S = 2.0  # délai avant de rouvrir une caméra injoignable
MAX_WIDTH = 640  # les images envoyées au dashboard sont réduites à cette largeur
PUSH_IDLE_S = 3.0  # sans image du navigateur pendant ce délai : on repasse en "attente"
PENDING_MIN_HITS = 3  # images minimum pendant la latence pour confirmer une détection (sinon : bruit)


class _FpsMeter:
    """Images traitées par seconde, mesurées sur des fenêtres de 2 s."""

    def __init__(self) -> None:
        self._frames, self._start = 0, time.time()

    def tick(self) -> float | None:
        self._frames += 1
        elapsed = time.time() - self._start
        if elapsed < 2:
            return None
        fps = round(self._frames / elapsed, 1)
        self._frames, self._start = 0, time.time()
        return fps


class VisionService:
    def __init__(self, cfg: VisionConfig, models_dir: Path, captures_dir: Path):
        self._cfg = cfg
        self._models_dir = models_dir
        self._captures_dir = captures_dir
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # VISION_SOURCE=browser|push : pas de caméra côté backend, les images arrivent sur /ws/camera
        self._configured_push = cfg.source in (BROWSER, PUSH)
        self._push_mode = self._configured_push
        self._cond = threading.Condition()  # protège _pushed et réveille le thread à l'arrivée d'une image
        self._pushed: bytes | None = None
        self._status = {
            "enabled": True,
            "state": "stopped",
            "source": cfg.source,
            "model": cfg.model,
            "fps": 0.0,
            "error": None,
        }
        self._latest = {"ts": 0.0, "detections": []}
        self._detector: YoloDetector | None = None  # chargé par le thread de vision
        self._intrusion_active = False
        self._last_seen = 0.0
        self._alerted = False  # une première photo / alerte a été faite dans l'intrusion en cours
        self._level = 0  # nombre de personnes déjà photographiées dans l'intrusion en cours
        self._level_seen = 0.0  # dernière fois où on a vu au moins `_level` personnes
        self._pending_since: float | None = None  # début de la latence en cours (nombre de personnes en hausse)
        self._pending_hits = 0  # images vues pendant cette latence
        self._best: tuple | None = None  # (image, détections) montrant le plus de personnes pendant la latence
        self._cb: dict = {}

    # ---- API publique (appelée depuis le thread de l'API) ----
    def start(self, on_frame, on_intrusion, on_intrusion_end, on_status) -> None:
        self._cb = {"frame": on_frame, "intrusion": on_intrusion, "intrusion_end": on_intrusion_end, "status": on_status}
        self._thread = threading.Thread(target=self._run, name="vision", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        if self._thread:
            self._thread.join(timeout=5)

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def latest_detections(self, max_age_s: float = 2.0) -> list[dict]:
        """Dernières détections (sans les silhouettes, inutiles pour l'analyse) ; liste vide si le service ne
        produit plus rien (caméra coupée, modèle en erreur)."""
        with self._lock:
            fresh = time.time() - self._latest["ts"] <= max_age_s
            detections = list(self._latest["detections"]) if fresh else []
        return [{k: v for k, v in d.items() if k != "polygon"} for d in detections]

    def analyze_image(self, data: bytes, annotate: bool = False) -> dict:
        """YOLO sur une image fournie en entrée (JPEG/PNG...). Lève ValueError si elle est illisible.

        Retourne {ts, width, height, detections, annotated} ; `annotated` = image avec les dessins de YOLO
        (JPEG en base64) si demandée. Indépendant du flux en cours : ne touche ni aux détections courantes
        ni aux intrusions.
        """
        import cv2  # imports tardifs : dépendances optionnelles
        import numpy as np

        if self._detector is None:
            raise ValueError("modèle YOLO pas encore chargé")
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("image illisible (JPEG ou PNG attendu)")
        detections, annotated = self._detector.detect(frame, annotate=annotate)
        encoded = None
        if annotated is not None:
            ok, jpeg = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, self._cfg.jpeg_quality])
            encoded = base64.b64encode(jpeg.tobytes()).decode() if ok else None
        height, width = frame.shape[:2]
        return {"ts": int(time.time() * 1000), "width": width, "height": height, "detections": detections, "annotated": encoded}

    def set_push_mode(self, enabled: bool) -> dict:
        """Source des images : le navigateur (True) ou la caméra du backend (False).

        Avec VISION_SOURCE=browser|push il n'y a pas de caméra côté backend : le mode reste « images poussées ».
        """
        enabled = enabled or self._configured_push
        with self._cond:
            self._push_mode = enabled
            self._pushed = None
            self._cond.notify_all()  # réveille le thread, qui change de source
        self._set_status(source=self._cfg.source if (self._configured_push or not enabled) else BROWSER)
        return self.status()

    def push_frame(self, jpeg: bytes) -> bool:
        """Image JPEG envoyée par le navigateur. Seule la plus récente est gardée (pas de file d'attente)."""
        with self._cond:
            if not self._push_mode:
                return False
            self._pushed = jpeg
            self._cond.notify()
        return True

    # ---- thread de vision ----
    def _set_status(self, **changes) -> None:
        with self._lock:
            before = dict(self._status)
            self._status.update(changes)
            after = dict(self._status)
        # le fps bouge en permanence : on ne notifie que les changements d'état ou de gros écarts
        changed = {k: v for k, v in after.items() if k != "fps"} != {k: v for k, v in before.items() if k != "fps"}
        if (changed or abs(after["fps"] - before["fps"]) >= 2) and "status" in self._cb:
            self._cb["status"](after)

    def _run(self) -> None:
        import cv2  # imports tardifs : dépendances optionnelles (requirements-vision.txt)
        import numpy as np

        self._set_status(state="loading", error=None)
        try:
            detector = self._detector = YoloDetector(
                self._models_dir / self._cfg.model, self._cfg.confidence, self._cfg.imgsz
            )
        except Exception as err:  # noqa: BLE001 — message affiché dans le dashboard
            log.error("modèle YOLO indisponible : %s", err)
            self._set_status(state="error", error=f"modèle YOLO indisponible : {err}")
            return

        while not self._stop.is_set():
            self._end_intrusion()  # changement de source : une intrusion en cours n'est plus suivie
            if self._push_mode:
                self._run_browser(cv2, np, detector)
            else:
                self._run_device(cv2, detector)

    def _run_device(self, cv2, detector) -> None:
        """Caméra du backend (webcam, URL, fichier). Rend la main si on passe en mode navigateur."""
        source = int(self._cfg.source) if self._cfg.source.isdigit() else self._cfg.source
        is_file = isinstance(source, str) and os.path.isfile(source)
        min_period = 1 / self._cfg.max_fps if self._cfg.max_fps > 0 else 0

        capture = cv2.VideoCapture(source)
        if not capture.isOpened():
            self._set_status(state="error", error=f"caméra injoignable : {self._cfg.source}", fps=0.0)
            self._stop.wait(RETRY_S)
            return
        self._set_status(state="running", error=None)

        meter = _FpsMeter()
        while not self._stop.is_set() and not self._push_mode:
            started = time.time()
            ok, frame = capture.read()
            if not ok and is_file:  # vidéo de test : on la rejoue en boucle
                capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = capture.read()
            if not ok:
                self._set_status(state="error", error="flux caméra interrompu", fps=0.0)
                break

            self._process(cv2, detector, frame)
            fps = meter.tick()
            if fps is not None:
                self._set_status(fps=fps)
            self._stop.wait(max(0.0, min_period - (time.time() - started)))

        capture.release()  # libère la webcam (le navigateur peut alors l'ouvrir)
        if not self._stop.is_set() and not self._push_mode:
            self._stop.wait(RETRY_S)

    def _run_browser(self, cv2, np, detector) -> None:
        """Images envoyées par le navigateur. Rend la main si on repasse sur la caméra du backend."""
        self._set_status(state="waiting", error=None, fps=0.0)
        meter = _FpsMeter()
        last_frame_at = 0.0

        while not self._stop.is_set() and self._push_mode:
            with self._cond:
                if self._pushed is None:
                    self._cond.wait(0.5)
                jpeg, self._pushed = self._pushed, None

            if jpeg is None:
                if time.time() - last_frame_at > PUSH_IDLE_S:
                    self._set_status(state="waiting", fps=0.0)
                continue
            frame = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:  # image corrompue : on l'ignore
                continue

            last_frame_at = time.time()
            self._set_status(state="running", error=None)
            self._process(cv2, detector, frame)
            fps = meter.tick()
            if fps is not None:
                self._set_status(fps=fps)

    def _process(self, cv2, detector, frame) -> None:
        """Une image : YOLO, mise à jour des détections et de l'intrusion, envoi de l'image et de ses résultats."""
        detections, annotated = detector.detect(frame, annotate=self._cfg.annotate)
        with self._lock:
            self._latest = {"ts": time.time(), "detections": detections}
        self._update_intrusion(detections, frame, cv2)

        # image brute (le dashboard dessine les carrés) ou image déjà annotée par YOLO (VISION_ANNOTATE=1)
        image = annotated if annotated is not None else frame
        if image.shape[1] > MAX_WIDTH:  # positions normalisées : la réduction ne les décale pas
            scale = MAX_WIDTH / image.shape[1]
            image = cv2.resize(image, (MAX_WIDTH, int(image.shape[0] * scale)))
        encoded, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, self._cfg.jpeg_quality])
        if encoded:
            meta = {
                "ts": int(time.time() * 1000),
                "width": image.shape[1],
                "height": image.shape[0],
                "annotated": annotated is not None,  # True : carrés déjà dessinés dans l'image, ne pas les redessiner
                "personCount": len(detections),  # YOLO ne cherche que des personnes (classe 0)
                "detections": detections,
            }
            self._cb["frame"](jpeg.tobytes(), meta)

    def _update_intrusion(self, detections: list[dict], frame, cv2) -> None:
        """Photo au début d'une intrusion, puis quand le nombre de personnes augmente, avec une latence.

        YOLO hésite d'une image à l'autre (2, 3, 2, 3...). Quand le nombre dépasse celui déjà photographié
        (`_level`), on n'agit pas tout de suite : on attend `capture_settle_s` en retenant l'image qui montre
        le plus de personnes, puis on prend UNE photo à ce niveau. Un clignotement entre les mêmes nombres
        donne donc une seule photo ; une photo de plus n'est prise que si un nouveau palier est atteint
        (3-4 après 2-3). Une détection de moins de PENDING_MIN_HITS images est du bruit : pas de photo.
        Pas de suivi d'identité : « nouvelle personne » = plus de personnes que le niveau déjà photographié.
        """
        now = time.time()
        count = len(detections)
        if count:
            self._last_seen = now
            self._intrusion_active = True
            if count >= self._level:
                self._level_seen = now
            elif now - self._level_seen > self._cfg.intrusion_timeout_s:
                self._level = count  # les personnes en trop sont réellement parties : un retour compte comme nouveau
            if count > self._level:
                if self._pending_since is None:
                    self._pending_since, self._pending_hits, self._best = now, 0, None
                self._pending_hits += 1
                if self._best is None or count > len(self._best[1]):
                    self._best = (frame.copy(), detections)

        if self._pending_since is not None and now - self._pending_since >= self._cfg.capture_settle_s:
            self._confirm_pending(now, cv2)
        if not count and self._intrusion_active and now - self._last_seen > self._cfg.intrusion_timeout_s:
            self._end_intrusion()

    def _confirm_pending(self, now: float, cv2) -> None:
        """Fin de la latence : une photo au niveau maximal vu (sauf si ce n'était que du bruit)."""
        frame, detections = self._best
        hits = self._pending_hits
        self._pending_since = self._best = None
        if hits < PENDING_MIN_HITS:
            return
        kind = "new_person" if self._alerted else "intrusion"
        self._alerted = True
        self._level = len(detections)
        self._capture(frame, detections, kind, now, cv2)

    def _capture(self, frame, detections: list[dict], kind: str, now: float, cv2) -> None:
        """Enregistre l'image brute dans CAPTURES_DIR et prévient le hub (alerte avec la photo)."""
        self._captures_dir.mkdir(parents=True, exist_ok=True)
        count = len(detections)
        name = f"intrusion_{datetime.now():%Y%m%d_%H%M%S_%f}"[:-3] + f"_{count}p.jpg"  # millisecondes : pas de collision
        (self._captures_dir / name).write_bytes(self._compress_capture(frame, cv2))
        self._cb["intrusion"](
            {
                "ts": int(now * 1000),
                "event": kind,  # "intrusion" (début) ou "new_person" (une personne de plus)
                "confidence": max(d["confidence"] for d in detections),
                "personCount": count,
                "zone": self._cfg.zone,
                "snapshot": f"/api/captures/{name}",
            }
        )

    def _compress_capture(self, frame, cv2) -> bytes:
        """Photo légère : réduite à `capture_max_width`, JPEG de qualité réduite, tables optimisées, progressif."""
        if frame.shape[1] > self._cfg.capture_max_width:
            scale = self._cfg.capture_max_width / frame.shape[1]
            frame = cv2.resize(frame, (self._cfg.capture_max_width, round(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
        ok, jpeg = cv2.imencode(
            ".jpg",
            frame,
            [
                cv2.IMWRITE_JPEG_QUALITY, self._cfg.capture_jpeg_quality,
                cv2.IMWRITE_JPEG_OPTIMIZE, 1,  # tables de Huffman optimisées : fichier plus petit, même image
                cv2.IMWRITE_JPEG_PROGRESSIVE, 1,
            ],
        )
        return jpeg.tobytes() if ok else b""

    def _end_intrusion(self) -> None:
        was_alerted = self._alerted
        self._intrusion_active = self._alerted = False
        self._level = 0
        self._pending_since = self._best = None
        if was_alerted:  # pas d'alerte levée (bruit) : rien à clore
            self._cb["intrusion_end"]()
