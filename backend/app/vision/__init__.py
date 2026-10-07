from ..config import CAPTURES_DIR, MODELS_DIR, Config
from .service import VisionService


def create_vision(config: Config) -> VisionService | None:
    """Le service de vision (caméra + YOLO) n'existe qu'avec ANALYZER=local."""
    if config.analyzer != "local":
        return None
    return VisionService(config.vision, MODELS_DIR, CAPTURES_DIR if config.env == "prod" else None)  # dev : pas de photos
