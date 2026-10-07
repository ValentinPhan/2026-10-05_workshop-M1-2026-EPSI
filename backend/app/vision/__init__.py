from ..config import CAPTURES_DIR, MODELS_DIR, VIDEOS_DIR, Config
from .service import VisionService


def create_vision(config: Config) -> VisionService | None:
    """Le service de vision (caméra + YOLO) n'existe qu'avec ANALYZER=local."""
    if config.analyzer != "local":
        return None
    record = config.vision.record_video in ("1", "true", "yes") or (config.vision.record_video == "auto" and config.env == "prod")
    # dev : ni photos ni clips (RECORD_VIDEO=1 pour forcer les clips)
    return VisionService(config.vision, MODELS_DIR, CAPTURES_DIR if config.env == "prod" else None, VIDEOS_DIR if record else None)
