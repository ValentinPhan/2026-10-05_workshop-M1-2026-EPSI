# Sentinel-X — Dashboard (workshop M1 2026 EPSI)

Dashboard de supervision du boîtier Sentinel-X : API Python (FastAPI) et front React (Vite) avec Ant Design (thème sombre).
Le backend porte aussi la **vision temps réel** : caméra + YOLOv8 tournent dans le même process, la vidéo annotée et les
alertes d'intrusion (avec photo) arrivent au dashboard par WebSocket.

Deux modes, selon la variable `ANALYZER` :

| Mode | Capteurs du Pi | Caméra / détection | Score de menace |
|---|---|---|---|
| `ANALYZER=mock` (défaut) | simulés (`PROVIDER=mock`) | faux flux + faux détecteur | heuristique factice |
| `ANALYZER=local` | simulés (`PROVIDER=mock`) ou **réels** (`PROVIDER=ssh`) | **vraie caméra + YOLOv8** | fusion des capteurs avec les détections YOLO |

## Matériel (liste finale)

| Composant | Rôle |
|---|---|
| Raspberry Pi 3 | unité centrale du boîtier : lit les capteurs, pilote le moteur |
| Caméra Raspberry Pi (v1) | flux vidéo pour la détection YOLO |
| Micro-servomoteur SG90 | oriente le capteur ultrason (radar) |
| Capteur température / humidité DHT22 | données d'environnement (module « V182 », 3 broches) |
| Capteur ultrason | mesure de distance (alerte de proximité) |
| ESP8266 (NodeMCU) — Edge Node | boîtier autonome en MQTTS vers le PC : gaz MQ-2, présence PIR HC-SR501 (voir « Edge Node ESP8266 ») |

## Structure du dépôt

```
backend/            API FastAPI + vision YOLO  (tourne sur le PC)
  app/
    main.py         routes REST + WebSocket (/ws, /ws/video, /ws/camera)
    hub.py          état, diffusion WebSocket, chemins rapide / lent / vidéo
    auth.py         comptes, sessions, rôles admin / agent, limitation des tentatives
    db.py           base de données (SQLite par défaut, PostgreSQL via DATABASE_URL)
    cli.py          gestion des comptes en ligne de commande (mot de passe perdu)
    alerts.py       moteur d'alertes
    edge.py         Edge Node ESP8266 : client MQTTS (EDGE=mqtt) ou ESP simulé (EDGE=mock)
    config.py       seuils et variables d'environnement
    console.py      couleurs ANSI des messages de statut dans le terminal
    providers/      sources de données du Pi : mock.py · ssh.py (Raspberry réel) · motor.py
    vision/         caméra + YOLO dans un thread dédié : service.py · detector.py
    ai/             analyse : mock_analyzer.py · local_analyzer.py · threat.py · env_anomaly.py
  models/           poids des modèles (yolov8n.pt, yolo26n.pt)
  data/             base SQLite et photos d'intrusion (générées, non versionnées)
  .env.example      modèle de configuration (copier en .env)
  requirements.txt · requirements-vision.txt   dépendances de l'API · de la vision YOLO
  tests/            tests pytest (python -m pytest tests -q)
frontend/           dashboard React / Vite / Ant Design  (navigateur)
  src/
    App.jsx · Dashboard.jsx · api.js   point d'entrée, page principale, appels REST
    components/     un panneau par capteur (Camera, Ultrasonic, Thermal, Motor, Environment),
                    InfoPanels, UsersPanel, LoginPage, drawOverlay.js, ui.jsx
    hooks/          useSentinel (WebSocket), useAuth, useVideoStream, useWebcamUpload
raspberry-pi/       scripts qui tournent sur le Raspberry (montage et mise en service : raspberry-pi/README.md)
  sentinel_agent.py lit les capteurs, pilote le servo ; lancé par le backend via SSH (PROVIDER=ssh)
  dht22_reader.py   lecture du DHT22 (une ligne JSON par mesure)
  camera_push.py    envoie les images de la caméra au backend (WebSocket /ws/camera)
firmware/esp8266/   firmware PlatformIO de l'Edge Node (MQ-2, PIR, MQTTS)
infra/              broker Mosquitto (Docker) + PKI : mosquitto/ (TLS, ACL) · pki/gen-certs.sh
docs/               plan d'action, contrat MQTT
ml/                 atelier de l'équipe IA, hors ligne : vision/ (tests YOLO) · environment/ (Isolation Forest DHT22)
scripts/            run-api.mjs : lance l'API avec le Python du venv (backend/.venv)
.vscode/            F5 : lance back + front
.claude/            contexte du projet pour Claude Code (voir .claude/README.md)
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

- **VS Code** (F5) : plusieurs configurations (dont « caméra du Raspberry, push »), **choisissez-la dans la liste de « Exécuter et déboguer »** (la dernière utilisée est retenue).
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

## Comptes et base de données

Le dashboard est protégé par un compte. Deux rôles :

| Rôle | Peut |
|---|---|
| **agent** | consulter : données, vidéo YOLO, alertes, photos. Les commandes sont désactivées (« Lecture seule »). |
| **admin** | tout : piloter le moteur / la position de la caméra, changer la source vidéo, lancer les simulations, créer / supprimer des comptes, voir le journal d'audit. |

- **Premier lancement** : si la base n'a aucun utilisateur, le compte `admin` est créé. Sans `ADMIN_PASSWORD`, **un mot de passe aléatoire est affiché une seule fois dans la console du backend** (à noter). Les agents se créent ensuite depuis le dashboard (panneau « Comptes et journal d'audit », admin seulement).
- **Mot de passe perdu** : `cd backend` puis `python -m app.cli passwd admin` (voir aussi `list` et `create <identifiant> <admin|agent>`), avec le venv.
- **Base** : SQLite par défaut (un fichier `backend/data/sentinel.db`, rien à installer). **PostgreSQL** : définir `DATABASE_URL=postgresql+psycopg://utilisateur:mot-de-passe@hote:5432/base` dans `backend/.env` (modèle : `backend/.env.example`, fichier ignoré par git) ; le même code tourne sur les deux, les tables sont créées au démarrage. Le conteneur Postgres du serveur doit publier son port 5432 sur la machine du backend.
- **Ce qui est enregistré** : comptes et sessions, **historique des alertes** (le journal survit à un redémarrage), **journal d'audit** (connexions, échecs, commandes moteur, changement de source vidéo, simulations, gestion des comptes).
- **Sécurité** : mots de passe hachés (scrypt, sel aléatoire) ; session = jeton aléatoire dans un cookie `HttpOnly`, seule son empreinte est en base ; 5 échecs de connexion en 5 min bloquent temporairement l'identifiant ; les droits sont vérifiés **côté serveur** (l'interface ne fait que les refléter) ; les photos d'intrusion et les WebSocket exigent un compte ; les WebSocket ouvertes sont revérifiées toutes les 15 s (compte supprimé, mot de passe réinitialisé ou déconnexion = flux coupés). Le Raspberry s'authentifie avec un jeton d'appareil (`DEVICE_TOKEN`, `camera_push.py --token`). En HTTPS, mettre `COOKIE_SECURE=1`.

### Variables d'environnement du back

| Variable | Défaut | Rôle |
|---|---|---|
| `PROVIDER` | `mock` | source des capteurs : `mock` \| `ssh` (Raspberry réel, voir plus bas) |
| `SSH_HOST` / `SSH_PORT` / `SSH_USER` | `192.168.50.10` / `22` / `pi` | Raspberry joint par `PROVIDER=ssh` |
| `SSH_KEY` / `SSH_PASSWORD` | clés de `~/.ssh` / vide | clé privée SSH (conseillé) ou mot de passe |
| `SSH_KNOWN_HOSTS` | `~/.ssh/known_hosts` | empreintes acceptées pour le Pi ; `none` = pas de vérification (tests seulement) |
| `SSH_COMMAND` | `python3 -u ~/sentinel-x/raspberry-pi/sentinel_agent.py` | agent lancé sur le Pi |
| `ABSENT_MODULES` | `thermal` | capteurs non montés (`PROVIDER=ssh`) : jamais signalés en panne |
| `AGENT_LOCAL` | `0` | `1` : l'agent tourne sur ce PC en mode simulé (test sans Raspberry) |
| `ANALYZER` | `mock` | `mock` \| `local` (YOLO + fusion capteurs) |
| `VISION_SOURCE` | `0` | image de YOLO : `0` = webcam de la machine du backend, URL du flux du Pi (`http://…`, `rtsp://…`), chemin d'un fichier vidéo (rejoué en boucle), `browser` = webcam du navigateur (le dashboard envoie ses images), ou `push` = images envoyées par le Raspberry (`raspberry-pi/camera_push.py`) |
| `YOLO_MODEL` | `yolov8n.pt` | poids dans `backend/models/` (téléchargés si absents). `yolov8n-seg.pt` dessine la **silhouette** de chaque personne (≈ 2× plus lent), `yolov8n.pt` seulement des cadres |
| `YOLO_CONF` / `YOLO_IMGSZ` | `0.5` / `640` | seuil de confiance / taille d'inférence (plus petit = plus rapide) |
| `VISION_FPS` | `10` | plafond d'images traitées par seconde |
| `VISION_ANNOTATE` | `0` | `0` : image brute + positions, **React dessine** les carrés rouges ; `1` : YOLO incruste ses dessins dans l'image |
| `INTRUSION_TIMEOUT_S` | `3` | sans détection pendant ce délai, l'intrusion est terminée |
| `CAPTURE_MAX_WIDTH` / `CAPTURE_JPEG_QUALITY` | `640` / `70` | photos d'intrusion allégées : réduites à cette largeur, JPEG de cette qualité, progressif (≈ 15 Ko au lieu de 40 à 160 Ko) |
| `CAPTURE_SETTLE_S` | `1.5` | latence avant de photographier quand le nombre de personnes monte (plus grand = moins de photos, alerte plus tardive) |
| `CAPTURES_DIR` | `backend/data/captures` | dossier des photos d'intrusion |
| `TICK_MS` | `1000` | période des capteurs |
| `DATABASE_URL` | SQLite `backend/data/sentinel.db` | base de données (`postgresql+psycopg://…` pour PostgreSQL) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `admin` / aléatoire | compte admin créé au premier lancement |
| `DEVICE_TOKEN` | vide | jeton du Raspberry pour `/ws/camera` (vide = le Pi est refusé) |
| `AGENT_USERNAME` / `AGENT_PASSWORD` | `agent` / vide | compte agent (consultation seule), créé avec l'admin seulement si `AGENT_PASSWORD` est renseigné |
| `SESSION_HOURS` / `COOKIE_SECURE` | `12` / `0` | durée des sessions / cookie réservé au HTTPS |
| `APP_ENV` | `prod` | `prod` \| `dev`. En `dev`, aucune photo d'intrusion n'est enregistrée (l'alerte reste créée, sans image) |
| `VISION_ZONE` | `camera_1` | nom de la zone associée aux alertes d'intrusion |
| `VISION_JPEG_QUALITY` | `70` | qualité JPEG des images envoyées au dashboard |
| `RECORD_VIDEO` | `auto` | clip vidéo H.264 par intrusion : `auto` = activé en prod, désactivé en dev ; `1` / `0` pour forcer |
| `RECORD_PREROLL_S` / `RECORD_MAX_S` | `2` / `180` | secondes avant la détection incluses dans le clip / durée max d'un clip (au-delà, coupé en parties) |
| `RECORD_CRF` / `RECORD_MAX_WIDTH` | `28` / `640` | qualité H.264 (23 = meilleure et plus lourd, 32 = plus léger) / largeur max du clip |
| `RECORD_KEEP_MB` | `1000` | quota du dossier des clips : les plus anciens sont supprimés au-delà |
| `VIDEOS_DIR` | `backend/data/videos` | dossier des clips vidéo |
| `LOG_DIR` | `backend/data/logs` | journal JSON des événements (un fichier par jour) |
| `MONITOR_INTERVAL_S` | `60` | relevé périodique de tous les capteurs dans le journal JSON (min. 1) |
| `MODULE_TIMEOUT_S` / `DHT_STALE_S` | `5` / `30` | délai (s) sans snapshot avant de déclarer le Raspberry perdu / âge max (s) de la dernière mesure DHT22 |
| `HISTORY_SIZE` / `ALERTS_SIZE` | `120` / `50` | taille des historiques de mesures / des alertes gardées en mémoire |
| `API_PORT` | `4000` | port de l'API, lu par `scripts/run-api.mjs` et par le proxy de Vite (pas par `config.py`) |
| `EDGE` | `mock` avec `PROVIDER=mock`, sinon `off` | Edge Node ESP8266 : `mqtt` (vrai boîtier via le broker) \| `mock` (simulé) \| `off` |
| `MQTT_HOST` / `MQTT_PORT` | `127.0.0.1` / `8883` | broker Mosquitto (`infra/docker-compose.yml`) |
| `MQTT_CA` / `MQTT_CERT` / `MQTT_KEY` | `infra/pki/out/ca.crt`, `backend.crt`, `backend.key` | certificats du backend (générés par `infra/pki/gen-certs.sh`) |
| `EDGE_TIMEOUT_S` | `10` | sans message de l'ESP pendant ce délai : perte de connexion |
| `GAS_ALERT_RAW` | `600` | seuil d'alerte gaz (lecture brute du MQ-2, 0–1023) : à régler sur le vrai capteur |

Ces variables peuvent aussi être mises dans `backend/.env` (ignoré par git, modèle : `backend/.env.example`).

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
- **Caméra du Raspberry, deux façons** (le backend traite les images de la même manière) :
  - **Push en WebSocket (recommandé)** : le Pi lance `python3 raspberry-pi/camera_push.py --url ws://<ip-du-pc>:4000/ws/camera --token <DEVICE_TOKEN>` (le jeton est défini dans `backend/.env`) ; le backend démarre avec `VISION_SOURCE=push` (config F5 « caméra du Raspberry, push », qui écoute sur toutes les interfaces). Aucun serveur de streaming à installer sur le Pi, reconnexion automatique, pas de file d'attente : on capture juste avant d'envoyer, la latence reste basse. Environ 15 Ko par image, soit ~1,3 Mbit/s à 10 images/s. Dépendances du Pi : `python3-picamera2` et `pip install websockets`. Le script a été testé avec un fichier vidéo en entrée, **pas encore sur un vrai Raspberry** (la partie `picamera2` est à valider).
  - **Pull** : le Pi expose un flux MJPEG en HTTP et on met son URL dans `VISION_SOURCE` (`http://<ip-du-pi>:8080/…`).
  - Pas de MQTT pour la vidéo (message par message, sans notion de « dernière image ») et pas dans la session SSH (une rafale d'images retarderait les ordres moteur) : SSH reste pour le JSON et les commandes.

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
| Edge Node (ESP8266) | gaz MQ-2 (brut / 1023, courbe et seuil), présence PIR, Wi-Fi, état de la liaison MQTTS, messages perdus |

En mode mock, des boutons du journal d'alertes déclenchent un intrus (capteurs), un pic thermique, une fenêtre ouverte, et avec `EDGE=mock` une fuite de gaz ou une présence PIR, pour la démo.

## Scénario de démo

Déroulé proposé pour la soutenance, construit à partir des fonctionnalités du dépôt. Il n'a pas été chronométré : à répéter avant le passage.

**Avant de commencer**
1. `npm run dev:yolo` (YOLO sur la webcam du navigateur) ; `npm run dev` si aucune caméra n'est disponible (mock, sans détection).
2. Ouvrir http://localhost:5173 et accepter la caméra. Mot de passe admin perdu : `cd backend && python -m app.cli passwd admin`.
3. Vérifier `APP_ENV=prod` (par défaut) : en `dev`, aucune photo d'intrusion n'est enregistrée.
4. Ouvrir deux sessions : une **admin** et une **agent** (compte créé si `AGENT_PASSWORD` est renseigné, ou depuis la gestion des comptes de l’admin).

**Étapes**

| # | Action | Ce que le jury voit |
|---|---|---|
| 1 | Connexion en **admin** | tous les modules : caméra, ultrason, thermique, environnement (DHT22), moteur, score de menace, alertes |
| 2 | Se placer devant la caméra (mode `dev:yolo`) | carrés rouges et silhouettes dessinés par React, bandeau « INTRUSION DETECTED », alerte critique avec la **photo** en miniature ; une personne de plus = nouvelle photo et alerte « Nouvelle personne détectée » |
| 3 | Moteur : position, pas, balayage auto | le radar ultrason tourne avec l'angle du moteur |
| 4 | Approcher la main du capteur ultrason | alerte de proximité (< 80 cm) |
| 5 | Souffler de l'air chaud / humide sur le DHT22 | courbes température / humidité, score d'anomalie IA et ses raisons (alerte à partir de 70) |
| 6 | Mode mock : boutons du journal d'alertes **intrus**, **pic thermique**, **fenêtre ouverte** | alertes déclenchées à la demande, utile si le matériel ne répond pas |
| 7 | Connexion en **agent** | mêmes données, mais commandes désactivées (« Lecture seule ») et simulations refusées (`403`) |
| 8 | Retour en **admin** : journal d'audit | connexions, commandes moteur et changements de source vidéo tracés |

Les alertes de proximité et d'environnement (étapes 4 et 5) dépendent des capteurs réels du Raspberry : le provider SSH n'est pas encore implémenté, ces capteurs sont donc simulés pour l'instant (voir « Brancher le vrai Raspberry Pi (SSH) »).

**Plan B** : une démo enregistrée de secours est prévue vendredi matin (hors dépôt). Les clips H.264 des intrusions sont dans `backend/data/videos/` (`GET /api/videos`).

## API

REST :
Tout exige un compte (cookie de session) sauf `GET /api/health`. **Consultation (admin ou agent)** ci-dessous ; **actions réservées aux admins** : `POST /api/motor`, `POST /api/vision/source`, `POST /api/vision/analyze`, `POST /api/mock/{scenario}`, gestion des comptes. Un agent reçoit `403`, un visiteur non connecté `401`.

- Comptes : `POST /api/auth/login` (`{username, password}`), `POST /api/auth/logout`, `GET /api/auth/me` ; admin : `GET|POST /api/users`, `DELETE /api/users/{id}`, `POST /api/users/{id}/password`, `GET /api/audit`
- `GET /api/health` (public), `GET /api/snapshot` (brut), `GET /api/analysis` (dernier résultat), `GET /api/vision` (état caméra + YOLO), `GET /api/history` (`{sensors, threat}`), `GET /api/alerts`
- `GET /api/captures/{fichier}` — photo d'intrusion
- `POST /api/vision/analyze` — YOLO sur une image envoyée en entrée (`?annotated=true` pour l'image dessinée)
- `POST /api/vision/source` — `{mode:'browser'}` (YOLO traite la webcam du navigateur) | `{mode:'default'}` (caméra du backend)
- `POST /api/motor` — `{type:'move',angle}` · `{type:'step',delta}` · `{type:'sweep',enabled}` · `{type:'speed',value}` · `{type:'stop'}`
- `POST /api/mock/{scenario}` — `intruder` | `heat` | `window` (`PROVIDER=mock`) · `gas` | `presence` (`EDGE=mock`)
- `GET /api/edge` — Edge Node ESP8266 : liaison MQTT et dernières mesures de chaque boîtier (`null` si `EDGE=off`)
- Documentation interactive générée par FastAPI : http://localhost:4000/docs

WebSocket :
- `/ws` (JSON) — `hello` (état complet à la connexion), `snapshot`, `analysis`, `alert` (champ `snapshot` = URL de la photo pour une intrusion), `motor`, `edge` (état de l'Edge Node à chaque message de l'ESP), `vision` (`{enabled, state: loading|running|waiting|error|stopped, source, model, fps, error}` ; `waiting` = mode navigateur sans image reçue)
- `/ws/video` (binaire, backend → front) — une image + ses résultats YOLO + la menace par message (format ci-dessus) ; rien si la vision est désactivée
- `/ws/camera` (binaire, vers le backend) — images JPEG envoyées par la webcam du navigateur (mode `browser`) ou par le Raspberry (mode `push`), pour YOLO. Accepté pour un **admin connecté** (cookie) ou un appareil muni du jeton `?token=<DEVICE_TOKEN>` (le Raspberry). Les autres WebSocket (`/ws`, `/ws/video`) exigent un compte ; refus = fermeture avec le code `4401` (non connecté) ou `4403` (rôle insuffisant)

Les clés JSON sont en camelCase (`distanceCm`, `maxC`…) : c'est le contrat avec le front.

## Brancher le vrai Raspberry Pi (SSH)

`PROVIDER=ssh` : le backend ouvre **une connexion SSH persistante** (`asyncssh`) vers le Pi et y lance
[`raspberry-pi/sentinel_agent.py`](raspberry-pi/sentinel_agent.py). Montage, câblage et mise en service : [`raspberry-pi/README.md`](raspberry-pi/README.md).

- **Protocole** : l'agent écrit **un snapshot JSON par ligne** sur stdout (même forme que le mock, `thermal: null`) et lit **une commande moteur JSON par ligne** sur stdin.
  Les commandes sont validées par le backend (`motor.py`) **avant** l'envoi ; Pi injoignable ⇒ `POST /api/motor` répond `503`.
- **Reconnexion automatique** (1, 2, 5 puis 10 s, indéfiniment) ; keepalive SSH toutes les 5 s. Pendant la coupure, la santé des modules signale « Perte de connexion : Raspberry Pi » (5 s) puis son retour.
  Événements du journal : `provider.connect` / `provider.disconnect` ; le journal de l'agent (stderr) apparaît dans la console du backend, préfixé `[pi]`.
- **Sécurité** : authentification par clé (ou mot de passe dans `backend/.env`), **empreinte du Pi vérifiée** (`~/.ssh/known_hosts`) : un autre appareil qui prend son IP est refusé.
  Fin de session (backend arrêté, liaison coupée) ⇒ stdin de l'agent fermé ⇒ l'agent s'arrête et relâche le servo. Un agent orphelin (Wi-Fi coupé) est arrêté par le suivant (un seul à la fois sur les GPIO).
- **Servo SG90** : pas de retour de position, l'angle affiché est la consigne déplacée à la vitesse demandée ; à la reconnexion, l'agent redémarre servo centré (0°).
- **Sans Raspberry** : `PROVIDER=ssh AGENT_LOCAL=1` lance l'agent en mode `--fake` sur le PC (tout le chemin sauf le réseau).
- Pas de matrice thermique sur le boîtier : `ABSENT_MODULES=thermal` (défaut) ; le dashboard masque le panneau quand `thermal` vaut `null`.
- **Testé** : agent seul, chaîne complète avec l'agent local (dashboard compris), vrai SSH contre un serveur `asyncssh` local (connexion, commande, coupure / reconnexion, refus d'une empreinte inconnue, arrêt de l'agent). **Pas encore testé sur le vrai Raspberry** (GPIO, servo, HC-SR04).

## Edge Node ESP8266 (gaz, présence) en MQTTS

Le sujet impose un boîtier ESP8266 « Edge Node » : il publie gaz (MQ-2) et présence (PIR) vers un broker **Mosquitto** sur le PC,
en **TLS 1.2 avec certificat client** (mTLS) et **ACL par boîtier**. Le backend s'y abonne (`EDGE=mqtt`), indépendamment du Raspberry.

1. PC serveur (Git Bash) : `cd infra && ./pki/gen-certs.sh && docker compose up -d` ; pare-feu Windows : ouvrir 8883 depuis le hotspot.
2. ESP : voir [`firmware/esp8266/README.md`](firmware/esp8266/README.md) (câblage, `config.h`, `certs.h`, `pio run -t upload`).
3. Backend : `EDGE=mqtt` dans `backend/.env` (certificats lus dans `infra/pki/out/` par défaut). Le panneau « Edge Node » apparaît dans le dashboard.

Contrat des messages, ACL et commandes de preuve (Wireshark, connexion sans certificat refusée, usurpation refusée) : [`docs/mqtt-contract.md`](docs/mqtt-contract.md).

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
