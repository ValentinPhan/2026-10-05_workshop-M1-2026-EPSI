#!/usr/bin/env python3
"""Agent Sentinel-X sur le Raspberry Pi : lit les capteurs, pilote le servo. Aucun calcul d'IA ici.

Lancé par le backend via SSH (backend/app/providers/ssh.py), ou à la main pour tester :
  stdout : un snapshot JSON par ligne, toutes les --period secondes (donnée BRUTE uniquement)
  stdin  : une commande moteur JSON par ligne, déjà validée par le backend :
           {"type":"move","angle":30} · {"type":"step","delta":-10} · {"type":"sweep","enabled":true}
           {"type":"speed","value":40} · {"type":"stop"}
  stderr : journal (démarrage, lectures ratées, commandes refusées)
stdin fermé (connexion SSH coupée) = l'agent s'arrête : le servo n'est jamais laissé piloté par un backend parti.
Un seul agent à la fois : après une coupure Wi-Fi, l'ancien peut tourner encore (le Pi ne voit pas tout de suite
que la liaison est morte) et tiendrait les GPIO ; le nouvel agent lui demande de s'arrêter (SIGTERM) avant de démarrer.

Câblage (numéros BCM ; entre parenthèses, la broche physique du connecteur 40 broches) :
  Servo SG90        : signal (orange) -> GPIO18 (12)   + (rouge) -> 5 V (2)   - (marron) -> GND (14)
  Ultrason HC-SR04  : Trig -> GPIO23 (16)   Echo -> GPIO24 (18) AVEC DIVISEUR (1 kOhm en série, 2 kOhm vers GND),
                      car Echo sort en 5 V   ·   VCC -> 5 V (4)   GND -> GND (6)
  DHT22             : + -> 3,3 V (1)   out -> GPIO4 (7)   - -> GND (9)   (voir dht22_reader.py)
Pas de matrice thermique : `thermal` vaut null (le backend et le dashboard le savent, voir ABSENT_MODULES).
La caméra passe à part (camera_push.py) : `camera.streamUrl` ne sert que pour un flux MJPEG en pull (--stream-url).

Servo : 0..180° physiques = -90..+90° pour le dashboard (0° = face avant). Pas de capteur de position :
l'angle affiché est la consigne envoyée, déplacée à la vitesse demandée. À l'arrêt, le signal est coupé
(sinon le SG90 tremble et chauffe) : il garde sa position tant qu'on ne force pas dessus.

Usage :  python3 sentinel_agent.py [--period 1] [--fake] [--stream-url http://IP:8080/stream.mjpg]
  --fake : aucune broche GPIO, valeurs synthétiques (test du protocole sur un PC, sans Raspberry).
Dépendances (Raspberry Pi OS) : sudo apt install python3-gpiozero python3-lgpio
  conseillé pour un servo sans tremblement : sudo apt install pigpio python3-pigpio && sudo systemctl enable --now pigpiod
  + celles de dht22_reader.py (pilote noyau dtoverlay=dht11,gpiopin=4, ou adafruit-circuitpython-dht)
"""
import argparse
import json
import math
import os
import random
import signal
import sys
import threading
import time

PIN_SERVO = 18
PIN_TRIG, PIN_ECHO = 23, 24
DHT_GPIO = 4

MAX_RANGE_CM = 400
MIN_ANGLE, MAX_ANGLE = -90, 90  # mêmes bornes que backend/app/providers/motor.py
MIN_SPEED, MAX_SPEED = 5, 90
SWEEP_ANGLE = 60  # balayage automatique entre -60° et +60°
SERVO_MIN_PULSE, SERVO_MAX_PULSE = 0.0005, 0.0025  # SG90 : 0,5 ms = 0°, 2,5 ms = 180° (ajuster si la course est courte)
SERVO_DIR = 1  # -1 si le servo tourne à l'envers du dashboard
SERVO_RELEASE_S = 0.6  # coupe le signal après ce délai à l'arrêt
MOTION_DT = 0.02  # pas de la boucle de mouvement (50 Hz, la fréquence du signal servo)
PID_FILE = "/tmp/sentinel_agent.pid"

started = time.time()
stop_event = threading.Event()


def log(msg: str) -> None:
    print(f"[agent] {msg}", file=sys.stderr, flush=True)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- servo SG90
class Servo:
    def __init__(self, fake: bool):
        self.device = None
        if not fake:
            from gpiozero import AngularServo

            factory = None
            try:  # pigpio : PWM matériel, servo stable ; sinon PWM logiciel (lgpio), qui fait trembler un peu
                from gpiozero.pins.pigpio import PiGPIOFactory

                factory = PiGPIOFactory()
                log("servo : PWM pigpio")
            except Exception as err:  # démon pigpiod absent, paquet non installé...
                log(f"servo : pigpio indisponible ({err}), PWM logiciel")
            self.device = AngularServo(
                PIN_SERVO, min_angle=MIN_ANGLE, max_angle=MAX_ANGLE, initial_angle=None,
                min_pulse_width=SERVO_MIN_PULSE, max_pulse_width=SERVO_MAX_PULSE, pin_factory=factory,
            )
        self.lock = threading.Lock()
        self.angle = 0.0  # position supposée (pas de retour de position sur un SG90)
        self.target = 0.0
        self.speed = 40.0
        self.sweeping = False
        self.sweep_dir = 1
        self.attached = False
        self._write(0.0)  # au démarrage : face avant

    def _write(self, angle: float) -> None:
        if self.device is not None:
            self.device.angle = clamp(SERVO_DIR * angle, MIN_ANGLE, MAX_ANGLE)
        self.attached = True

    def _release(self) -> None:
        if self.device is not None:
            self.device.detach()
        self.attached = False

    def command(self, cmd: dict) -> None:
        kind = cmd.get("type")
        with self.lock:
            if kind == "move":
                self.sweeping = False
                self.target = clamp(float(cmd["angle"]), MIN_ANGLE, MAX_ANGLE)
            elif kind == "step":
                self.sweeping = False
                self.target = clamp(self.target + float(cmd["delta"]), MIN_ANGLE, MAX_ANGLE)
            elif kind == "sweep":
                self.sweeping = bool(cmd["enabled"])
                if not self.sweeping:
                    self.target = self.angle
            elif kind == "speed":
                self.speed = clamp(float(cmd["value"]), MIN_SPEED, MAX_SPEED)
            elif kind == "stop":
                self.sweeping = False
                self.target = self.angle
            else:
                raise ValueError(f"commande inconnue : {kind}")

    def state(self) -> dict:
        with self.lock:
            return {
                "angle": round(self.angle, 1),
                "target": round(self.target, 1),
                "speed": self.speed,
                "mode": "sweep" if self.sweeping else "manual",
                "moving": abs(self.target - self.angle) > 0.5,
            }

    def run(self) -> None:
        idle_since = time.monotonic()
        while not stop_event.is_set():
            with self.lock:
                if self.sweeping:
                    if abs(self.angle - self.target) < 1:
                        self.sweep_dir = -self.sweep_dir
                    self.target = self.sweep_dir * SWEEP_ANGLE
                diff = self.target - self.angle
                step = self.speed * MOTION_DT
                moving = abs(diff) > 0.05
                if moving:
                    self.angle = self.target if abs(diff) <= step else self.angle + math.copysign(step, diff)
                    angle = self.angle
            now = time.monotonic()
            if moving:
                idle_since = now
                self._write(angle)
            elif self.attached and now - idle_since > SERVO_RELEASE_S:
                self._release()
            time.sleep(MOTION_DT)
        self._release()


# ---------------------------------------------------------------- ultrason HC-SR04
class Ultrasonic:
    def __init__(self, fake: bool):
        self.fake = fake
        self.sensor = None
        if not fake:
            from gpiozero import DistanceSensor

            self.sensor = DistanceSensor(echo=PIN_ECHO, trigger=PIN_TRIG, max_distance=MAX_RANGE_CM / 100, queue_len=3)

    def read(self) -> float | None:
        if self.fake:
            near = 60 if int(time.time() - started) % 40 > 30 else 300  # un « intrus » 10 s toutes les 40 s
            return round(clamp(near + random.uniform(-2, 2), 2, MAX_RANGE_CM), 1)
        try:
            return round(clamp(self.sensor.distance * 100, 2, MAX_RANGE_CM), 1)
        except Exception as err:  # écho perdu, broche en défaut : le backend signalera le capteur muet
            log(f"lecture ultrason ratée : {err}")
            return None


# ---------------------------------------------------------------- DHT22
class Dht:
    """Lit le DHT22 dans un thread (une mesure / 2 s) ; garde la dernière lecture valide."""

    def __init__(self, fake: bool):
        self.fake = fake
        self.last: dict = {}
        self.read = None
        if not fake:
            from dht22_reader import adafruit_reader, iio_reader  # même dossier que cet agent

            self.read = iio_reader() or adafruit_reader(DHT_GPIO)

    def run(self) -> None:
        period, plausible = 2.0, (lambda t, h, prev: True)
        if not self.fake:
            from dht22_reader import MIN_PERIOD_S, plausible

            period = MIN_PERIOD_S
        prev = None
        while not stop_event.is_set():
            t0 = time.monotonic()
            try:
                if self.fake:
                    t = time.time() - started
                    temp, hum = 23 + math.sin(t / 600) + random.uniform(-0.1, 0.1), 48 + 2 * math.sin(t / 900)
                else:
                    temp, hum = self.read()
                if plausible(temp, hum, prev):
                    prev = (temp, hum)
                    self.last = {"tempC": round(temp, 1), "humidityPct": round(hum, 1), "readAt": int(time.time() * 1000)}
            except (OSError, RuntimeError) as err:  # checksum / timeout : fréquent, on réessaie au tour suivant
                log(f"lecture DHT22 ratée : {err}")
            stop_event.wait(max(0.0, period - (time.monotonic() - t0)))


# ---------------------------------------------------------------- système
def system_stats(prev: list) -> dict:
    stats = {"link": "ssh", "cpuPct": 0, "ramPct": 0, "cpuTempC": None, "uptimeS": int(time.time() - started)}
    try:
        with open("/proc/stat") as f:
            parts = [int(x) for x in f.readline().split()[1:]]
        idle, total = parts[3] + parts[4], sum(parts)
        if prev[0] is not None and total > prev[1]:
            stats["cpuPct"] = round(100 * (1 - (idle - prev[0]) / (total - prev[1])))
        prev[0], prev[1] = idle, total
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                key, val = line.split(":")
                mem[key] = int(val.split()[0])
        stats["ramPct"] = round(100 * (1 - mem["MemAvailable"] / mem["MemTotal"]))
        with open("/proc/uptime") as f:
            stats["uptimeS"] = int(float(f.read().split()[0]))
    except (OSError, KeyError, ValueError, IndexError):
        pass  # hors Linux (mode --fake sur un autre OS) : valeurs par défaut
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            stats["cpuTempC"] = round(int(f.read()) / 1000, 1)
    except (OSError, ValueError):
        pass
    return stats


# ---------------------------------------------------------------- un seul agent à la fois
def _running(pid: int) -> bool:
    """Processus vivant (un zombie, terminé mais pas encore récupéré par son parent, ne tient plus les GPIO)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return False


def take_over() -> None:
    """Arrête un agent précédent encore vivant (liaison SSH morte mais pas encore détectée), puis prend sa place."""
    try:
        with open(PID_FILE) as f:
            old = int(f.read().strip())
        with open(f"/proc/{old}/cmdline", "rb") as f:
            alive = old != os.getpid() and b"sentinel_agent" in f.read()
    except (OSError, ValueError):
        alive = False
    if alive:
        log(f"agent précédent (pid {old}) encore actif : arrêt demandé")
        os.kill(old, signal.SIGTERM)
        for _ in range(30):  # il relâche le servo et les GPIO en ~0,1 s
            if not _running(old):
                break
            time.sleep(0.1)
        else:
            os.kill(old, signal.SIGKILL)
            time.sleep(0.2)
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


# ---------------------------------------------------------------- commandes (stdin)
def read_commands(servo: Servo) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            servo.command(json.loads(line))
        except (ValueError, KeyError, TypeError) as err:
            log(f"commande ignorée ({line}) : {err}")
    stop_event.set()  # stdin fermé : backend parti, on arrête tout (servo relâché)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--period", type=float, default=1.0, help="secondes entre deux snapshots")
    ap.add_argument("--stream-url", default=None, help="URL d'un flux MJPEG du Pi (mode pull), sinon null")
    ap.add_argument("--fake", action="store_true", help="sans GPIO : valeurs synthétiques")
    args = ap.parse_args()

    for sig in (signal.SIGTERM, signal.SIGHUP):  # arrêt demandé (nouvel agent, fin de session) : sortie propre
        signal.signal(sig, lambda *_: stop_event.set())
    if not args.fake:
        take_over()
    servo, ultra, dht = Servo(args.fake), Ultrasonic(args.fake), Dht(args.fake)
    for target in (servo.run, dht.run):
        threading.Thread(target=target, daemon=True).start()
    threading.Thread(target=read_commands, args=(servo,), daemon=True).start()
    log(f"démarré (period={args.period}s, fake={args.fake}) : servo centré à 0°")

    cpu_prev = [None, 0]
    while not stop_event.is_set():
        t0 = time.monotonic()
        snapshot = {
            "ts": int(time.time() * 1000),
            "ultrasonic": {"distanceCm": ultra.read(), "maxRangeCm": MAX_RANGE_CM},
            "thermal": None,
            "camera": {"streamUrl": args.stream_url, "width": 640, "height": 480, "fps": 15},
            "motor": servo.state(),
            "environment": dict(dht.last),
            "system": system_stats(cpu_prev),
        }
        try:
            print(json.dumps(snapshot), flush=True)
        except BrokenPipeError:  # stdout fermé : plus personne n'écoute
            break
        stop_event.wait(max(0.0, args.period - (time.monotonic() - t0)))
    stop_event.set()
    time.sleep(0.1)  # laisse le thread du servo couper le signal


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_event.set()
