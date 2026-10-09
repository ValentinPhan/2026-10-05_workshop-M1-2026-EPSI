"""Environnement de test : app/config.py lit les variables à l'import, elles doivent donc être posées avant tout
import de `app`. Base, journal et photos dans un dossier temporaire : la base de l'utilisateur n'est jamais touchée."""
import os
import sys
import tempfile
from pathlib import Path

TMP = tempfile.mkdtemp(prefix="sentinel-tests-")
ADMIN_PASSWORD = "test-password-123"
os.environ.update({
    "DATABASE_URL": f"sqlite:///{Path(TMP, 'test.db').as_posix()}", "LOG_DIR": str(Path(TMP, "logs")),
    "CAPTURES_DIR": str(Path(TMP, "captures")), "VIDEOS_DIR": str(Path(TMP, "videos")),
    "ADMIN_USERNAME": "admin", "ADMIN_PASSWORD": ADMIN_PASSWORD,
    "PROVIDER": "mock", "ANALYZER": "mock", "EDGE": "mock", "APP_ENV": "dev",
    "PI_MQTT": "off", "PI_MQTT_ENV_FILE": "",  # jamais de connexion au vrai broker pendant les tests
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # `import app` depuis backend/
