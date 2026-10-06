from ..config import Config
from ..vision.service import VisionService
from .local_analyzer import LocalAnalyzer
from .mock_analyzer import MockAnalyzer


def create_analyzer(config: Config, vision: VisionService | None):
    if config.analyzer == "mock":
        return MockAnalyzer()
    if config.analyzer == "local":
        return LocalAnalyzer(vision)
    raise ValueError(f"ANALYZER inconnu : {config.analyzer} (mock | local)")
