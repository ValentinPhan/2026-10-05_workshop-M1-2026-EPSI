// Provider fictif : simule le Raspberry Pi (caméra, ultrason, thermique, moteur).
// Même contrat que sshProvider.js — voir providers/index.js.
import { applyMotorCommand, clamp } from './motor.js';

const GRID = 8; // matrice thermique 8x8 (type AMG8833)
const MAX_RANGE_CM = 400;
const WALL_CM = 300;

const rand = (min, max) => min + Math.random() * (max - min);
const noise = (amp) => (Math.random() - 0.5) * 2 * amp;

export function createMockProvider({ tickMs }) {
  const startedAt = Date.now();
  let timer = null;
  let t = 0;

  // Intrus simulé : phase "idle" -> "approach" -> "stay" -> "leave" -> "idle"
  const intruder = { phase: 'idle', distance: WALL_CM, x: 0.5, timeLeft: rand(15, 30) };
  // Pic thermique simulé (ex. surchauffe d'un équipement)
  const heat = { remaining: 0, boost: 0 };

  const motor = { angle: 0, target: 0, speed: 40, mode: 'manual', moving: false };
  let sweepDir = 1;

  function stepIntruder(dt) {
    intruder.timeLeft -= dt;
    switch (intruder.phase) {
      case 'idle':
        intruder.distance = WALL_CM + noise(3);
        if (intruder.timeLeft <= 0) startIntruder();
        break;
      case 'approach':
        intruder.distance = Math.max(45, intruder.distance - 28 * dt);
        intruder.x = clamp(intruder.x + noise(0.03), 0.15, 0.85);
        if (intruder.distance <= 60) {
          intruder.phase = 'stay';
          intruder.timeLeft = rand(5, 10);
        }
        break;
      case 'stay':
        intruder.distance = 55 + noise(6);
        intruder.x = clamp(intruder.x + noise(0.02), 0.15, 0.85);
        if (intruder.timeLeft <= 0) intruder.phase = 'leave';
        break;
      case 'leave':
        intruder.distance += 40 * dt;
        if (intruder.distance >= WALL_CM) {
          intruder.phase = 'idle';
          intruder.timeLeft = rand(20, 40);
        }
        break;
    }
  }

  function startIntruder() {
    if (intruder.phase !== 'idle') return;
    intruder.phase = 'approach';
    intruder.distance = 260;
    intruder.x = rand(0.3, 0.7);
  }

  function stepMotor(dt) {
    if (motor.mode === 'sweep') {
      motor.target = sweepDir * 60;
      if (Math.abs(motor.angle - motor.target) < 1) sweepDir *= -1;
    }
    const diff = motor.target - motor.angle;
    const maxStep = motor.speed * dt;
    motor.moving = Math.abs(diff) > 0.5;
    motor.angle = Math.abs(diff) <= maxStep ? motor.target : motor.angle + Math.sign(diff) * maxStep;
  }

  function buildThermal() {
    const ambient = 24 + 1.5 * Math.sin(t / 60);
    if (heat.remaining > 0) heat.boost = Math.min(heat.boost + 1.5, 30);
    else heat.boost = Math.max(heat.boost - 1, 0);
    const present = intruder.phase !== 'idle' ? clamp((WALL_CM - intruder.distance) / 250, 0, 1) : 0;
    const cx = intruder.x * (GRID - 1);
    const cy = 4;
    let sum = 0;
    let max = -Infinity;
    const grid = Array.from({ length: GRID }, (_, r) =>
      Array.from({ length: GRID }, (_, c) => {
        const d2 = (c - cx) ** 2 + (r - cy) ** 2;
        const body = present * 12 * Math.exp(-d2 / 5);
        const hot = heat.boost * Math.exp(-((c - 1) ** 2 + (r - 1) ** 2) / 3);
        const v = ambient + body + hot + noise(0.3);
        sum += v;
        max = Math.max(max, v);
        return Number(v.toFixed(1));
      }),
    );
    return { avgC: Number((sum / (GRID * GRID)).toFixed(1)), maxC: Number(max.toFixed(1)), grid };
  }

  // Le Pi n'envoie que le flux : les détections sont calculées par le modèle IA local.
  function buildCamera() {
    return { streamUrl: null, width: 640, height: 480, fps: 15 + Math.round(noise(1)) };
  }

  function buildSystem() {
    return {
      link: 'mock',
      cpuPct: Number(clamp(22 + (intruder.phase !== 'idle' ? 35 : 0) + noise(5), 3, 100).toFixed(0)),
      ramPct: Number(clamp(41 + noise(1.5), 0, 100).toFixed(0)),
      cpuTempC: Number((48 + (intruder.phase !== 'idle' ? 8 : 0) + noise(1)).toFixed(1)),
      uptimeS: Math.floor((Date.now() - startedAt) / 1000),
    };
  }

  function getSnapshot() {
    return {
      ts: Date.now(),
      ultrasonic: { distanceCm: Number(clamp(intruder.distance + noise(1.5), 2, MAX_RANGE_CM).toFixed(1)), maxRangeCm: MAX_RANGE_CM },
      thermal: buildThermal(),
      camera: buildCamera(),
      motor: { ...motor, angle: Number(motor.angle.toFixed(1)) },
      system: buildSystem(),
    };
  }

  return {
    name: 'mock',

    start(onSnapshot) {
      const dt = tickMs / 1000;
      onSnapshot(getSnapshot()); // pas d'écran vide au premier chargement
      timer = setInterval(() => {
        t += dt;
        heat.remaining = Math.max(0, heat.remaining - dt);
        stepIntruder(dt);
        stepMotor(dt);
        onSnapshot(getSnapshot());
      }, tickMs);
    },

    stop() {
      clearInterval(timer);
    },

    getSnapshot,

    // Retourne l'état moteur mis à jour ; lève une Error si la commande est invalide.
    async sendMotorCommand(cmd) {
      applyMotorCommand(motor, cmd);
      return { ...motor };
    },

    // Déclenche un scénario de démo à la demande (bouton "simuler" du dashboard).
    triggerScenario(name) {
      if (name === 'intruder') {
        intruder.timeLeft = 0;
        startIntruder();
      } else if (name === 'heat') {
        heat.remaining = 12;
      } else {
        throw new Error(`Scénario inconnu : ${name}`);
      }
    },
  };
}
