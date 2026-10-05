# Sentinel-X — Dashboard (workshop M1 2026 EPSI)

Dashboard de supervision du boîtier Sentinel-X : API Node.js (Express + WebSocket) et front React (Vite) avec Ant Design (thème sombre).
Pour l'instant les données du Raspberry Pi sont **simulées** (provider `mock`).

## Lancer

```bash
npm install
npm run dev        # API sur :4000, dashboard sur http://localhost:5173
```

Variables d'environnement utiles (serveur) : `PORT`, `PROVIDER` (`mock` | `ssh`), `TICK_MS`.

## Architecture

```
Raspberry Pi ──(brut : caméra, ultrason, thermique)──► API ──► front   (chemin rapide, chaque seconde)
      ▲                                                 │
      └──────────(ordres moteur)────────────────────────┤
                                                        └─► modèle IA local ──► API ──► front   (chemin lent, en différé)
```

- Le **Pi n'envoie que de la donnée brute** et reçoit des ordres moteur. Aucun calcul d'IA dessus.
- L'API diffuse les données brutes au front **sans attendre** le modèle (message WS `snapshot`).
- En parallèle elle envoie le snapshot au **modèle IA local** (`server/src/ai/`). Son résultat (score de menace + détections caméra) repart vers le front plus tard (message WS `analysis`, avec `forTs` = snapshot analysé et `latencyMs`).
- Si le modèle est occupé, le snapshot est sauté (pas de file d'attente). S'il est injoignable, le dashboard continue et affiche « IA hors ligne ».
- Alertes : proximité et pic thermique = seuils sur la donnée brute (immédiat) ; intrusion = dépend du modèle IA.

Variables : `ANALYZER` (`mock` = heuristique avec latence simulée | `http` = service Python), `AI_URL` (défaut `http://localhost:8000`), `AI_TIMEOUT_MS`.
Contrat du modèle (`POST {AI_URL}/analyze`) documenté dans `server/src/ai/httpAnalyzer.js`.

## Modules du dashboard

| Module | Données |
|---|---|
| Caméra | flux (faux flux canvas en mock, webcam du PC via l'interrupteur, `camera.streamUrl` pour le vrai) + détections du modèle IA (masquées après 3 s) |
| Ultrason | distance, radar orienté selon l'angle du moteur, historique |
| Thermique | matrice 8×8, moyenne / max, historique |
| Moteur | angle, cible, vitesse, mode ; commandes : position, pas, centrer, balayage auto, vitesse, stop |
| Score de menace | calculé par le modèle IA local, affiché en différé (mock : fusion caméra 50 % / ultrason 30 % / thermique 20 %) |
| Alertes | proximité (< 80 cm), pic thermique (> 45 °C), intrusion (modèle IA) ; seuils dans `server/src/config.js` |
| Raspberry Pi | CPU, RAM, température, uptime |

En mode mock, deux boutons du journal d'alertes déclenchent un intrus ou un pic thermique pour la démo.

## API

- `GET /api/health`, `GET /api/snapshot` (brut), `GET /api/analysis` (dernier résultat IA), `GET /api/history` (`{sensors, threat}`), `GET /api/alerts`
- `POST /api/motor` — `{type:'move',angle}` · `{type:'step',delta}` · `{type:'sweep',enabled}` · `{type:'speed',value}` · `{type:'stop'}`
- `POST /api/mock/:scenario` — `intruder` | `heat` (mock uniquement)
- WebSocket `/ws` — messages `hello`, `snapshot`, `analysis`, `alert`, `motor`

## Brancher le vrai Raspberry Pi (SSH)

Tout passe par un *provider* (`server/src/providers/`). Pour remplacer le mock, il suffit d'implémenter
`sshProvider.js` avec le même contrat que `mockProvider.js` (`start`, `stop`, `getSnapshot`, `sendMotorCommand`)
et la même forme de snapshot — le moteur d'alertes, l'API et le front n'ont pas à changer.
Le contrat et une piste d'implémentation (`ssh2` + script Python côté Pi) sont documentés en tête de `sshProvider.js`.

## Structure

```
server/src/  index.js (API + WS) · alerts.js · config.js · providers/ (mock, ssh, motor) · ai/ (mock, http)
client/src/  App.jsx · hooks/useSentinel.js · components/
```
