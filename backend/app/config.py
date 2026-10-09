"""Configuration centrale, surchargeable par variables d'environnement."""
import os
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PKI_DIR = BACKEND_DIR.parent / "infra" / "pki" / "out"  # certificats générés par infra/pki/gen-certs.sh


def _load_dotenv() -> None:
    """Lit backend/.env (ignoré par git : mots de passe, DATABASE_URL...). Les variables déjà définies gagnent."""
    path = BACKEND_DIR / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_dotenv()  # avant les valeurs par défaut ci-dessous, qui lisent os.environ à l'import

MODELS_DIR = BACKEND_DIR / "models"  # poids des modèles (YOLO, ...)
CAPTURES_DIR = Path(os.environ.get("CAPTURES_DIR", BACKEND_DIR / "data" / "captures"))  # photos d'intrusion
VIDEOS_DIR = Path(os.environ.get("VIDEOS_DIR", BACKEND_DIR / "data" / "videos"))  # clips vidéo des intrusions
LOG_DIR = Path(os.environ.get("LOG_DIR", BACKEND_DIR / "data" / "logs"))  # journal JSON des événements (voir logger.py)


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
    gas_raw: float = _num("GAS_ALERT_RAW", 600)  # MQ-2 de l'ESP8266 : lecture brute A0 (0..1023) au-delà de laquelle on alerte


@dataclass(frozen=True)
class SshConfig:
    """Liaison avec le Raspberry (PROVIDER=ssh, voir providers/ssh.py)."""

    host: str = os.environ.get("SSH_HOST", "192.168.50.10")
    port: int = int(_num("SSH_PORT", 22))
    username: str = os.environ.get("SSH_USER", "pi")
    private_key_path: str = os.environ.get("SSH_KEY", "")  # vide = clés par défaut de ~/.ssh et agent SSH
    password: str = os.environ.get("SSH_PASSWORD", "")  # à éviter (clé conseillée) ; à mettre dans backend/.env
    # Empreintes acceptées pour le Pi : fichier known_hosts (vide = ~/.ssh/known_hosts). "none" désactive la
    # vérification (connexion sans savoir si c'est bien le Pi : à réserver aux tests).
    known_hosts: str = os.environ.get("SSH_KNOWN_HOSTS", "")
    # Commande lancée sur le Pi ; le backend y ajoute --period (et --stream-url si STREAM_URL est défini).
    command: str = os.environ.get("SSH_COMMAND", "python3 -u ~/sentinel-x/raspberry-pi/sentinel_agent.py")
    stream_url: str = os.environ.get("STREAM_URL", "")  # flux MJPEG du Pi (mode pull), recopié dans snapshot.camera
    # AGENT_LOCAL=1 : lance l'agent sur ce PC en mode --fake, sans Raspberry (teste toute la chaîne SSH sauf le réseau)
    local: bool = os.environ.get("AGENT_LOCAL", "0").lower() in ("1", "true", "yes")
    # Capteurs absents du boîtier : jamais signalés en panne, panneau masqué (la matrice thermique n'est pas montée)
    absent_modules: tuple[str, ...] = tuple(
        m.strip() for m in os.environ.get("ABSENT_MODULES", "thermal").split(",") if m.strip()
    )


@dataclass(frozen=True)
class EdgeConfig:
    """Edge Node ESP8266 (gaz MQ-2, présence PIR) relié en MQTTS au broker Mosquitto (infra/docker-compose.yml).

    EDGE : "mqtt" (vrai boîtier), "mock" (ESP simulé, pour développer sans matériel) ou "off".
    Défaut : "mock" avec PROVIDER=mock, sinon "off". Voir docs/mqtt-contract.md.
    """

    source: str = os.environ.get("EDGE", "mock" if os.environ.get("PROVIDER", "mock") == "mock" else "off").strip().lower()
    host: str = os.environ.get("MQTT_HOST", "127.0.0.1")
    port: int = int(_num("MQTT_PORT", 8883))
    ca: str = os.environ.get("MQTT_CA", str(PKI_DIR / "ca.crt"))
    cert: str = os.environ.get("MQTT_CERT", str(PKI_DIR / "backend.crt"))
    key: str = os.environ.get("MQTT_KEY", str(PKI_DIR / "backend.key"))
    client_id: str = os.environ.get("MQTT_CLIENT_ID", "backend")  # doit être le CN du certificat (ACL du broker)
    timeout_s: float = _num("EDGE_TIMEOUT_S", 10)  # sans message d'un boîtier pendant ce délai = perte de connexion


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
    # Clip vidéo H.264 par intrusion (voir vision/recorder.py). auto = activé en prod, désactivé en dev ; 1 / 0 pour forcer.
    record_video: str = os.environ.get("RECORD_VIDEO", "auto").strip().lower()
    record_preroll_s: float = _num("RECORD_PREROLL_S", 2)  # secondes avant la détection incluses dans le clip
    record_max_s: float = _num("RECORD_MAX_S", 180)  # un clip plus long est coupé en parties
    record_crf: int = int(_num("RECORD_CRF", 28))  # qualité H.264 : plus bas = meilleure qualité, plus lourd (23 à 32)
    record_max_width: int = int(_num("RECORD_MAX_WIDTH", 640))
    record_keep_mb: float = _num("RECORD_KEEP_MB", 1000)  # quota du dossier : les plus anciens clips sont supprimés


@dataclass(frozen=True)
class AuthConfig:
    """Base de données et comptes. Deux rôles : admin (tout, dont piloter la caméra) et agent (consultation seule)."""

    # SQLite par défaut (un fichier, rien à installer). PostgreSQL : postgresql+psycopg://user:motdepasse@hote:5432/base
    database_url: str = os.environ.get("DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'data' / 'sentinel.db').as_posix()}")
    session_hours: float = _num("SESSION_HOURS", 12)
    cookie_secure: bool = os.environ.get("COOKIE_SECURE", "0").lower() in ("1", "true", "yes")  # 1 si servi en HTTPS
    # Premier lancement : compte admin créé s'il n'existe aucun utilisateur. Sans ADMIN_PASSWORD, un mot de passe
    # aléatoire est généré et affiché une seule fois dans la console du backend.
    admin_username: str = os.environ.get("ADMIN_USERNAME", "admin")
    admin_password: str = os.environ.get("ADMIN_PASSWORD", "")
    # Compte agent (consultation seule) créé au démarrage s'il n'existe pas, seulement si AGENT_PASSWORD est renseigné.
    agent_username: str = os.environ.get("AGENT_USERNAME", "agent")
    agent_password: str = os.environ.get("AGENT_PASSWORD", "")
    # Jeton des appareils (Raspberry) qui envoient leurs images sur /ws/camera sans passer par un compte.
    # Vide = désactivé : seule la webcam d'un admin connecté peut alors envoyer des images.
    device_token: str = os.environ.get("DEVICE_TOKEN", "")


@dataclass(frozen=True)
class Config:
    # "prod" (défaut) ou "dev". En dev, aucune photo d'intrusion n'est enregistrée (l'alerte reste créée, sans image).
    env: str = "dev" if os.environ.get("APP_ENV", "prod").strip().lower() in ("dev", "development") else "prod"
    # "mock" (données fictives) ou "ssh" (Raspberry Pi réel)
    provider: str = os.environ.get("PROVIDER", "mock")
    # Analyse : "mock" (heuristique factice) ou "local" (YOLO sur la caméra + fusion des capteurs, voir app/vision/)
    analyzer: str = os.environ.get("ANALYZER", "mock")
    tick_ms: int = int(_num("TICK_MS", 1000))
    # Santé des modules (voir modules.py) : délai sans snapshot avant de déclarer le Raspberry perdu, et âge maximal
    # de la dernière mesure du DHT22.
    module_timeout_s: float = _num("MODULE_TIMEOUT_S", 5)
    dht_stale_s: float = _num("DHT_STALE_S", 30)
    # Relevé périodique dans le journal JSON (monitoring et analyse a posteriori) : une ligne avec toutes les données
    # des capteurs au moins toutes les MONITOR_INTERVAL_S secondes, indépendamment de tout événement.
    monitor_interval_s: float = max(1.0, _num("MONITOR_INTERVAL_S", 60))
    history_size: int = int(_num("HISTORY_SIZE", 120))
    alerts_size: int = int(_num("ALERTS_SIZE", 50))
    ssh: SshConfig = field(default_factory=SshConfig)
    edge: EdgeConfig = field(default_factory=EdgeConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    thresholds: Thresholds = field(default_factory=Thresholds)


config = Config()
