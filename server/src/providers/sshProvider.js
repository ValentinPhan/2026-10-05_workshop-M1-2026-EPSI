// Provider réel : communication SSH avec le Raspberry Pi. PAS ENCORE IMPLÉMENTÉ.
//
// Il doit respecter exactement le même contrat que mockProvider.js :
//   name                      : string
//   start(onSnapshot)         : lance la collecte, appelle onSnapshot(snapshot) à chaque tick
//   stop()                    : arrête la collecte et ferme la connexion
//   getSnapshot()             : dernier snapshot connu
//   sendMotorCommand(cmd)     : envoie la commande au Pi (voir motor.js), retourne l'état moteur
//
// Forme du snapshot (identique au mock) :
//   { ts, ultrasonic:{distanceCm,maxRangeCm}, thermal:{avgC,maxC,grid[8][8]},
//     camera:{streamUrl,width,height,fps}, motor:{angle,target,speed,mode,moving},
//     environment:{tempC,humidityPct,readAt},   // DHT22 (readAt = ts de la dernière lecture réussie)
//     system:{link,cpuPct,ramPct,cpuTempC,uptimeS} }
//
// Le Pi n'envoie que de la donnée BRUTE (pas de détection, pas de score) et reçoit des ordres
// moteur : l'analyse est faite par le modèle IA local (voir server/src/ai/).
//
// Piste d'implémentation : lib `ssh2`, une connexion persistante, un script Python côté Pi
// qui imprime un JSON par ligne sur stdout (lu en streaming), et les commandes moteur
// envoyées sur son stdin. Lecture du DHT22 côté Pi : voir pi/dht22_reader.py. Valider les commandes avec applyMotorCommand avant envoi.
export function createSshProvider(_options) {
  throw new Error('Provider SSH non implémenté : lancer avec PROVIDER=mock');
}
