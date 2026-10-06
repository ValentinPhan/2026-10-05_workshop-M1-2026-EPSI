"""Provider réel : communication SSH avec le Raspberry Pi. PAS ENCORE IMPLÉMENTÉ.

Il doit respecter exactement le même contrat que MockProvider :
  name                              : str
  async start(on_snapshot)          : lance la collecte, `await on_snapshot(snapshot)` à chaque tick
  async stop()                      : arrête la collecte et ferme la connexion
  get_snapshot()                    : dernier snapshot connu
  async send_motor_command(cmd)     : envoie la commande au Pi (voir motor.py), retourne l'état moteur

Forme du snapshot (identique au mock, clés en camelCase = contrat avec le front) :
  { ts, ultrasonic:{distanceCm,maxRangeCm}, thermal:{avgC,maxC,grid[8][8]},
    camera:{streamUrl,width,height,fps}, motor:{angle,target,speed,mode,moving},
    environment:{tempC,humidityPct,readAt},   # DHT22 (readAt = ts de la dernière lecture réussie)
    system:{link,cpuPct,ramPct,cpuTempC,uptimeS} }

Le Pi n'envoie que de la donnée BRUTE (pas de détection, pas de score) et reçoit des ordres
moteur : l'analyse est faite par le modèle IA local (voir app/ai/).

Piste d'implémentation : `asyncssh`, une connexion persistante, un script Python côté Pi qui
imprime un JSON par ligne sur stdout (lu en streaming) ; les commandes moteur sont envoyées sur
son stdin après validation par apply_motor_command. Lecture du DHT22 côté Pi : pi/dht22_reader.py
(une ligne JSON {tempC, humidityPct, readAt} par mesure = le champ `environment` du snapshot).
"""
from ..config import SshConfig


def create_ssh_provider(_options: SshConfig):
    raise NotImplementedError("Provider SSH non implémenté : lancer avec PROVIDER=mock")
