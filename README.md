# Sentinel-X — Dashboard (workshop M1 2026 EPSI)

Dashboard de supervision du boîtier Sentinel-X : API Python (FastAPI) et front React (Vite) avec Ant Design (thème sombre).
Le backend porte aussi la **vision temps réel** : caméra + YOLOv8 tournent dans le même process, la vidéo annotée et les
alertes d'intrusion (avec photo) arrivent au dashboard par WebSocket.

Deux modes, selon la variable `ANALYZER` :

| Mode | Capteurs du Pi | Caméra / détection | Score de menace |
|---|---|---|---|
| `ANALYZER=mock` (défaut) | simulés (`PROVIDER=mock`) | faux flux + faux détecteur | heuristique factice |
| `ANALYZER=local` | simulés pour l'instant, SSH à venir | **vraie caméra + YOLOv8** | fusion des capteurs avec les détections YOLO |

## Matériel (liste finale)

| Composant | Rôle |
|---|---|
| Raspberry Pi 3 | unité centrale du boîtier : lit les capteurs, pilote le moteur |
| Caméra Raspberry Pi (v1) | flux vidéo pour la détection YOLO |
| Micro-servomoteur SG90 | oriente le capteur ultrason (radar) |
| Capteur température / humidité DHT22 | données d'environnement (module « V182 », 3 broches) |
| Capteur ultrason | mesure de distance (alerte de proximité) |

## Structure du dépôt

```
backend/            API FastAPI + vision YOLO  (tourne sur le PC)
  app/
    main.py         routes REST + WebSocket (/ws, /ws/video)
    hub.py          état, diffusion WebSocket, chemins rapide / lent / vidéo
    alerts.py       moteur d'alertes
    config.py       seuils et variables d'environnement
    providers/      sources de données du Pi : mock.py · ssh.py (à implémenter) · motor.py
    vision/         caméra + YOLO dans un thread dédié : service.py · detector.py
    ai/             analyse : mock_analyzer.py · local_analyzer.py · threat.py · env_anomaly.py
  models/           poids des modèles (yolov8n.pt, yolo26n.pt)
  data/captures/    photos d'intrusion (générées, non versionnées)
frontend/           dashboard React / Vite / Ant Design  (navigateur)
raspberry-pi/       scripts qui tournent sur le Raspberry (lecture du DHT22)
ml/                 atelier de l'équipe IA, hors ligne : vision/ (tests YOLO) · environment/ (Isolation Forest DHT22)
.vscode/            F5 : lance back + front
```

## Installation

```bash
# Front
npm install

# Back (Python 3.11+)
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows   (Linux/Mac : source .venv/bin/activate)
pip install -r requirements.txt

# Vision YOLO (optionnel, nécessaire pour ANALYZER=local — installe aussi torch, ~1 Go)
pip install -r requirements-vision.txt
```

## Lancer

- **VS Code** (F5) : trois configurations, **choisissez-la dans la liste de « Exécuter et déboguer »** (la dernière utilisée est retenue).
  - « **Sentinel-X + YOLO (webcam navigateur)** » (par défaut) : la webcam est ouverte par le navigateur, ses images sont envoyées au backend, YOLO les traite et React dessine les carrés rouges. Le backend n'ouvre aucune caméra. Le navigateur demande l'autorisation de la caméra au chargement.
  - « Sentinel-X (mock, sans YOLO) » : données simulées, faux flux caméra, **aucune détection**.
  - « Sentinel-X + YOLO (caméra du backend) » : YOLO sur la caméra de la machine du backend ou sur le flux du Pi (pour plus tard).

  Les configurations YOLO utilisent le modèle de segmentation `yolov8n-seg.pt` (silhouettes), téléchargé automatiquement dans `backend/models/` au premier lancement. Le debug Python utilise toujours `backend/.venv`.

  Le front a son terminal dédié (tâche « Front (Vite) ») et attend que l'API réponde sur :4000 avant de démarrer ; le back tourne en debug Python (extension *Python Debugger*).
  Sans debug : tâche « Sentinel-X (Back + Front, sans debug) ».
- **Ligne de commande** (le venv `backend/.venv` est utilisé automatiquement, inutile de l'activer) :
  `npm run dev:yolo` (YOLO sur la webcam du navigateur) ou `npm run dev` (mock) — API sur :4000, dashboard sur http://localhost:5173.
  Séparément : `npm run api` / `npm run api:yolo` (back) et `npm run dev -w frontend` (front).

Les terminaux affichent en vert la connexion front ↔ back et en rouge la déconnexion / les intrusions.

### Variables d'environnement du back

| Variable | Défaut | Rôle |
|---|---|---|
| `PROVIDER` | `mock` | source des capteurs : `mock` \| `ssh` (à implémenter) |
| `ANALYZER` | `mock` | `mock` \| `local` (YOLO + fusion capteurs) |
| `VISION_SOURCE` | `0` | image de YOLO : `0` = webcam de la machine du backend, URL du flux du Pi (`http://…`, `rtsp://…`), chemin d'un fichier vidéo (rejoué en boucle), ou `browser` = webcam du navigateur (le dashboard envoie ses images) |
| `YOLO_MODEL` | `yolov8n.pt` | poids dans `backend/models/` (téléchargés si absents). `yolov8n-seg.pt` dessine la **silhouette** de chaque personne (≈ 2× plus lent), `yolov8n.pt` seulement des cadres |
| `YOLO_CONF` / `YOLO_IMGSZ` | `0.5` / `640` | seuil de confiance / taille d'inférence (plus petit = plus rapide) |
| `VISION_FPS` | `10` | plafond d'images traitées par seconde |
| `VISION_ANNOTATE` | `0` | `0` : image brute + positions, **React dessine** les carrés rouges ; `1` : YOLO incruste ses dessins dans l'image |
| `INTRUSION_TIMEOUT_S` | `3` | sans détection pendant ce délai, l'intrusion est terminée |
| `CAPTURE_MAX_WIDTH` / `CAPTURE_JPEG_QUALITY` | `640` / `70` | photos d'intrusion allégées : réduites à cette largeur, JPEG de cette qualité, progressif (≈ 15 Ko au lieu de 40 à 160 Ko) |
| `CAPTURE_SETTLE_S` | `1.5` | latence avant de photographier quand le nombre de personnes monte (plus grand = moins de photos, alerte plus tardive) |
| `CAPTURES_DIR` | `backend/data/captures` | dossier des photos d'intrusion |
| `TICK_MS` | `1000` | période des capteurs |

## Architecture

```
Raspberry Pi ──(brut : capteurs)──► backend ──► front   chemin rapide : snapshot, chaque seconde        (WS /ws)
      │  ▲                          │
      │  └──(ordres moteur)─────────┤
      │                             ├─► analyseur (thread) ──► front   chemin lent : score, anomalies   (WS /ws)
      └──(flux caméra)──► vision (caméra + YOLO, thread) ──► front   chemin vidéo : image + positions    (WS /ws/video)
                                              └──► alertes d'intrusion + photo                         (WS /ws)
```

- Le **Pi n'envoie que de la donnée brute** (capteurs, flux caméra) et reçoit des ordres moteur. Aucun calcul d'IA dessus.
- **YOLO tourne dans le backend**, pas sur un serveur à part : le service de vision a son propre thread et son propre rythme (~10 images/s), indépendant du tick des capteurs (1/s). Un YOLO lent ne bloque ni l'API ni l'affichage des capteurs.
- **YOLO prend une image en entrée et rend ses résultats** : positions des carrés (`bbox`), silhouettes (`polygon`, modèle de segmentation) et confiance. Chaque image part sur `/ws/video` **avec ses propres résultats et la menace courante** (un message binaire : 4 octets = taille N de l'en-tête, N octets de JSON `{ts, width, height, annotated, personCount, detections, threat}`, puis le JPEG ; `personCount` = nombre de personnes détectées, aussi présent dans le message `analysis` et dans l'alerte d'intrusion). **React dessine les carrés rouges, les silhouettes et le bandeau « INTRUSION DETECTED » sur un canvas** (`frontend/src/components/drawOverlay.js`), parfaitement synchronisés avec l'image. Avec `VISION_ANNOTATE=1`, YOLO incruste à la place ses propres dessins dans l'image (`annotated: true`, React ne redessine rien). Si un client est lent, les images intermédiaires sont sautées (pas de retard cumulé).
- **Image en entrée par HTTP** : `POST /api/vision/analyze` (corps = JPEG/PNG) renvoie `detections`, `threat` (calculée avec les capteurs courants) et, avec `?annotated=true`, l'image annotée par YOLO. Utile pour tester ou pour qu'une autre source (le Pi) envoie ses images.
- Une **intrusion** démarre à la première détection de personne : photo enregistrée dans `CAPTURES_DIR` (`intrusion_<date>_<N>p.jpg`, N = nombre de personnes), alerte critique avec la photo (miniature dans le journal d'alertes). **Une nouvelle photo et une alerte « Nouvelle personne détectée » sont ajoutées quand le nombre de personnes atteint un nouveau palier.** YOLO hésitant d'une image à l'autre (2, 3, 2, 3…), on n'agit pas tout de suite : une **latence de confirmation** (`CAPTURE_SETTLE_S`, 1,5 s) retient le maximum vu et l'image qui montre le plus de personnes, puis **une seule photo** est prise à ce niveau. Un clignotement entre les mêmes nombres = une photo ; 2-3 puis 3-4 = deux photos. Une détection de moins de 3 images est du bruit (ni photo ni alerte). Pas de suivi d'identité. L'intrusion se termine après `INTRUSION_TIMEOUT_S` sans détection ; une personne qui revient ensuite (ou des personnes parties depuis plus de ce délai) redéclenche une photo.
- L'analyseur (score de menace, anomalies DHT22) reçoit le snapshot dans un thread ; son résultat repart plus tard (message `analysis`, avec `forTs` = snapshot analysé et `latencyMs`). S'il est occupé, le snapshot est sauté ; s'il plante, le dashboard continue et affiche « IA hors ligne ».
- Alertes : proximité et pic thermique = seuils sur la donnée brute (immédiat) ; anomalie d'environnement = analyseur ; intrusion = service de vision (ou analyseur en mode mock).
- **Webcam du navigateur** : l'interrupteur « Webcam PC » du panneau Caméra envoie les images de la webcam (JPEG, ~8/s) au backend sur `/ws/camera` ; YOLO les traite et l'image revient avec ses résultats sur `/ws/video`. Le backend relâche alors sa propre caméra (une webcam ne s'ouvre que dans un programme à la fois) et la reprend quand on désactive l'interrupteur. Avec `VISION_SOURCE=browser`, le backend n'ouvre aucune caméra et l'interrupteur est activé d'emblée.
- Caméra du Pi : mettre l'URL de son flux dans `VISION_SOURCE`, le reste est identique.

## Modules du dashboard

| Module | Données |
|---|---|
| Caméra | image de la caméra du backend ou de la webcam du navigateur, avec carrés rouges, silhouettes, confiance et menace dessinés par React d'après les positions de YOLO (`ANALYZER=local`) ; sinon faux flux canvas, webcam du PC via l'interrupteur, ou `camera.streamUrl` |
| Ultrason | distance, radar orienté selon l'angle du moteur, historique |
| Thermique | matrice 8×8, moyenne / max, historique |
| Environnement (DHT22) | température, humidité, point de rosée, score d'anomalie IA et ses raisons, historiques |
| Moteur | angle, cible, vitesse, mode ; commandes : position, pas, centrer, balayage auto, vitesse, stop |
| Score de menace | calculé par l'analyseur, affiché en différé : caméra 45 % / ultrason 25 % / thermique 15 % / environnement 15 % |
| Alertes | proximité (< 80 cm), pic thermique (> 45 °C), intrusion (avec photo), anomalie d'environnement (score DHT22 ≥ 70) ; seuils dans `backend/app/config.py` |
| Raspberry Pi | CPU, RAM, température, uptime |

En mode mock, trois boutons du journal d'alertes déclenchent un intrus (capteurs), un pic thermique ou une fenêtre ouverte pour la démo.

## API

REST :
- `GET /api/health`, `GET /api/snapshot` (brut), `GET /api/analysis` (dernier résultat), `GET /api/vision` (état caméra + YOLO), `GET /api/history` (`{sensors, threat}`), `GET /api/alerts`
- `GET /api/captures/{fichier}` — photo d'intrusion
- `POST /api/vision/analyze` — YOLO sur une image envoyée en entrée (`?annotated=true` pour l'image dessinée)
- `POST /api/vision/source` — `{mode:'browser'}` (YOLO traite la webcam du navigateur) | `{mode:'default'}` (caméra du backend)
- `POST /api/motor` — `{type:'move',angle}` · `{type:'step',delta}` · `{type:'sweep',enabled}` · `{type:'speed',value}` · `{type:'stop'}`
- `POST /api/mock/{scenario}` — `intruder` | `heat` | `window` (mock uniquement)
- Documentation interactive générée par FastAPI : http://localhost:4000/docs

WebSocket :
- `/ws` (JSON) — `hello` (état complet à la connexion), `snapshot`, `analysis`, `alert` (champ `snapshot` = URL de la photo pour une intrusion), `motor`, `vision` (`{enabled, state: loading|running|waiting|error|stopped, source, model, fps, error}` ; `waiting` = mode navigateur sans image reçue)
- `/ws/video` (binaire, backend → front) — une image + ses résultats YOLO + la menace par message (format ci-dessus) ; rien si la vision est désactivée
- `/ws/camera` (binaire, front → backend) — images JPEG de la webcam du navigateur, pour YOLO (mode navigateur)

Les clés JSON sont en camelCase (`distanceCm`, `maxC`…) : c'est le contrat avec le front.

## Brancher le vrai Raspberry Pi (SSH)

Tout passe par un *provider* (`backend/app/providers/`). Pour remplacer le mock, il suffit d'implémenter
[ssh.py](backend/app/providers/ssh.py) avec le même contrat que `mock.py` (`start`, `stop`, `get_snapshot`, `send_motor_command`)
et la même forme de snapshot — le moteur d'alertes, l'API, l'analyseur et le front n'ont pas à changer.
Le contrat et une piste d'implémentation (`asyncssh` + script Python côté Pi) sont documentés en tête de `ssh.py`.

## Capteur DHT22 (température / humidité)

Module 3 broches « V182 » : capteur **DHT22 / AM2302** (−40 à 80 °C ±0,5 °C, 0 à 100 % HR ±2 à 5 %,
**une mesure toutes les 2 s au maximum**, protocole fil unique propriétaire — pas du 1-Wire). Résistance de tirage déjà sur le module.

- **Câblage** : `+` → 3,3 V (broche 1, surtout pas 5 V), `out` → GPIO4 (broche 7), `−` → GND (broche 6).
- **Lecture côté Pi** : `raspberry-pi/dht22_reader.py` (pilote noyau `dtoverlay=dht11,gpiopin=4`, repli Adafruit) → une ligne JSON par mesure,
  `{tempC, humidityPct, readAt}` = champ `environment` du snapshot. `--csv dht22_log.csv` journalise les données d'entraînement.
- **Ce que l'IA en fait** : température ambiante fiable pour la matrice thermique, et détection d'anomalies d'environnement
  (surchauffe / départ de feu, fenêtre ou porte ouverte, condensation), ajoutée au score de menace.
- **Algorithme** : détection d'anomalies **non supervisée** sur des variables dérivées (température, humidité, point de rosée,
  pentes sur 1 / 5 / 15 min, heure de la journée) + garde-fous déterministes (> 45 °C, montée > 2 °C/min, air proche de la saturation).
  - `backend/app/ai/env_anomaly.py` : version en ligne (moyennes / variances glissantes + z-score), utilisée par les deux analyseurs.
    Elle apprend la normale de la pièce pendant ~1 min puis n'apprend plus des anomalies.
  - `ml/environment/env_model.py` : **Isolation Forest** (scikit-learn) entraînée sur quelques jours de données normales (voir `ml/README.md`).
  - Sortie commune : `environment: {score 0..100, label, dewPointC, reasons[]}` dans le résultat de l'analyse.

## Brancher un autre modèle (équipe IA)

- **Vision** : `backend/app/vision/detector.py` (`YoloDetector.detect(image) -> (détections, image annotée ou None)`) est le seul endroit qui connaît YOLO. Pour changer de modèle : poids dans `backend/models/` + `YOLO_MODEL`.
- **Analyse** : `backend/app/ai/local_analyzer.py` (`analyze(snapshot) -> {detections, threat, environment}`, synchrone, appelé dans un thread). Le contrat y est documenté ; `mock_analyzer.py` montre le format exact.
