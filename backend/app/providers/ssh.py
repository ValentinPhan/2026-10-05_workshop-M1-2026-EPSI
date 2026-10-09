"""Provider réel : le Raspberry Pi, joint par SSH. Même contrat que MockProvider :
  name                              : str
  async start(on_snapshot)          : lance la collecte, `await on_snapshot(snapshot)` à chaque snapshot reçu
  async stop()                      : arrête la collecte et ferme la connexion
  get_snapshot()                    : dernier snapshot connu (None tant que le Pi n'a rien envoyé)
  async send_motor_command(cmd)     : valide (motor.py), envoie au Pi, retourne l'état moteur attendu
  absent_modules                    : capteurs non montés (jamais signalés en panne, voir modules.py)

Côté Pi : raspberry-pi/sentinel_agent.py, lancé par SSH. Il écrit un snapshot JSON par ligne sur stdout et lit
les commandes moteur (JSON, une par ligne) sur stdin. Le Pi n'envoie que de la donnée BRUTE (pas d'IA).
Forme du snapshot (identique au mock, clés en camelCase = contrat avec le front ; `thermal` vaut null) :
  { ts, ultrasonic:{distanceCm,maxRangeCm}, thermal:null, camera:{streamUrl,width,height,fps},
    motor:{angle,target,speed,mode,moving}, environment:{tempC,humidityPct,readAt}, system:{link,cpuPct,ramPct,cpuTempC,uptimeS} }

Une seule connexion SSH persistante (asyncssh). Coupure du Wi-Fi, Pi redémarré, agent planté : nouvelle tentative
après 1, 2, 5 puis 10 s, indéfiniment. Pendant la coupure plus aucun snapshot n'arrive : la santé des modules
(modules.py) déclare le Raspberry perdu, puis revenu. Fermer la session ferme le stdin de l'agent, qui s'arrête
et relâche le servo. La vidéo ne passe pas par ici (raspberry-pi/camera_push.py) : une rafale d'images
retarderait les ordres moteur.

AGENT_LOCAL=1 : l'agent tourne sur ce PC en mode --fake (sous-processus), sans Raspberry ni SSH.
"""
import asyncio
import json
import logging
import shlex
import sys
from pathlib import Path
from typing import Awaitable, Callable

from ..config import SshConfig
from ..console import green, red
from ..logger import logger
from .motor import apply_motor_command

OnSnapshot = Callable[[dict], Awaitable[None]]
log = logging.getLogger("sentinel-x")

RETRY_S = (1, 2, 5, 10)
CONNECT_TIMEOUT_S = 8
KEEPALIVE_S = 5  # une liaison morte (Wi-Fi coupé) est détectée en ~3 keepalives sans réponse
LOCAL_AGENT = Path(__file__).resolve().parents[3] / "raspberry-pi" / "sentinel_agent.py"
DEFAULT_MOTOR = {"angle": 0.0, "target": 0.0, "speed": 40, "mode": "manual", "moving": False}


class _Session:
    """Un agent en cours d'exécution : flux de sortie à lire, entrée pour les commandes, fermeture."""

    def __init__(self, stdout, stdin, stderr, close: Callable[[], None]):
        self.stdout, self.stdin, self.stderr, self.close = stdout, stdin, stderr, close


class SshProvider:
    def __init__(self, options: SshConfig, tick_ms: int):
        self._opt = options
        self._period_s = tick_ms / 1000
        self.name = "agent local (fake)" if options.local else "ssh"
        self.absent_modules = set(options.absent_modules)
        self._latest: dict | None = None
        self._session: _Session | None = None
        self._task: asyncio.Task | None = None
        self._stopping = False

    # ---- contrat provider ----
    def get_snapshot(self) -> dict | None:
        return self._latest

    async def start(self, on_snapshot: OnSnapshot) -> None:
        self._task = asyncio.create_task(self._run(on_snapshot))

    async def stop(self) -> None:
        self._stopping = True
        if self._session:
            self._session.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass

    async def send_motor_command(self, cmd: dict) -> dict:
        """État moteur attendu après la commande ; ValueError si invalide, ConnectionError si le Pi est injoignable."""
        motor = {**DEFAULT_MOTOR, **((self._latest or {}).get("motor") or {})}
        apply_motor_command(motor, cmd)  # validation avant tout envoi : le Pi ne reçoit que des commandes saines
        if self._session is None:
            raise ConnectionError("Raspberry Pi non connecté")
        try:
            self._session.stdin.write(json.dumps(cmd) + "\n")
        except Exception as err:  # canal en cours de fermeture
            raise ConnectionError(f"envoi au Raspberry Pi impossible : {err}") from err
        return motor

    # ---- connexion ----
    def _agent_args(self) -> list[str]:
        args = ["--period", f"{self._period_s:g}"]
        if self._opt.stream_url:
            args += ["--stream-url", self._opt.stream_url]
        return args

    async def _open_local(self) -> _Session:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(LOCAL_AGENT), "--fake", *self._agent_args(),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )

        class _Writer:  # même interface que le stdin d'asyncssh (write de str)
            def write(self, text: str) -> None:
                proc.stdin.write(text.encode())

        def close() -> None:
            if proc.returncode is None:
                proc.stdin.close()  # l'agent s'arrête de lui-même en voyant stdin fermé
                proc.kill()

        return _Session(proc.stdout, _Writer(), proc.stderr, close)

    async def _open_ssh(self) -> _Session:
        import asyncssh  # import tardif : inutile en mode mock

        opt = self._opt
        kwargs = dict(
            host=opt.host, port=opt.port, username=opt.username,
            keepalive_interval=KEEPALIVE_S, keepalive_count_max=3, connect_timeout=CONNECT_TIMEOUT_S,
        )
        if opt.private_key_path:
            kwargs["client_keys"] = [opt.private_key_path]
        if opt.password:
            kwargs["password"] = opt.password
        if opt.known_hosts.lower() == "none":
            kwargs["known_hosts"] = None
        elif opt.known_hosts:
            kwargs["known_hosts"] = opt.known_hosts
        conn = await asyncssh.connect(**kwargs)
        command = " ".join([opt.command, *map(shlex.quote, self._agent_args())])
        try:
            proc = await conn.create_process(command)
        except Exception:
            conn.close()
            raise

        def close() -> None:
            try:
                proc.stdin.write_eof()  # l'agent voit stdin fermé et s'arrête proprement (servo relâché)
            except Exception:  # canal déjà fermé
                pass
            conn.close()

        return _Session(proc.stdout, proc.stdin, proc.stderr, close)

    async def _relay_stderr(self, stream) -> None:
        """Journal de l'agent (lectures ratées, démarrage...) recopié dans la console du backend."""
        async for line in stream:
            text = (line.decode(errors="replace") if isinstance(line, bytes) else line).rstrip()
            if text:
                log.info(f"[pi] {text}")

    async def _read_snapshots(self, session: _Session, on_snapshot: OnSnapshot) -> None:
        async for line in session.stdout:
            text = (line.decode(errors="replace") if isinstance(line, bytes) else line).strip()
            if not text:
                continue
            try:
                snapshot = json.loads(text)
            except ValueError:
                logger.emit("provider.bad_line", "Ligne illisible reçue du Raspberry Pi", level="warning", line=text[:200])
                continue
            if not isinstance(snapshot, dict):
                continue
            self._latest = snapshot
            await on_snapshot(snapshot)

    async def _run(self, on_snapshot: OnSnapshot) -> None:
        target = "agent local" if self._opt.local else f"{self._opt.username}@{self._opt.host}:{self._opt.port}"
        attempt = 0
        while not self._stopping:
            try:
                session = await (self._open_local() if self._opt.local else self._open_ssh())
            except asyncio.CancelledError:
                raise
            except Exception as err:
                reason = str(err) or type(err).__name__
            else:
                self._session = session
                log.info(green(f"Raspberry Pi connecté ({target})"))
                logger.emit("provider.connect", f"Raspberry Pi connecté ({target})", target=target, failedAttempts=attempt)
                attempt = 0
                stderr_task = asyncio.create_task(self._relay_stderr(session.stderr))
                try:
                    await self._read_snapshots(session, on_snapshot)
                    reason = "l'agent s'est arrêté"
                except asyncio.CancelledError:
                    raise
                except Exception as err:
                    reason = str(err) or type(err).__name__
                finally:
                    self._session = None
                    stderr_task.cancel()
                    session.close()
                if self._stopping:
                    break
            delay = RETRY_S[min(attempt, len(RETRY_S) - 1)]
            attempt += 1
            message = f"Raspberry Pi injoignable ({reason}), nouvelle tentative dans {delay} s"
            log.info(red(message))
            if attempt == 1:  # une ligne de journal par coupure, pas une par tentative (la console les montre toutes)
                logger.emit("provider.disconnect", message, level="warning", target=target, reason=reason)
            await asyncio.sleep(delay)


def create_ssh_provider(options: SshConfig, tick_ms: int = 1000) -> SshProvider:
    return SshProvider(options, tick_ms)
