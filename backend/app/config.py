"""Configuration centrale, surchargeable par variables d'environnement."""
import os
from dataclasses import dataclass, field


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


@dataclass(frozen=True)
class SshConfig:
    host: str = os.environ.get("SSH_HOST", "192.168.50.10")
    port: int = int(_num("SSH_PORT", 22))
    username: str = os.environ.get("SSH_USER", "pi")
    private_key_path: str = os.environ.get("SSH_KEY", "")


@dataclass(frozen=True)
class Config:
    # "mock" (données fictives) ou "ssh" (Raspberry Pi réel)
    provider: str = os.environ.get("PROVIDER", "mock")
    # Modèle IA local (score de menace + détections) : "mock" (heuristique) ou "local" (vrai modèle, voir app/ai/)
    analyzer: str = os.environ.get("ANALYZER", "mock")
    tick_ms: int = int(_num("TICK_MS", 1000))
    history_size: int = int(_num("HISTORY_SIZE", 120))
    alerts_size: int = int(_num("ALERTS_SIZE", 50))
    ssh: SshConfig = field(default_factory=SshConfig)
    thresholds: Thresholds = field(default_factory=Thresholds)


config = Config()
