from ..config import Config
from .mock import MockProvider
from .ssh import create_ssh_provider


def create_provider(config: Config):
    if config.provider == "mock":
        return MockProvider(tick_ms=config.tick_ms)
    if config.provider == "ssh":
        return create_ssh_provider(config.ssh)
    raise ValueError(f"PROVIDER inconnu : {config.provider} (mock | ssh)")
