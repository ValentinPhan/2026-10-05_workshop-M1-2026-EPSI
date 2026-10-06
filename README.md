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

## Architecture

```
Raspberry Pi ──(brut : caméra, ultrason, thermique)──► API ──► front   (chemin rapide, chaque seconde)
      ▲                                                 │
      └──────────(ordres moteur)────────────────────────┤
                                                        └─► modèle IA local ──► API ──► front   (chemin lent, en différé)
```

- Le **Pi n'envoie que de la donnée brute** et reçoit des ordres moteur. Aucun calcul d'IA dessus.
- L'API diffuse les données brutes au front **sans attendre** le modèle (message WS `snapshot`).
- En parallèle elle envoie le snapshot au **modèle IA local**, dans le même process Python mais **dans un thread** : un modèle lent ne bloque ni l'API ni l'affichage. Son résultat (score de menace + détections caméra) repart vers le front plus tard (message WS `analysis`, avec `forTs` = snapshot analysé et `latencyMs`).
- Si le modèle est occupé, le snapshot est sauté (pas de file d'attente). S'il plante ou répond mal, le dashboard continue et affiche « IA hors ligne ».
- Alertes : proximité et pic thermique = seuils sur la donnée brute (immédiat) ; intrusion = dépend du modèle IA.

## Brancher le modèle IA (équipe IA)

Tout est dans `backend/app/ai/` ; les poids vont dans `backend/models/` (dossier vide pour l'instant).
Il suffit d'implémenter `LocalAnalyzer` dans [local_analyzer.py](backend/app/ai/local_analyzer.py) puis de lancer avec `ANALYZER=local`.
Le contrat (entrée : snapshot brut ; sortie : détections + score de menace) y est documenté. `analyze()` est synchrone et bloquante, c'est voulu.

## Modules du dashboard

| Module | Données |
|---|---|
| Caméra | flux (faux flux canvas en mock, webcam du PC via l'interrupteur, `camera.streamUrl` pour le vrai) + détections du modèle IA (masquées après 3 s) |
| Ultrason | distance, radar orienté selon l'angle du moteur, historique |
| Thermique | matrice 8×8, moyenne / max, historique |
| Moteur | angle, cible, vitesse, mode ; commandes : position, pas, centrer, balayage auto, vitesse, stop |
| Score de menace | calculé par le modèle IA local, affiché en différé (mock : fusion caméra 50 % / ultrason 30 % / thermique 20 %) |
| Alertes | proximité (< 80 cm), pic thermique (> 45 °C), intrusion (modèle IA) ; seuils dans `backend/app/config.py` |
| Raspberry Pi | CPU, RAM, température, uptime |

En mode mock, deux boutons du journal d'alertes déclenchent un intrus ou un pic thermique pour la démo.

## API

- `GET /api/health`, `GET /api/snapshot` (brut), `GET /api/analysis` (dernier résultat IA), `GET /api/history` (`{sensors, threat}`), `GET /api/alerts`
- `POST /api/motor` — `{type:'move',angle}` · `{type:'step',delta}` · `{type:'sweep',enabled}` · `{type:'speed',value}` · `{type:'stop'}`
- `POST /api/mock/{scenario}` — `intruder` | `heat` (mock uniquement)
- WebSocket `/ws` — messages `hello`, `snapshot`, `analysis`, `alert`, `motor`
- Documentation interactive générée par FastAPI : http://localhost:4000/docs

Les clés JSON sont en camelCase (`distanceCm`, `maxC`…) : c'est le contrat avec le front.

## Brancher le vrai Raspberry Pi (SSH)

Tout passe par un *provider* (`backend/app/providers/`). Pour remplacer le mock, il suffit d'implémenter
[ssh.py](backend/app/providers/ssh.py) avec le même contrat que `mock.py` (`start`, `stop`, `get_snapshot`, `send_motor_command`)
et la même forme de snapshot — le moteur d'alertes, l'API, le modèle IA et le front n'ont pas à changer.
Le contrat et une piste d'implémentation (`asyncssh` + script Python côté Pi) sont documentés en tête de `ssh.py`.

## Structure

```
backend/
  app/main.py        routes REST + WebSocket
  app/hub.py         état, diffusion WS, chemins rapide / lent
  app/alerts.py      moteur d'alertes
  app/config.py      seuils et variables d'environnement
  app/providers/     mock.py · ssh.py · motor.py
  app/ai/            mock_analyzer.py · local_analyzer.py (à implémenter)
  models/            poids du modèle IA (vide)
client/src/          App.jsx · hooks/useSentinel.js · components/
```
