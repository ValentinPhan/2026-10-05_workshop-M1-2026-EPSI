#!/usr/bin/env python3
"""Agent Sentinel-X sur le Raspberry Pi : lit les capteurs, pilote le moteur.

Protocole (lu par server/src/providers/sshProvider.js, lancé via SSH) :
  stdout : un snapshot JSON par ligne, toutes les --period secondes (donnée BRUTE uniquement)
  stdin  : une commande moteur JSON par ligne, déjà validée côté serveur :
           {"type":"move","angle":30} · {"type":"step","delta":-10} · {"type":"sweep","enabled":true}
           {"type":"speed","value":40} · {"type":"stop"}
  stderr : journal (messages d'erreur, démarrage)

Câblage (numéros BCM ; entre parenthèses, la broche physique du connecteur 40 broches) :
  Moteur 28BYJ-48 via carte ULN2003 : IN1=GPIO17 (11)  IN2=GPIO18 (12)  IN3=GPIO27 (13)  IN4=GPIO22 (15)
                                      + -> 5 V (4)   - -> GND (14)
  Ultrason HC-SR04 : Trig=GPIO23 (16)  Echo=GPIO24 (18) AVEC DIVISEUR (1 kΩ en série + 2 kΩ vers GND) : Echo sort en 5 V !
                     VCC -> 5 V (2)  GND -> GND (6, 9, 20…)
  DHT22 : + -> 3,3 V (1)  out -> GPIO4 (7)  - -> GND (6)   (voir dht22_reader.py)
Pas de matrice thermique ni de caméra gérée ici : `thermal` vaut null, `camera.streamUrl` vient de --stream-url.

Un moteur pas à pas n'a pas de capteur de position : au lancement, la position courante = 0° (face avant).

Usage : python3 sentinel_agent.py [--period 1] [--stream-url http://IP:8080/stream.mjpg] [--fake]
  --fake : aucune broche GPIO, valeurs synthétiques (test du protocole sur un PC, sans Raspberry).
Dépendances : sudo apt install python3-gpiozero python3-lgpio   (+ celles de dht22_reader.py)
"""
import argparse
import json
import math
import random
import sys
import threading
import time

PIN_MOTOR = (17, 18, 27, 22)
PIN_TRIG, PIN_ECHO = 23, 24
DHT_GPIO = 4

MAX_RANGE_CM = 400
MOTOR_LIMITS = {"minAngle": -90, "maxAngle": 90, "minSpeed": 5, "maxSpeed": 60}  # 60 °/s : au-delà le 28BYJ-48 décroche
STEPS_PER_DEG = 4076 / 360  # 28BYJ-48 en demi-pas
SWEEP_ANGLE = 60
IDLE_RELEASE_S = 0.5  # coupe les bobines à l'arrêt (le moteur chauffe sinon)
HALF_STEP = [(1, 0, 0, 0), (1, 1, 0, 0), (0, 1, 0, 0), (0, 1, 1, 0), (0, 0, 1, 0), (0, 0, 1, 1), (0, 0, 0, 1), (1, 0, 0, 1)]
MOTOR_DIR = 1  # -1 pour inverser le sens de rotation

started = time.time()
stop_event = threading.Event()


def log(msg):
    print(f"[agent] {msg}", file=sys.stderr, flush=True)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---------------------------------------------------------------- moteur
class Motor:
    def __init__(self, fake):
        self.coils = None
        if not fake:
            from gpiozero import OutputDevice

            self.coils = [OutputDevice(p) for p in PIN_MOTOR]
        self.lock = threading.Lock()
        self.pos = 0  # pas depuis la position de départ
        self.target = 0
        self.target_deg = 0.0
        self.speed = 40.0
        self.sweeping = False
        self.sweep_dir = 1
        self.phase = 0
        self.energized = False

    def _set_target(self, deg):
        self.target_deg = clamp(deg, MOTOR_LIMITS["minAngle"], MOTOR_LIMITS["maxAngle"])
        self.target = round(self.target_deg * STEPS_PER_DEG)

    def command(self, cmd):
        kind = cmd.get("type")
        with self.lock:
            if kind == "move":
                self.sweeping = False
                self._set_target(float(cmd["angle"]))
            elif kind == "step":
                self.sweeping = False
                self._set_target(self.target_deg + float(cmd["delta"]))
            elif kind == "sweep":
                self.sweeping = bool(cmd["enabled"])
                if not self.sweeping:
                    self._set_target(self.pos / STEPS_PER_DEG)
            elif kind == "speed":
                self.speed = clamp(float(cmd["value"]), MOTOR_LIMITS["minSpeed"], MOTOR_LIMITS["maxSpeed"])
            elif kind == "stop":
                self.sweeping = False
                self.target = self.pos
                self.target_deg = self.pos / STEPS_PER_DEG
            else:
                raise ValueError(f"commande inconnue : {kind}")

    def state(self):
        with self.lock:
            return {
                "angle": round(self.pos / STEPS_PER_DEG, 1),
                "target": round(self.target_deg, 1),
                "speed": self.speed,
                "mode": "sweep" if self.sweeping else "manual",
                "moving": self.pos != self.target,
            }

    def _write(self, bits):
        if self.coils:
            for coil, bit in zip(self.coils, bits):
                coil.value = bit

    def release(self):
        self._write((0, 0, 0, 0))
        self.energized = False

    def run(self):
        next_t = time.perf_counter()
        idle_since = time.perf_counter()
        while not stop_event.is_set():
            with self.lock:
                if self.sweeping:
                    angle = self.pos / STEPS_PER_DEG
                    if abs(angle - self.target_deg) < 1:
                        self.sweep_dir = -self.sweep_dir
                    self._set_target(self.sweep_dir * SWEEP_ANGLE)
                delta = self.target - self.pos
                direction = (delta > 0) - (delta < 0)
                interval = 1.0 / (self.speed * STEPS_PER_DEG)
            now = time.perf_counter()
            if direction == 0:
                if self.energized and now - idle_since > IDLE_RELEASE_S:
                    self.release()
                next_t = now
                time.sleep(0.01)
                continue
            idle_since = now
            if now < next_t:
                time.sleep(next_t - now)
            next_t = max(next_t + interval, time.perf_counter() - interval)  # rattrape un retard sans rafale
            with self.lock:
                self.pos += direction
            self.phase = (self.phase + 8 + direction * MOTOR_DIR) % 8
            self._write(HALF_STEP[self.phase])
            self.energized = True
        self.release()


# ---------------------------------------------------------------- ultrason
class Ultrasonic:
    def __init__(self, fake):
        self.fake = fake
        self.sensor = None
        if not fake:
            from gpiozero import DistanceSensor

            self.sensor = DistanceSensor(echo=PIN_ECHO, trigger=PIN_TRIG, max_distance=MAX_RANGE_CM / 100, queue_len=3)

    def read(self):
        if self.fake:
            t = time.time() - started
            near = 60 if int(t) % 40 > 30 else 300  # un « intrus » toutes les 40 s
            return round(clamp(near + random.uniform(-2, 2), 2, MAX_RANGE_CM), 1)
        return round(clamp(self.sensor.distance * 100, 2, MAX_RANGE_CM), 1)


# ---------------------------------------------------------------- DHT22
class Dht:
    """Lit le DHT22 dans un thread (une mesure / 2 s) ; garde la dernière lecture valide."""

    def __init__(self, fake):
        self.fake = fake
        self.last = {}
        self.read = None
        if not fake:
            from dht22_reader import adafruit_reader, iio_reader

            self.read = iio_reader() or adafruit_reader(DHT_GPIO)

    def run(self):
        from_dht = None
        if not self.fake:
            from dht22_reader import MIN_PERIOD_S, plausible

        while not stop_event.is_set():
            started_at = time.monotonic()
            try:
                if self.fake:
                    t = time.time() - started
                    temp, hum = 23 + math.sin(t / 600), 48 + 2 * math.sin(t / 900)
                else:
                    temp, hum = self.read()
                if self.fake or plausible(temp, hum, from_dht):
                    from_dht = (temp, hum)
                    self.last = {"tempC": round(temp, 1), "humidityPct": round(hum, 1), "readAt": int(time.time() * 1000)}
            except (OSError, RuntimeError) as err:  # checksum / timeout : fréquent, on réessaie
                log(f"lecture DHT22 ratée : {err}")
            period = 2.0 if self.fake else MIN_PERIOD_S
            stop_event.wait(max(0.0, period - (time.monotonic() - started_at)))


# ---------------------------------------------------------------- système
def read_cpu_times():
    with open("/proc/stat") as f:
        parts = [int(x) for x in f.readline().split()[1:]]
    return parts[3] + parts[4], sum(parts)  # idle(+iowait), total


def system_stats(prev):
    stats = {"link": "ssh", "cpuPct": 0, "ramPct": 0, "cpuTempC": None, "uptimeS": 0}
    try:
        idle, total = read_cpu_times()
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
    except (OSError, KeyError, ValueError):
        pass  # hors Linux (mode --fake sur un autre OS) : valeurs par défaut
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            stats["cpuTempC"] = round(int(f.read()) / 1000, 1)
    except (OSError, ValueError):
        stats["cpuTempC"] = 0
    return stats


# ---------------------------------------------------------------- commandes (stdin)
def read_commands(motor):
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            motor.command(json.loads(line))
        except (ValueError, KeyError, TypeError) as err:
            log(f"commande ignorée ({line}) : {err}")
    stop_event.set()  # stdin fermé (connexion SSH coupée) : on arrête tout, moteur compris


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", type=float, default=1.0)
    ap.add_argument("--stream-url", default=None)
    ap.add_argument("--fake", action="store_true")
    args = ap.parse_args()

    motor, ultra, dht = Motor(args.fake), Ultrasonic(args.fake), Dht(args.fake)
    for target in (motor.run, dht.run):
        threading.Thread(target=target, daemon=True).start()
    threading.Thread(target=read_commands, args=(motor,), daemon=True).start()
    log(f"démarré (period={args.period}s, fake={args.fake}) — position moteur actuelle = 0°")

    cpu_prev = [None, 0]
    while not stop_event.is_set():
        loop_start = time.monotonic()
        snapshot = {
            "ts": int(time.time() * 1000),
            "ultrasonic": {"distanceCm": ultra.read(), "maxRangeCm": MAX_RANGE_CM},
            "thermal": None,
            "camera": {"streamUrl": args.stream_url, "width": 640, "height": 480, "fps": 15},
            "motor": motor.state(),
            "environment": dict(dht.last),
            "system": system_stats(cpu_prev),
        }
        print(json.dumps(snapshot), flush=True)
        stop_event.wait(max(0.0, args.period - (time.monotonic() - loop_start)))
    time.sleep(0.2)  # laisse le thread moteur couper les bobines


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_event.set()
