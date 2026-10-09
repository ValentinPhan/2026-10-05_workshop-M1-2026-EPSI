"""Horloge commune : l'heure en millisecondes depuis 1970 (le format de tous les horodatages de l'API)."""
import time


def now_ms() -> int:
    return int(time.time() * 1000)
