"""Provider fictif : simule le Raspberry Pi (caméra, ultrason, thermique, DHT22, moteur).

Même contrat que ssh.py — voir providers/__init__.py. Le Pi n'envoie que de la donnée
BRUTE : les détections et le score de menace sont calculés par le modèle IA local.
"""
import asyncio
import math
import random
import time
from typing import Awaitable, Callable

from ..clock import now_ms
from .motor import apply_motor_command, clamp

GRID = 8  # matrice thermique 8x8 (type AMG8833)
MAX_RANGE_CM = 400
WALL_CM = 300
DHT_PERIOD_S = 2  # le DHT22 ne fournit qu'une mesure toutes les 2 s
DHT_TAU_S = 20  # inertie du capteur (constante de temps)
DHT_FAIL_RATE = 0.03  # lectures ratées (checksum / timeout), fréquentes sous Linux

OnSnapshot = Callable[[dict], Awaitable[None]]


def _noise(amp: float) -> float:
    return (random.random() - 0.5) * 2 * amp


class MockProvider:
    name = "mock"

    def __init__(self, tick_ms: int):
        self._tick = tick_ms / 1000
        self._started_at = time.time()
        self._task: asyncio.Task | None = None
        self._t = 0.0

        # Intrus simulé : phase "idle" -> "approach" -> "stay" -> "leave" -> "idle"
        self._intruder = {"phase": "idle", "distance": WALL_CM, "x": 0.5, "time_left": random.uniform(15, 30)}
        # Pic thermique simulé (ex. surchauffe d'un équipement)
        self._heat = {"remaining": 0.0, "boost": 0.0}
        # Fenêtre ouverte simulée : air extérieur plus froid et plus humide
        self._window = {"remaining": 0.0, "mix": 0.0}
        # État interne du DHT22 (valeur "vue" par le capteur, en retard sur l'air réel)
        self._dht = {"tempC": 23.0, "humidityPct": 48.0, "next_read_in": 0.0, "last": None}

        self._motor = {"angle": 0.0, "target": 0.0, "speed": 40, "mode": "manual", "moving": False}
        self._sweep_dir = 1

    # ---- simulation ----
    def _step_intruder(self, dt: float) -> None:
        i = self._intruder
        i["time_left"] -= dt
        if i["phase"] == "idle":
            i["distance"] = WALL_CM + _noise(3)
            if i["time_left"] <= 0:
                self._start_intruder()
        elif i["phase"] == "approach":
            i["distance"] = max(45, i["distance"] - 28 * dt)
            i["x"] = clamp(i["x"] + _noise(0.03), 0.15, 0.85)
            if i["distance"] <= 60:
                i["phase"] = "stay"
                i["time_left"] = random.uniform(5, 10)
        elif i["phase"] == "stay":
            i["distance"] = 55 + _noise(6)
            i["x"] = clamp(i["x"] + _noise(0.02), 0.15, 0.85)
            if i["time_left"] <= 0:
                i["phase"] = "leave"
        elif i["phase"] == "leave":
            i["distance"] += 40 * dt
            if i["distance"] >= WALL_CM:
                i["phase"] = "idle"
                i["time_left"] = random.uniform(20, 40)

    def _start_intruder(self) -> None:
        i = self._intruder
        if i["phase"] != "idle":
            return
        i["phase"] = "approach"
        i["distance"] = 260
        i["x"] = random.uniform(0.3, 0.7)

    def _step_motor(self, dt: float) -> None:
        m = self._motor
        if m["mode"] == "sweep":
            m["target"] = self._sweep_dir * 60
            if abs(m["angle"] - m["target"]) < 1:
                self._sweep_dir *= -1
        diff = m["target"] - m["angle"]
        max_step = m["speed"] * dt
        m["moving"] = abs(diff) > 0.5
        m["angle"] = m["target"] if abs(diff) <= max_step else m["angle"] + math.copysign(max_step, diff)

    def _room_temp_c(self) -> float:
        """Température de l'air de la pièce : dérive lente (cycle de 1 h environ)."""
        return 23 + 1.2 * math.sin(self._t / 600)

    def _step_dht(self, dt: float) -> None:
        w, d, heat = self._window, self._dht, self._heat
        w["mix"] = clamp(w["mix"] + (0.05 if w["remaining"] > 0 else -0.02) * dt, 0, 1)
        present = self._intruder["phase"] not in ("idle", "leave")
        # air réel : pièce + chaleur de l'équipement en surchauffe + air extérieur (fenêtre)
        air_t = self._room_temp_c() + heat["boost"] * 0.2 - 6 * w["mix"]
        base_rh = 48 + 2 * math.sin(self._t / 900) + (2 if present else 0)
        # l'air chauffé s'assèche (~ -3 % HR / °C), l'air extérieur est humide
        air_rh = clamp(base_rh - heat["boost"] * 0.6 + 25 * w["mix"], 5, 99)
        k = 1 - math.exp(-dt / DHT_TAU_S)
        d["tempC"] += (air_t - d["tempC"]) * k
        d["humidityPct"] += (air_rh - d["humidityPct"]) * k

        d["next_read_in"] -= dt
        if d["next_read_in"] > 0:
            return
        d["next_read_in"] = DHT_PERIOD_S
        if d["last"] and random.random() < DHT_FAIL_RATE:
            return  # lecture ratée : on garde l'ancienne
        d["last"] = {
            "tempC": round(d["tempC"] + _noise(0.1), 1),
            "humidityPct": round(clamp(d["humidityPct"] + _noise(0.3), 0, 100), 1),
            "readAt": now_ms(),
        }

    # ---- construction du snapshot brut ----
    def _build_thermal(self) -> dict:
        i, heat = self._intruder, self._heat
        ambient = self._room_temp_c() + 1 - 5 * self._window["mix"]  # les surfaces vues refroidissent aussi
        if heat["remaining"] > 0:
            heat["boost"] = min(heat["boost"] + 1.5, 30)
        else:
            heat["boost"] = max(heat["boost"] - 1, 0)
        present = clamp((WALL_CM - i["distance"]) / 250, 0, 1) if i["phase"] != "idle" else 0
        cx, cy = i["x"] * (GRID - 1), 4
        grid = []
        for r in range(GRID):
            row = []
            for c in range(GRID):
                body = present * 12 * math.exp(-((c - cx) ** 2 + (r - cy) ** 2) / 5)
                hot = heat["boost"] * math.exp(-((c - 1) ** 2 + (r - 1) ** 2) / 3)
                row.append(round(ambient + body + hot + _noise(0.3), 1))
            grid.append(row)
        flat = [v for row in grid for v in row]
        return {"avgC": round(sum(flat) / len(flat), 1), "maxC": max(flat), "grid": grid}

    def _build_camera(self) -> dict:
        return {"streamUrl": None, "width": 640, "height": 480, "fps": 15 + round(_noise(1))}

    def _build_system(self) -> dict:
        busy = self._intruder["phase"] != "idle"
        return {
            "link": "mock",
            "cpuPct": round(clamp(22 + (35 if busy else 0) + _noise(5), 3, 100)),
            "ramPct": round(clamp(41 + _noise(1.5), 0, 100)),
            "cpuTempC": round(48 + (8 if busy else 0) + _noise(1), 1),
            "uptimeS": int(time.time() - self._started_at),
        }

    def get_snapshot(self) -> dict:
        return {
            "ts": now_ms(),
            "ultrasonic": {
                "distanceCm": round(clamp(self._intruder["distance"] + _noise(1.5), 2, MAX_RANGE_CM), 1),
                "maxRangeCm": MAX_RANGE_CM,
            },
            "thermal": self._build_thermal(),
            "camera": self._build_camera(),
            "motor": {**self._motor, "angle": round(self._motor["angle"], 1)},
            "environment": dict(self._dht["last"] or {}),
            "system": self._build_system(),
        }

    # ---- contrat provider ----
    async def start(self, on_snapshot: OnSnapshot) -> None:
        self._task = asyncio.create_task(self._run(on_snapshot))

    async def _run(self, on_snapshot: OnSnapshot) -> None:
        self._step_dht(0)  # première mesure DHT22 dès le départ
        await on_snapshot(self.get_snapshot())  # pas d'écran vide au premier chargement
        while True:
            await asyncio.sleep(self._tick)
            self._t += self._tick
            self._heat["remaining"] = max(0.0, self._heat["remaining"] - self._tick)
            self._window["remaining"] = max(0.0, self._window["remaining"] - self._tick)
            self._step_intruder(self._tick)
            self._step_motor(self._tick)
            self._step_dht(self._tick)
            await on_snapshot(self.get_snapshot())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def send_motor_command(self, cmd: dict) -> dict:
        """Retourne l'état moteur mis à jour ; lève ValueError si la commande est invalide."""
        apply_motor_command(self._motor, cmd)
        return {**self._motor}

    def trigger_scenario(self, name: str) -> None:
        """Déclenche un scénario de démo à la demande (boutons "simuler" du dashboard)."""
        if name == "intruder":
            self._intruder["time_left"] = 0
            self._start_intruder()
        elif name == "heat":
            self._heat["remaining"] = 12
        elif name == "window":
            self._window["remaining"] = 40
        else:
            raise ValueError(f"Scénario inconnu : {name}")
