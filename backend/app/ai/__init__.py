from ..config import Config
from .local_analyzer import LocalAnalyzer
from .mock_analyzer import MockAnalyzer


def create_analyzer(config: Config):
    if config.analyzer == "mock":
        return MockAnalyzer()
    if config.analyzer == "local":
        return LocalAnalyzer()
    raise ValueError(f"ANALYZER inconnu : {config.analyzer} (mock | local)")
