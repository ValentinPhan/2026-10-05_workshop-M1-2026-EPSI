"""Configuration centrale, surchargeable par variables d'environnement."""
import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODELS_DIR = BACKEND_DIR / "models"  # poids des modèles (YOLO, ...)
CAPTURES_DIR = Path(os.environ.get("CAPTURES_DIR", BACKEND_DIR / "data" / "captures"))  # photos d'intrusion


def _num(name: str, default: float) -> float:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return default


@dataclass(frozen=True)
class Thresholds:
    """Seuils du moteur d'alertes (indépendants du provider)."""

    proximity_cm: float = 80
    heat_max_c: float = 45
    person_confidence: float = 0.6
    env_anomaly_score: float = 70  # score d'anomalie DHT22 (0..100) au-delà duquel on alerte


@dataclass(frozen=True)
class SshConfig:
    host: str = os.environ.get("SSH_HOST", "192.168.50.10")
    port: int = int(_num("SSH_PORT", 22))
    username: str = os.environ.get("SSH_USER", "pi")
    private_key_path: str = os.environ.get("SSH_KEY", "")


@dataclass(frozen=True)
class VisionConfig:
    """Vision temps réel (YOLO), active uniquement avec ANALYZER=local."""

    source: str = os.environ.get("VISION_SOURCE", "0")  # "0" = webcam du PC, sinon URL du flux du Pi ou fichier vidéo
    model: str = os.environ.get("YOLO_MODEL", "yolov8n.pt")  # fichier dans backend/models/
    confidence: float = _num("YOLO_CONF", 0.5)
    imgsz: int = int(_num("YOLO_IMGSZ", 640))
    max_fps: float = _num("VISION_FPS", 10)  # plafond d'images traitées / s (borne la charge CPU)
    jpeg_quality: int = int(_num("VISION_JPEG_QUALITY", 70))
    # False (défaut) : le backend envoie l'image brute + les positions, le dashboard dessine les carrés rouges.
    # True : YOLO incruste lui-même ses dessins dans l'image envoyée.
    annotate: bool = os.environ.get("VISION_ANNOTATE", "0").lower() in ("1", "true", "yes")
    intrusion_timeout_s: float = _num("INTRUSION_TIMEOUT_S", 3)  # sans détection pendant ce délai = intrusion terminée
    # Latence avant de photographier : quand le nombre de personnes monte, on attend ce délai (en gardant le
    # maximum vu) pour ne prendre qu'une photo malgré les hésitations de YOLO (2-3-2-3...). Plus grand = moins de photos.
    capture_settle_s: float = _num("CAPTURE_SETTLE_S", 1.5)
    # Photos d'intrusion : réduites et compressées pour rester légères (une photo = un justificatif, pas une œuvre)
    capture_max_width: int = int(_num("CAPTURE_MAX_WIDTH", 640))
    capture_jpeg_quality: int = int(_num("CAPTURE_JPEG_QUALITY", 70))
    zone: str = os.environ.get("VISION_ZONE", "camera_1")


@dataclass(frozen=True)
class Config:
    # "mock" (données fictives) ou "ssh" (Raspberry Pi réel)
    provider: str = os.environ.get("PROVIDER", "mock")
    # Analyse : "mock" (heuristique factice) ou "local" (YOLO sur la caméra + fusion des capteurs, voir app/vision/)
    analyzer: str = os.environ.get("ANALYZER", "mock")
    tick_ms: int = int(_num("TICK_MS", 1000))
    history_size: int = int(_num("HISTORY_SIZE", 120))
    alerts_size: int = int(_num("ALERTS_SIZE", 50))
    ssh: SshConfig = field(default_factory=SshConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    thresholds: Thresholds = field(default_factory=Thresholds)


config = Config()
