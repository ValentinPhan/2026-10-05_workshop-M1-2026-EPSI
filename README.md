# Sentinel-X — Dashboard (workshop M1 2026 EPSI)

Dashboard de supervision du boîtier Sentinel-X : API Python (FastAPI) et front React (Vite) avec Ant Design (thème sombre).
Pour l'instant les données du Raspberry Pi sont **simulées** (provider `mock`) et le modèle IA est **factice** (analyzer `mock`).

## Installation

```bash
# Front
npm install

# Back (Python 3.11+)
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows   (Linux/Mac : source .venv/bin/activate)
pip install -r requirements.txt
```

## Lancer

- **VS Code** : F5 sur « Sentinel-X (Back + Front) » — le front a son terminal dédié (tâche « Front (Vite) ») mais attend que l'API réponde sur :4000 avant de démarrer, le back tourne en debug Python (extension *Python Debugger*). Sans debug : tâche « Sentinel-X (Back + Front, sans debug) ».
- **Ligne de commande** (venv activé) : `npm run dev` — API sur :4000, dashboard sur http://localhost:5173.
  Séparément : `npm run api` (back) et `npm run dev -w client` (front).

Variables d'environnement du back : `PROVIDER` (`mock` | `ssh`), `ANALYZER` (`mock` | `local`), `TICK_MS`.
Les terminaux affichent en vert la connexion front ↔ back et en rouge la déconnexion.

## Architecture

```
Raspberry Pi ──(brut : caméra, ultrason, thermique, DHT22)──► API ──► front   (chemin rapide, chaque seconde)
      ▲                                                        │
      └──────────(ordres moteur)───────────────────────────────┤
                                                               └─► modèle IA local ──► API ──► front   (chemin lent, en différé)
```

- Le **Pi n'envoie que de la donnée brute** et reçoit des ordres moteur. Aucun calcul d'IA dessus.
- L'API diffuse les données brutes au front **sans attendre** le modèle (message WS `snapshot`).
- En parallèle elle envoie le snapshot au **modèle IA local**, dans le même process Python mais **dans un thread** : un modèle lent ne bloque ni l'API ni l'affichage. Son résultat (score de menace + détections caméra + anomalies d'environnement) repart vers le front plus tard (message WS `analysis`, avec `forTs` = snapshot analysé et `latencyMs`).
- Si le modèle est occupé, le snapshot est sauté (pas de file d'attente). S'il plante ou répond mal, le dashboard continue et affiche « IA hors ligne ».
- Alertes : proximité et pic thermique = seuils sur la donnée brute (immédiat) ; intrusion et anomalie d'environnement = dépendent du modèle IA.

### Qui fait quoi dans le dépôt

| Dossier | Rôle | Tourne où |
|---|---|---|
| `pi/` | scripts de lecture des capteurs (`dht22_reader.py`) | sur le **Raspberry** |
| `backend/` | API REST + WebSocket, alertes, providers, **intégration** du modèle IA | sur le **PC** |
| `ai/` | atelier de l'équipe IA : entraînement et expérimentation (`env_model.py`) | sur le **PC**, hors ligne |
| `client/` | dashboard React | navigateur |

Le modèle entraîné dans `ai/` se déploie en copiant son fichier dans `backend/models/`, puis en l'appelant depuis `LocalAnalyzer` (ci-dessous).

## Brancher le modèle IA (équipe IA)

Tout est dans `backend/app/ai/` ; les poids vont dans `backend/models/` (dossier vide pour l'instant).
Il suffit d'implémenter `LocalAnalyzer` dans [local_analyzer.py](backend/app/ai/local_analyzer.py) puis de lancer avec `ANALYZER=local`.
Le contrat (entrée : snapshot brut ; sortie : détections + score de menace + anomalies d'environnement) y est documenté. `analyze()` est synchrone et bloquante, c'est voulu.
Le faux modèle (`mock_analyzer.py`, `env_anomaly.py`) montre le format exact attendu.

## Modules du dashboard

| Module | Données |
|---|---|
| Caméra | flux (faux flux canvas en mock, webcam du PC via l'interrupteur, `camera.streamUrl` pour le vrai) + détections du modèle IA (masquées après 3 s) |
| Ultrason | distance, radar orienté selon l'angle du moteur, historique |
| Thermique | matrice 8×8, moyenne / max, historique |
| Environnement (DHT22) | température, humidité, point de rosée, score d'anomalie IA et ses raisons, historiques |
| Moteur | angle, cible, vitesse, mode ; commandes : position, pas, centrer, balayage auto, vitesse, stop |
| Score de menace | calculé par le modèle IA local, affiché en différé (mock : fusion caméra 45 % / ultrason 25 % / thermique 15 % / environnement 15 %) |
| Alertes | proximité (< 80 cm), pic thermique (> 45 °C), intrusion (modèle IA), anomalie d'environnement (score DHT22 ≥ 70) ; seuils dans `backend/app/config.py` |
| Raspberry Pi | CPU, RAM, température, uptime |

En mode mock, trois boutons du journal d'alertes déclenchent un intrus, un pic thermique ou une fenêtre ouverte pour la démo.

## API

- `GET /api/health`, `GET /api/snapshot` (brut), `GET /api/analysis` (dernier résultat IA), `GET /api/history` (`{sensors, threat}`), `GET /api/alerts`
- `POST /api/motor` — `{type:'move',angle}` · `{type:'step',delta}` · `{type:'sweep',enabled}` · `{type:'speed',value}` · `{type:'stop'}`
- `POST /api/mock/{scenario}` — `intruder` | `heat` | `window` (mock uniquement)
- WebSocket `/ws` — messages `hello`, `snapshot`, `analysis`, `alert`, `motor`
- Documentation interactive générée par FastAPI : http://localhost:4000/docs

Les clés JSON sont en camelCase (`distanceCm`, `maxC`…) : c'est le contrat avec le front.

## Brancher le vrai Raspberry Pi (SSH)

Tout passe par un *provider* (`backend/app/providers/`). Pour remplacer le mock, il suffit d'implémenter
[ssh.py](backend/app/providers/ssh.py) avec le même contrat que `mock.py` (`start`, `stop`, `get_snapshot`, `send_motor_command`)
et la même forme de snapshot — le moteur d'alertes, l'API, le modèle IA et le front n'ont pas à changer.
Le contrat et une piste d'implémentation (`asyncssh` + script Python côté Pi) sont documentés en tête de `ssh.py`.

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
  - `backend/app/ai/env_anomaly.py` : version en ligne (moyennes / variances glissantes + z-score), utilisée par l'analyseur mock.
    Elle apprend la normale de la pièce pendant ~1 min puis n'apprend plus des anomalies.
  - `ai/env_model.py` : **Isolation Forest** (scikit-learn) entraînée sur quelques jours de données normales, pour le vrai modèle.
    `pip install -r ai/requirements.txt` puis `python ai/env_model.py demo` (données synthétiques), `train dht22_log.csv`, `score dht22_log.csv`.
  - Sortie commune : `environment: {score 0..100, label, dewPointC, reasons[]}` dans le résultat de l'analyse.

## Structure

```
backend/
  app/main.py        routes REST + WebSocket
  app/hub.py         état, diffusion WS, chemins rapide / lent
  app/alerts.py      moteur d'alertes
  app/config.py      seuils et variables d'environnement
  app/providers/     mock.py · ssh.py · motor.py
  app/ai/            mock_analyzer.py · env_anomaly.py · local_analyzer.py (à implémenter)
  models/            poids du modèle IA déployé (vide)
client/src/          App.jsx · hooks/useSentinel.js · components/
pi/                  dht22_reader.py (lecture du capteur sur le Raspberry)
ai/                  env_model.py (Isolation Forest sur le DHT22) · requirements.txt
```
