# Sentinel-X — Dashboard (workshop M1 2026 EPSI)

Dashboard de supervision du boîtier Sentinel-X : API Node.js (Express + WebSocket) et front React (Vite) avec Ant Design (thème sombre).
Par défaut les données du Raspberry Pi sont **simulées** (provider `mock`) ; `PROVIDER=ssh` branche le vrai Pi.

## Lancer

```bash
npm install
npm run dev        # API sur :4000, dashboard sur http://localhost:5173
```

Variables d'environnement utiles (serveur) : `PORT`, `PROVIDER` (`mock` | `ssh`), `TICK_MS`.

## Architecture

```
Raspberry Pi ──(brut : caméra, ultrason, thermique, DHT22)──► API ──► front   (chemin rapide, chaque seconde)
      ▲                                                 │
      └──────────(ordres moteur)────────────────────────┤
                                                        └─► modèle IA local ──► API ──► front   (chemin lent, en différé)
```

- Le **Pi n'envoie que de la donnée brute** et reçoit des ordres moteur. Aucun calcul d'IA dessus.
- L'API diffuse les données brutes au front **sans attendre** le modèle (message WS `snapshot`).
- En parallèle elle envoie le snapshot au **modèle IA local** (`server/src/ai/`). Son résultat (score de menace + détections caméra) repart vers le front plus tard (message WS `analysis`, avec `forTs` = snapshot analysé et `latencyMs`).
- Si le modèle est occupé, le snapshot est sauté (pas de file d'attente). S'il est injoignable, le dashboard continue et affiche « IA hors ligne ».
- Alertes : proximité et pic thermique = seuils sur la donnée brute (immédiat) ; intrusion et anomalie d'environnement = dépendent du modèle IA.

Variables : `ANALYZER` (`mock` = heuristique avec latence simulée | `http` = service Python), `AI_URL` (défaut `http://localhost:8000`), `AI_TIMEOUT_MS`.
Contrat du modèle (`POST {AI_URL}/analyze`) documenté dans `server/src/ai/httpAnalyzer.js`.

## Modules du dashboard

| Module | Données |
|---|---|
| Caméra | flux (faux flux canvas en mock, webcam du PC via l'interrupteur, `camera.streamUrl` pour le vrai) + détections du modèle IA (masquées après 3 s) |
| Ultrason | distance, radar orienté selon l'angle du moteur, historique |
| Thermique | matrice 8×8, moyenne / max, historique |
| Environnement (DHT22) | température, humidité, point de rosée, score d'anomalie IA et ses raisons, historiques |
| Moteur | angle, cible, vitesse, mode ; commandes : position, pas, centrer, balayage auto, vitesse, stop |
| Score de menace | calculé par le modèle IA local, affiché en différé (mock : fusion caméra 45 % / ultrason 25 % / thermique 15 % / environnement 15 %) |
| Alertes | proximité (< 80 cm), pic thermique (> 45 °C), intrusion (modèle IA), anomalie d'environnement (score DHT22 ≥ 70) ; seuils dans `server/src/config.js` |
| Raspberry Pi | CPU, RAM, température, uptime |

En mode mock, trois boutons du journal d'alertes déclenchent un intrus, un pic thermique ou une fenêtre ouverte pour la démo.

## API

- `GET /api/health`, `GET /api/snapshot` (brut), `GET /api/analysis` (dernier résultat IA), `GET /api/history` (`{sensors, threat}`), `GET /api/alerts`
- `POST /api/motor` — `{type:'move',angle}` · `{type:'step',delta}` · `{type:'sweep',enabled}` · `{type:'speed',value}` · `{type:'stop'}`
- `POST /api/mock/:scenario` — `intruder` | `heat` | `window` (mock uniquement)
- WebSocket `/ws` — messages `hello`, `snapshot`, `analysis`, `alert`, `motor`

## Brancher le vrai Raspberry Pi (SSH)

`PROVIDER=ssh` : le serveur se connecte au Pi (`ssh2`) et y lance `pi/sentinel_agent.py`, qui envoie un snapshot JSON par ligne
et reçoit les commandes moteur sur son entrée standard. Montage, câblage et mise en service pas à pas : **[pi/README.md](pi/README.md)**.

Variables : `SSH_HOST`, `SSH_PORT`, `SSH_USER`, `SSH_KEY` (ou `SSH_PASSWORD`), `AGENT_COMMAND` (défaut `python3 ~/sentinel-x/pi/sentinel_agent.py`),
`CAMERA=0` (désactive le flux vidéo), `STREAM_PORT` (défaut 8080), `STREAM_URL` (remplace l'adresse du flux déduite de `SSH_HOST`), `AGENT_LOCAL=1` (agent simulé sur le PC, sans Raspberry).
Le module thermique est **optionnel** : sans matrice AMG8833, `thermal` vaut `null`, le panneau et l'alerte de pic thermique sont désactivés.

## Capteur DHT22 (température / humidité)

Module 3 broches « V182 » : capteur **DHT22 / AM2302** (−40 à 80 °C ±0,5 °C, 0 à 100 % HR ±2 à 5 %,
**une mesure toutes les 2 s au maximum**, protocole fil unique propriétaire — pas du 1-Wire). Résistance de tirage déjà sur le module.

- **Câblage** : `+` → 3,3 V (broche 1, surtout pas 5 V), `out` → GPIO4 (broche 7), `−` → GND (broche 6).
- **Lecture côté Pi** : `pi/dht22_reader.py` (pilote noyau `dtoverlay=dht11,gpiopin=4`, repli Adafruit) → une ligne JSON par mesure,
  `{tempC, humidityPct, readAt}` = champ `environment` du snapshot. `--csv dht22_log.csv` journalise les données d'entraînement.
- **Ce que l'IA en fait** :
  - température ambiante fiable pour la matrice thermique (remplace la médiane de la grille, faussée quand une personne remplit le champ) ;
  - détection d'anomalies d'environnement (surchauffe / départ de feu, fenêtre ou porte ouverte, condensation), ajoutée au score de menace.
- **Algorithme** : détection d'anomalies **non supervisée** sur des variables dérivées (température, humidité, point de rosée,
  pentes sur 1 / 5 / 15 min, heure de la journée) + garde-fous déterministes (> 45 °C, montée > 2 °C/min, air proche de la saturation).
  - `server/src/ai/envAnomaly.js` : version en ligne (moyennes / variances glissantes + z-score), utilisée par l'analyseur mock.
    Elle apprend la normale de la pièce pendant ~1 min puis n'apprend plus des anomalies.
  - `ai/env_model.py` : **Isolation Forest** (scikit-learn) entraînée sur quelques jours de données normales, pour le service IA Python.
    `pip install -r ai/requirements.txt` puis `python3 ai/env_model.py demo` (données synthétiques), `train dht22_log.csv`, `score dht22_log.csv`.
  - Sortie commune : `environment: {score 0..100, label, dewPointC, reasons[]}` dans la réponse de `/analyze`.

## Structure

```
server/src/  index.js (API + WS) · alerts.js · config.js · providers/ (mock, ssh, motor) · ai/ (mock, http, envAnomaly)
client/src/  App.jsx · hooks/useSentinel.js · components/
pi/          sentinel_agent.py (agent sur le Raspberry : ultrason, moteur, DHT22, système) · camera_stream.py (flux MJPEG) · dht22_reader.py · README.md (montage)
arduino/     sentinel_io (firmware Uno de test : ultrason + moteur, liaison série)
ai/          env_model.py (Isolation Forest sur le DHT22, pour le service IA Python)
```
