// Validation des commandes moteur, partagée par tous les providers.
export const MOTOR_LIMITS = { minAngle: -90, maxAngle: 90, minSpeed: 5, maxSpeed: 90 };

export const clamp = (v, min, max) => Math.min(max, Math.max(min, v));

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

// Commandes acceptées :
//   { type: 'move',  angle: -90..90 }     aller à un angle absolu
//   { type: 'step',  delta: number }      déplacement relatif
//   { type: 'sweep', enabled: boolean }   balayage automatique
//   { type: 'speed', value: 5..90 }       vitesse en °/s
//   { type: 'stop' }                      arrêt immédiat
export function applyMotorCommand(motor, cmd) {
  const { minAngle, maxAngle, minSpeed, maxSpeed } = MOTOR_LIMITS;
  switch (cmd?.type) {
    case 'move':
      if (!isNum(cmd.angle)) throw new Error('angle invalide');
      motor.mode = 'manual';
      motor.target = clamp(cmd.angle, minAngle, maxAngle);
      break;
    case 'step':
      if (!isNum(cmd.delta)) throw new Error('delta invalide');
      motor.mode = 'manual';
      motor.target = clamp(motor.target + cmd.delta, minAngle, maxAngle);
      break;
    case 'sweep':
      motor.mode = cmd.enabled ? 'sweep' : 'manual';
      if (!cmd.enabled) motor.target = motor.angle;
      break;
    case 'speed':
      if (!isNum(cmd.value)) throw new Error('vitesse invalide');
      motor.speed = clamp(cmd.value, minSpeed, maxSpeed);
      break;
    case 'stop':
      motor.mode = 'manual';
      motor.target = motor.angle;
      break;
    default:
      throw new Error(`commande inconnue : ${cmd?.type}`);
  }
}
