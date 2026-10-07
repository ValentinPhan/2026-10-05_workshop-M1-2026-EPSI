"""Enregistrement vidéo des intrusions : un clip H.264 par intrusion, de la première détection à la fin.

Le service de vision appelle, depuis son thread :
  push(frame, ts)   chaque image traitée (BGR) : garde les `preroll_s` dernières secondes en mémoire et, si un clip est
                    ouvert, l'ajoute au fichier ;
  start(ts)         début d'intrusion : ouvre le clip et y verse d'abord le tampon (on voit donc la personne ARRIVER) ;
  stop(ts, keep)    fin d'intrusion : ferme le clip, ou le supprime (keep=False : fausse alerte / bruit).

Poids et qualité : H.264 (libx264) en CRF 28, preset « veryfast », largeur réduite à 640 px, yuv420p, `faststart`
(lecture immédiate dans le navigateur). Mesuré sur une vraie vidéo 640x480 à 10 img/s : ≈ 28 à 54 Ko/s, soit 1,7 à 3 Mo
par minute, 4 à 8 fois moins que OpenCV seul (mp4v ≈ 107 Ko/s, VP9 ≈ 207 Ko/s) et lisible partout. L'encodage coûte
≈ 2 ms par image (négligeable devant YOLO). Les images sont horodatées (durée réelle respectée même si le débit varie).
Encodeur : PyAV (`pip install av`, FFmpeg embarqué). Sans lui l'enregistrement se désactive avec un avertissement.

Résistance aux plantages : le clip s'écrit en MP4 FRAGMENTÉ (`frag_keyframe+empty_moov`) dans `<nom>.mp4.part`, avec une image clé
toutes les `GOP` images : chaque fragment est autonome et écrit sur disque au fur et à mesure, donc si le serveur plante, tout ce qui
a été filmé jusqu'au dernier fragment (≤ 2 s avant le plantage) reste lisible. À la fermeture normale, le fichier est converti (sans
ré-encodage) en MP4 classique `<nom>.mp4` (index au début : durée, avance rapide) et le `.part` est supprimé. Au redémarrage, `recover()`
repère les `.part` orphelins, les convertit en `<nom>_interrompu.mp4` et les signale (événement `vision.clip` avec `recovered`).

Un clip qui dépasse `max_s` est coupé et le suivant continue (`_p2`, `_p3`...). Les plus anciens sont supprimés au-delà de
`keep_mb` (pas de disque qui se remplit en silence). Tout est exécuté dans le thread de vision : aucun verrou.
"""
import logging
from collections import deque
from datetime import datetime
from fractions import Fraction
from pathlib import Path
from typing import Callable

log = logging.getLogger("sentinel-x.vision")

TIME_BASE = Fraction(1, 1000)  # horodatage des images en millisecondes
GOP = 20  # une image clé (donc un fragment) toutes les 20 images ≈ 2 s : perte maximale en cas de plantage


class ClipRecorder:
    def __init__(
        self, directory: Path | None, on_clip: Callable[[dict], None], *,
        preroll_s: float = 2.0, max_s: float = 180.0, crf: int = 28, max_width: int = 640, keep_mb: float = 1000.0,
    ):
        self._dir = directory
        self._on_clip = on_clip
        self._preroll_s, self._max_s, self._crf, self._max_width, self._keep_mb = preroll_s, max_s, crf, max_width, keep_mb
        self._buffer: deque[tuple[float, object]] = deque()  # (ts, image réduite)
        self._clip: dict | None = None  # clip ouvert : container, stream, chemin, début, nombre d'images...
        self._av = None
        self._cv2 = None
        self._part = 1
        self._base: str | None = None
        self.enabled = directory is not None
        if self.enabled:
            try:
                import av  # noqa: F401 — dépendance optionnelle (requirements-vision.txt)

                self._av = av
            except ImportError:
                self.enabled = False
                log.warning("enregistrement vidéo désactivé : paquet « av » absent (pip install -r requirements-vision.txt)")

    # ---- API appelée par le service de vision ----
    def push(self, frame, ts: float) -> None:
        if not self.enabled:
            return
        try:
            small = self._shrink(frame)
            self._buffer.append((ts, small))
            while self._buffer and ts - self._buffer[0][0] > self._preroll_s:
                self._buffer.popleft()
            if self._clip is not None:
                if ts - self._clip["startTs"] > self._max_s:  # clip trop long : on coupe et on enchaîne
                    self._finish(ts, keep=True)
                    self._open(ts)
                self._write(small, ts)
        except Exception as err:  # noqa: BLE001 — l'enregistrement ne doit jamais casser la détection
            log.warning("enregistrement vidéo interrompu : %s", err)
            self._abort()

    def start(self, ts: float) -> None:
        """Début d'intrusion : ouvre le clip et y verse le tampon (les secondes qui précèdent)."""
        if not self.enabled or self._clip is not None:
            return
        try:
            self._base, self._part = f"intrusion_{datetime.now():%Y%m%d_%H%M%S_%f}"[:-3], 1
            self._open(ts)
            for buffered_ts, image in list(self._buffer):  # inclut l'image courante, déjà poussée
                self._write(image, buffered_ts)
        except Exception as err:  # noqa: BLE001
            log.warning("enregistrement vidéo impossible : %s", err)
            self._abort()

    def stop(self, ts: float, keep: bool = True) -> None:
        """Fin d'intrusion : ferme le clip (ou le supprime si keep=False)."""
        if self._clip is None:
            return
        try:
            self._finish(ts, keep)
        except Exception as err:  # noqa: BLE001
            log.warning("fermeture du clip vidéo : %s", err)
            self._abort()

    # ---- interne ----
    def _shrink(self, frame):
        if self._cv2 is None:
            import cv2

            self._cv2 = cv2
        h, w = frame.shape[:2]
        width = min(w, self._max_width) // 2 * 2  # yuv420p exige des dimensions paires
        height = round(h * width / w) // 2 * 2
        if (width, height) == (w, h):
            return frame.copy()  # le tampon ne doit pas pointer sur une image que l'appelant réutilise
        return self._cv2.resize(frame, (width, height), interpolation=self._cv2.INTER_AREA)

    def _open(self, ts: float) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        name = f"{self._base}.mp4" if self._part == 1 else f"{self._base}_p{self._part}.mp4"
        path = self._dir / f"{name}.part"  # en cours d'écriture ; renommé à la fermeture
        first = self._buffer[0][1] if self._buffer else None
        height, width = first.shape[:2] if first is not None else (480, 640)
        container = self._av.open(
            str(path), "w", format="mp4", options={"movflags": "frag_keyframe+empty_moov+default_base_moof", "flush_packets": "1"}
        )
        stream = container.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        stream.codec_context.time_base = TIME_BASE
        stream.codec_context.gop_size = GOP
        stream.options = {"crf": str(self._crf), "preset": "veryfast"}
        t0 = self._buffer[0][0] if self._buffer and self._part == 1 else ts
        self._clip = {
            "container": container, "stream": stream, "path": path, "final": self._dir / name, "name": name, "startTs": ts, "t0": t0, "lastTs": t0,
            "frames": 0, "size": (width, height),
        }

    def _write(self, image, ts: float) -> None:
        clip = self._clip
        if (image.shape[1], image.shape[0]) != clip["size"]:  # la source a changé de résolution en cours de clip
            image = self._cv2.resize(image, clip["size"], interpolation=self._cv2.INTER_AREA)
        frame = self._av.VideoFrame.from_ndarray(image, format="bgr24")
        pts = max(int((ts - clip["t0"]) * 1000), clip["lastPts"] + 1 if "lastPts" in clip else 0)  # strictement croissant
        frame.pts, frame.time_base = pts, TIME_BASE
        for packet in clip["stream"].encode(frame):
            clip["container"].mux(packet)
        clip["lastPts"], clip["lastTs"] = pts, ts
        clip["frames"] += 1

    def _finish(self, ts: float, keep: bool) -> None:
        clip, self._clip = self._clip, None
        for packet in clip["stream"].encode():  # vide l'encodeur
            clip["container"].mux(packet)
        clip["container"].close()
        part: Path = clip["path"]
        if not keep or clip["frames"] == 0:
            part.unlink(missing_ok=True)
            return
        path = self._seal(part, clip["final"])
        duration = max(clip["lastTs"] - clip["t0"], 0) + 0.1
        info = {
            "name": path.name, "file": str(path), "bytes": path.stat().st_size, "durationS": round(duration, 1),
            "frames": clip["frames"], "fps": round(clip["frames"] / duration, 1), "width": clip["size"][0], "height": clip["size"][1],
            "codec": "h264", "crf": self._crf, "part": self._part, "startedMs": int(clip["t0"] * 1000), "endedMs": int(clip["lastTs"] * 1000),
            "url": f"/api/videos/{path.name}",
        }
        self._part += 1
        self._purge()
        self._on_clip(info)

    def _abort(self) -> None:
        clip, self._clip = self._clip, None
        if clip is not None:
            try:
                clip["container"].close()
            except Exception:  # noqa: BLE001
                pass
            if clip["frames"]:  # on garde ce qui a déjà été filmé (le fragmenté reste lisible)
                clip["path"].replace(clip["final"].with_name(clip["final"].stem + "_interrompu.mp4"))
            else:
                clip["path"].unlink(missing_ok=True)

    def _remux(self, src: Path, dst: Path) -> bool:
        """Copie les paquets H.264 (sans ré-encodage) vers un MP4 classique : index au début, durée connue."""
        try:
            with self._av.open(str(src)) as source, self._av.open(str(dst), "w", format="mp4", options={"movflags": "+faststart"}) as out:
                video = source.streams.video[0]
                target = out.add_stream_from_template(video)
                for packet in source.demux(video):
                    if packet.dts is None:
                        continue
                    packet.stream = target
                    out.mux(packet)
            return True
        except Exception:  # noqa: BLE001 — le fragmenté d'origine reste valable
            dst.unlink(missing_ok=True)
            return False

    def _seal(self, part: Path, final: Path) -> Path:
        """`.part` -> MP4 classique ; si la conversion échoue, le fragmenté est simplement renommé (il est lisible)."""
        if self._remux(part, final):
            part.unlink(missing_ok=True)
        else:
            part.replace(final)
        return final

    def recover(self) -> list[dict]:
        """À appeler au démarrage : les `.part` laissés par un plantage deviennent des clips `_interrompu.mp4`."""
        if not self.enabled or not self._dir.is_dir():
            return []
        recovered = []
        for part in sorted(self._dir.glob("intrusion_*.mp4.part")):
            frames, last, width, height = 0, 0.0, 0, 0
            try:
                with self._av.open(str(part)) as container:
                    video = container.streams.video[0]
                    width, height = video.width, video.height
                    for frame in container.decode(video):  # s'arrête au dernier fragment complet
                        frames, last = frames + 1, float(frame.time or 0)
            except Exception:  # noqa: BLE001 — fragment final tronqué par le plantage : on garde ce qui a été lu
                pass
            if frames == 0:
                part.unlink(missing_ok=True)
                continue
            final = part.with_name(part.name.removesuffix(".mp4.part") + "_interrompu.mp4")
            path = self._seal(part, final)
            duration = last + 0.1
            recovered.append({
                "name": path.name, "file": str(path), "bytes": path.stat().st_size, "durationS": round(duration, 1), "frames": frames,
                "fps": round(frames / duration, 1), "width": width, "height": height, "codec": "h264", "crf": self._crf, "part": None,
                "recovered": True, "url": f"/api/videos/{path.name}",
            })
        return recovered

    def _purge(self) -> None:
        """Supprime les plus anciens clips tant que le dossier dépasse `keep_mb`."""
        files = sorted(self._dir.glob("intrusion_*.mp4"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        while len(files) > 1 and total > self._keep_mb * 1024 * 1024:  # le clip qui vient d'être écrit est toujours gardé
            oldest = files.pop(0)
            total -= oldest.stat().st_size
            oldest.unlink(missing_ok=True)
            log.info("clip vidéo le plus ancien supprimé (quota %s Mo) : %s", self._keep_mb, oldest.name)
