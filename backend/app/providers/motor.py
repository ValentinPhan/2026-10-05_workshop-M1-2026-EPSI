"""Validation des commandes moteur, partagée par tous les providers."""
import math
from typing import Any

MIN_ANGLE, MAX_ANGLE = -90, 90
MIN_SPEED, MAX_SPEED = 5, 90


def clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def apply_motor_command(motor: dict, cmd: Any) -> None:
    """Applique une commande à l'état moteur ; lève ValueError si elle est invalide.

    Commandes acceptées :
      {type: 'move',  angle: -90..90}     aller à un angle absolu
      {type: 'step',  delta: number}      déplacement relatif
      {type: 'sweep', enabled: bool}      balayage automatique
      {type: 'speed', value: 5..90}       vitesse en °/s
      {type: 'stop'}                      arrêt immédiat
    """
    kind = cmd.get("type") if isinstance(cmd, dict) else None
    if kind == "move":
        if not _is_num(cmd.get("angle")):
            raise ValueError("angle invalide")
        motor["mode"] = "manual"
        motor["target"] = clamp(cmd["angle"], MIN_ANGLE, MAX_ANGLE)
    elif kind == "step":
        if not _is_num(cmd.get("delta")):
            raise ValueError("delta invalide")
        motor["mode"] = "manual"
        motor["target"] = clamp(motor["target"] + cmd["delta"], MIN_ANGLE, MAX_ANGLE)
    elif kind == "sweep":
        enabled = bool(cmd.get("enabled"))
        motor["mode"] = "sweep" if enabled else "manual"
        if not enabled:
            motor["target"] = motor["angle"]
    elif kind == "speed":
        if not _is_num(cmd.get("value")):
            raise ValueError("vitesse invalide")
        motor["speed"] = clamp(cmd["value"], MIN_SPEED, MAX_SPEED)
    elif kind == "stop":
        motor["mode"] = "manual"
        motor["target"] = motor["angle"]
    else:
        raise ValueError(f"commande inconnue : {kind}")
