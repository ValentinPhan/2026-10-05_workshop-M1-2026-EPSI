"""Logger centralisé : le seul point d'entrée des journaux de l'application.

  from .logger import logger
  logger.emit("vision.intrusion", "Intrusion détectée", level="critical", personCount=2, snapshot="...")

Chaque événement significatif devient UNE ligne JSON (format JSON Lines) dans backend/data/logs/events-AAAA-MM-JJ.jsonl
(un fichier par jour ; dossier modifiable avec LOG_DIR). Une ligne contient toujours :

  ts / tsMs   heure locale ISO (avec fuseau) et epoch en millisecondes
  seq         numéro d'ordre depuis le démarrage du process
  level       debug | info | warning | error | critical
  event       nom pointé de l'événement (« auth.login_failed », « vision.intrusion », « alert.created »...)
  message     phrase lisible
  env         « dev » ou « prod »
  data        les informations propres à l'événement (acteur, adresse IP, chemin de la photo, détections...)
  context     l'ÉTAT COMPLET de l'application à cet instant : dernier snapshot des capteurs (ultrason, thermique,
              environnement, moteur, système, caméra), dernière analyse IA (menace, anomalies), état de la vision,
              alertes actives, clients connectés. Même les informations sans rapport avec l'événement y figurent.

Tout ce qui passe par le module `logging` standard (WARNING et au-dessus, y compris les erreurs d'uvicorn, d'asyncio
et les exceptions non gérées) est aussi recopié dans ce fichier : rien ne se perd. Écrire dans le journal ne doit
jamais faire échouer l'application : toute erreur d'écriture est avalée.

Lecture rapide (PowerShell) :  Get-Content backend\\data\\logs\\events-*.jsonl -Wait | ConvertFrom-Json
"""
import json
import logging
import re
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from .config import LOG_DIR, config

_ANSI = re.compile(r"\x1b\[[0-9;]*m")  # couleurs de la console, inutiles dans le fichier
_LEVELS = ("debug", "info", "warning", "error", "critical")


class Logger:
    def __init__(self, directory: Path, env: str):
        self._dir = directory
        self._env = env
        self._lock = threading.Lock()  # le hub (boucle async), les routes sync (threads) et la vision écrivent
        self._seq = 0
        self._context: Callable[[], dict] | None = None
        self._busy = threading.local()  # évite la récursion si une erreur d'écriture est elle-même journalisée

    def set_context(self, provider: Callable[[], dict]) -> None:
        """Fonction qui renvoie l'état complet de l'application (enregistrée par le Hub)."""
        self._context = provider

    def setup(self) -> None:
        """Console + recopie des warnings/erreurs de `logging` dans le fichier. À appeler une fois, au démarrage."""
        logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
        handler = _JsonHandler(self)
        handler.setLevel(logging.WARNING)
        for name in ("", "uvicorn"):  # uvicorn ne propage pas ses journaux à la racine
            logging.getLogger(name).addHandler(handler)

    def emit(self, event: str, message: str = "", level: str = "info", context: bool = True, **data) -> None:
        """Écrit une ligne. `data` : informations propres à l'événement ; `context=False` : sans l'état complet."""
        if getattr(self._busy, "on", False):
            return
        self._busy.on = True
        try:
            now = datetime.now().astimezone()
            record = {
                "ts": now.isoformat(timespec="milliseconds"),
                "tsMs": int(now.timestamp() * 1000),
                "seq": 0,
                "level": level if level in _LEVELS else "info",
                "event": event,
                "message": _ANSI.sub("", message),
                "env": self._env,
                "data": data,
            }
            if context and self._context is not None:
                try:
                    record["context"] = self._context()
                except Exception as err:  # noqa: BLE001 — un état illisible ne doit pas empêcher la trace
                    record["context"] = {"error": f"{type(err).__name__}: {err}"}
            with self._lock:
                self._seq += 1
                record["seq"] = self._seq
                line = json.dumps(record, ensure_ascii=False, default=str, separators=(",", ":"))
                self._dir.mkdir(parents=True, exist_ok=True)
                with open(self._dir / f"events-{now:%Y-%m-%d}.jsonl", "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:  # noqa: BLE001 — disque plein, droits, état non sérialisable : jamais bloquant
            pass
        finally:
            self._busy.on = False


class _JsonHandler(logging.Handler):
    """Recopie dans le journal JSON les enregistrements `logging` de niveau WARNING et plus."""

    def __init__(self, target: Logger):
        super().__init__()
        self._target = target

    def emit(self, record: logging.LogRecord) -> None:
        extra = {"logger": record.name}
        if record.exc_info:
            extra["exception"] = "".join(traceback.format_exception(*record.exc_info))
        self._target.emit(f"log.{record.levelname.lower()}", record.getMessage(), level=record.levelname.lower(), **extra)


logger = Logger(LOG_DIR, config.env)
