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

Historique lisible : backend/data/logs/sentinel-AAAA-MM-JJ.log, un fichier texte par jour, une ligne horodatée par
message de la console (INFO et plus : démarrage, connexions, Raspberry, agent du Pi, vision, ESP8266, exceptions avec
leur trace) et par événement du journal JSON (sans l'état complet). C'est le fil du fonctionnement, à lire ou suivre
en direct ; le JSON reste la référence pour l'analyse.

Secrets : un message `logging` passé avec extra={"console_only": True} (mot de passe initial de l'admin) s'affiche
dans la console mais n'est écrit dans AUCUN fichier.

Rétention : au démarrage puis à chaque changement de jour, les fichiers events-*.jsonl et sentinel-*.log de plus de
LOG_KEEP_DAYS jours (30 par défaut, 0 = tout garder) sont supprimés.

Lecture rapide (PowerShell) :  Get-Content backend\\data\\logs\\events-*.jsonl -Wait | ConvertFrom-Json
Suivre l'historique :          Get-Content backend\\data\\logs\\sentinel-$(Get-Date -f yyyy-MM-dd).log -Wait
"""
import json
import logging
import re
import threading
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from .config import LOG_DIR, config

_ANSI = re.compile(r"\x1b\[[0-9;]*m")  # couleurs de la console, inutiles dans le fichier
_LEVELS = ("debug", "info", "warning", "error", "critical")
_DATED = re.compile(r"^(?:events|sentinel)-(\d{4}-\d{2}-\d{2})\.(?:jsonl|log)$")  # fichiers gérés par la rétention


class Logger:
    def __init__(self, directory: Path, env: str, keep_days: int = 0):
        self._dir = directory
        self._env = env
        self._keep_days = keep_days
        self._lock = threading.Lock()  # le hub (boucle async), les routes sync (threads) et la vision écrivent
        self._text_lock = threading.Lock()
        self._day: date | None = None  # dernier jour écrit : un changement déclenche la rétention
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
        text = TextHandler(self)
        text.setLevel(logging.INFO)
        for name in ("", "uvicorn"):  # uvicorn ne propage pas ses journaux à la racine
            logging.getLogger(name).addHandler(handler)
            logging.getLogger(name).addHandler(text)
        self._rotate(datetime.now().astimezone().date())

    # ---- historique texte (sentinel-AAAA-MM-JJ.log) ----
    def write_text(self, level: str, source: str, message: str, when: datetime | None = None) -> None:
        """Ajoute une ligne à l'historique texte du jour. Jamais bloquant."""
        try:
            now = when or datetime.now().astimezone()
            text = _ANSI.sub("", message).rstrip()
            line = f"{now:%Y-%m-%d %H:%M:%S}.{now.microsecond // 1000:03d} {level.upper():<8} [{source}] {text}"
            with self._text_lock:
                self._rotate(now.date())
                self._dir.mkdir(parents=True, exist_ok=True)
                with open(self._dir / f"sentinel-{now:%Y-%m-%d}.log", "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:  # noqa: BLE001 — disque plein, droits : jamais bloquant
            pass

    # ---- rétention ----
    def _rotate(self, today: date) -> None:
        if today == self._day:
            return
        self._day = today
        self.purge(today)

    def purge(self, today: date) -> list[str]:
        """Supprime les journaux datés de plus de `keep_days` jours ; renvoie les noms supprimés."""
        if self._keep_days <= 0 or not self._dir.is_dir():
            return []
        oldest = today - timedelta(days=self._keep_days - 1)  # keep_days = 1 : seulement aujourd'hui
        removed = []
        for path in self._dir.iterdir():
            m = _DATED.match(path.name)
            if not m:
                continue
            try:
                if date.fromisoformat(m.group(1)) < oldest:
                    path.unlink()
                    removed.append(path.name)
            except (ValueError, OSError):  # date invalide, fichier ouvert ailleurs (Windows) : on réessaiera
                continue
        return sorted(removed)

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
            if not event.startswith("log."):  # log.* = un message `logging`, déjà écrit par TextHandler
                self.write_text(record["level"], event, record["message"], now)
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
        if getattr(record, "console_only", False):
            return
        extra = {"logger": record.name}
        if record.exc_info:
            extra["exception"] = "".join(traceback.format_exception(*record.exc_info))
        self._target.emit(f"log.{record.levelname.lower()}", record.getMessage(), level=record.levelname.lower(), **extra)


class TextHandler(logging.Handler):
    """Recopie dans l'historique texte du jour les messages `logging` (INFO et plus), avec la trace des exceptions."""

    def __init__(self, target: Logger):
        super().__init__()
        self._target = target

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "console_only", False):  # secret affiché à l'écran seulement
            return
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + "".join(traceback.format_exception(*record.exc_info)).rstrip()
        when = datetime.fromtimestamp(record.created).astimezone()
        self._target.write_text(record.levelname, record.name, message, when)


logger = Logger(LOG_DIR, config.env, config.log_keep_days)
