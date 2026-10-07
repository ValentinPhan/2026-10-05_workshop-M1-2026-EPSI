# Architecture

## 1. Topologie réseau cible

```
                    Wi-Fi dédié (hotspot du PC de l'utilisateur, WPA2 — jamais le Wi-Fi de l'école)
   ┌────────────────────────────────────────────────────────────────────────┐
   │  PC portable (Windows) = point d'accès Wi-Fi + serveur                  │
   │   ├─ backend FastAPI/uvicorn  :4000  (REST + WebSocket, YOLO, BDD)       │
   │   ├─ front React (Vite)       :5173  (dev ; proxy /api et /ws vers :4000)│
   │   └─ navigateur(s) : localhost:5173 (autres appareils du hotspot possibles)│
   └───────────────▲───────────────────────────────▲────────────────────────┘
                   │ SSH :22 (JSON capteurs ← / ordres moteur →)  │ WebSocket binaire /ws/camera (JPEG)
                   │ [À IMPLÉMENTER : providers/ssh.py]            │ [camera_push.py — testé sans vrai Pi]
          ┌────────┴───────────────────────────────────────────────┴────────┐
          │  Raspberry Pi (rejoint le Wi-Fi du PC, même sous-réseau)          │
          │  capteurs : ultrason, matrice thermique 8×8, DHT22, caméra, moteur│
          │  aucune IA sur le Pi : donnée brute en sortie, ordres moteur en entrée
          └───────────────────────────────────────────────────────────────────┘
```

- **Le Pi n'envoie que de la donnée brute** et reçoit des ordres moteur. L'IA tourne **dans le backend, sur le PC** (YOLO dans un thread du même process : pas de serveur IA séparé).
- Plage par défaut d'un hotspot Windows : `192.168.137.0/24`, PC = `192.168.137.1` **[à vérifier]**. Fixer l'IP du Pi. Pare-feu Windows : ouvrir le port 4000 depuis le hotspot.
- **Vidéo du Pi — 3 options, toutes gérées par `VISION_SOURCE`** : (1) `push` (recommandé) : le Pi envoie ses JPEG en WebSocket sur `/ws/camera` ; (2) pull : le Pi expose un flux MJPEG/RTSP, on met l'URL dans `VISION_SOURCE` ;
  (3) `browser` : la webcam du navigateur. **Pas de MQTT pour la vidéo** (pas de notion de « dernière image », broker en plus) et **pas dans la session SSH** (une rafale d'images retarderait les ordres moteur).
  ≈ 15 Ko/image 640×480 → ~1,3 Mbit/s à 10 img/s.
- Le sujet d'origine parlait d'un **ESP8266 → MQTTS → Mosquitto**. Le code actuel ne contient **ni ESP8266 ni MQTT** (voir `etat-et-decisions.md`, « écarts »).
- Une pile serveur Docker (Postgres, MQTT) existe **hors dépôt** chez l'utilisateur (`C:\Users\noamg\Bureau\sentinel-x-server`, retirée du dépôt par l'utilisateur). Son conteneur Postgres `sentinel-postgres`
  (postgres:17) **ne publie pas le port 5432** sur la machine : pour que le backend l'utilise, il faut `ports: ["127.0.0.1:5432:5432"]` dans son compose.
- Des commits « plan d'action `docs/PLAN.md` » et « contrat MQTT + squelette docker-compose » existent sur des branches distantes `origin/claude/*` non fusionnées : à lire (`git show origin/<branche>:docs/PLAN.md`) avant de refaire un plan.

## 2. Backend (`backend/app/`)

FastAPI + uvicorn, Python 3.13 (3.11+ OK). `main.py` : routes, handlers d'erreurs (toujours `{"error": "..."}`), WebSocket, `lifespan` (création de l'admin au premier lancement, démarrage du hub).

### Les trois chemins de données (`hub.py`)

| Chemin | Source → destination | Rythme | Détail |
|---|---|---|---|
| **Rapide** | provider (Pi) → front | 1 / s | message WS `snapshot` diffusé **sans attendre l'IA** ; alertes à seuil (proximité, chaleur) évaluées tout de suite |
| **Lent** | snapshot → analyseur (thread `asyncio.to_thread`) → front | 1 / s, en différé | message WS `analysis` (avec `forTs` = snapshot analysé, `latencyMs`) ; **pas de file d'attente** (si l'analyseur est occupé le snapshot est sauté) ; s'il plante : `{ok:false,error}` et le dashboard affiche « IA hors ligne » |
| **Vidéo** | caméra / images poussées → YOLO (thread `vision`) → front | ~10 img/s | message binaire sur `/ws/video` ; client lent = images sautées (`VideoClient.busy`) |

Les callbacks du thread de vision repassent dans la boucle asyncio via `loop.call_soon_threadsafe`. Les `WebSocket` ouvertes sont revérifiées toutes les 15 s (`_sweep_sessions`) : compte supprimé / mot de passe réinitialisé / déconnexion ⇒ fermeture `4401`.

### Providers (source des données du Pi) — `providers/`
Contrat : `name`, `async start(on_snapshot)`, `async stop()`, `get_snapshot()`, `async send_motor_command(cmd)` (+ `trigger_scenario` pour le mock).
- `mock.py` : Pi simulé (intrus qui approche/reste/part, pic thermique, fenêtre ouverte, DHT22 avec inertie et lectures ratées, moteur avec balayage).
- `ssh.py` : **squelette** (lève `NotImplementedError`). Plan : `asyncssh`, connexion persistante, script côté Pi qui imprime **une ligne JSON par mesure** sur stdout, ordres moteur envoyés sur son stdin (validés par `apply_motor_command`), **reconnexion automatique**.
- `motor.py` : commandes `{type:'move',angle}` `{type:'step',delta}` `{type:'sweep',enabled}` `{type:'speed',value}` `{type:'stop'}` ; angle −90..90°, vitesse 5..90 °/s.

**Snapshot brut** (clés en camelCase = contrat avec le front) :
`{ts, ultrasonic:{distanceCm,maxRangeCm}, thermal:{avgC,maxC,grid[8][8]}, camera:{streamUrl,width,height,fps}, motor:{angle,target,speed,mode,moving}, environment:{tempC,humidityPct,readAt}, system:{link,cpuPct,ramPct,cpuTempC,uptimeS}}`

### Analyse (`ai/`) — `ANALYZER=mock|local`
Contrat : `analyze(snapshot) -> {detections:[{label,confidence,bbox{x,y,w,h},polygon?}], threat:{score 0-100,label}, environment?}` — **synchrone** (appelée dans un thread).
- `mock_analyzer.py` : faux modèle (déduit une « personne » de la tache chaude de la matrice + ultrason, latence 150–400 ms simulée).
- `local_analyzer.py` : détections **YOLO réelles** (`vision.latest_detections()`, vides si > 2 s) + `EnvDetector` + `threat_score`.
- `threat.py` : **score de menace = 45 % personne (confiance YOLO) + 25 % proximité ultrason + 15 % chaleur + 15 % anomalie d'environnement** ; libellé Calme < 30 ≤ Vigilance < 60 ≤ Menace.
- `env_anomaly.py` : détecteur d'anomalies DHT22 **en ligne**, sans dépendance (z-score glissant sur température, humidité, pentes ; apprentissage 30 mesures ≈ 1 min ; garde-fous : > 45 °C ou +2 °C/min ⇒ 100, air proche de la saturation ⇒ ≥ 70). Sortie `{score,label Apprentissage|Normal|Inhabituel|Anomalie,dewPointC,reasons[],learning}`.
  Le vrai modèle (Isolation Forest, `ml/environment/env_model.py`) **n'est pas branché** : à intégrer dans `LocalAnalyzer`.

### Vision (`vision/`) — `VisionService` (thread dédié, démarre seulement avec `ANALYZER=local`)
- Sources commutables à chaud : **caméra du backend** (`VISION_SOURCE` = `0`, URL, ou fichier vidéo rejoué en boucle) ou **images poussées** (`browser` / `push` ⇒ `/ws/camera`, `push_frame`, dernier-gagnant). Passer en mode navigateur **relâche la caméra du backend**.
- `YoloDetector` (ultralytics) : classe « person » seule, `result.boxes` + silhouettes (`result.masks.xyn` simplifiées par Douglas-Peucker ≤ 60 points avec `yolov8n-seg.pt`), verrou (modèle non thread-safe), poids téléchargés dans `backend/models/` s'ils manquent. Modèle par défaut `yolov8n.pt` ; les configs F5 YOLO utilisent `yolov8n-seg.pt` + `YOLO_IMGSZ=480`.
- États : `loading` · `running` · `waiting` (mode push sans image depuis 3 s) · `error` · `stopped` ; message WS `vision`.
- **Photos d'intrusion** : à la première détection, puis à chaque **nouveau palier** du nombre de personnes, avec **latence de confirmation** `CAPTURE_SETTLE_S` (1,5 s) : on garde l'image montrant le plus de personnes et on prend **une photo**
  (un clignotement 2-3-2-3 = 1 photo ; 2-3 puis 3-4 = 2 photos). < 3 images de détection = bruit. Le niveau ne redescend qu'après `INTRUSION_TIMEOUT_S` (3 s) sans le revoir ; l'intrusion se termine après ce délai sans détection.
  Photo allégée (640 px, JPEG q70, progressif ≈ 15 Ko), nom `intrusion_<date>_<ms>_<N>p.jpg` dans `backend/data/captures/` (ignoré par git), servie par `GET /api/captures/{nom}` (compte requis).
- Message vidéo `/ws/video` : `[4 octets : taille N de l'en-tête, big-endian][N octets JSON {ts,width,height,annotated,personCount,detections,threat}][JPEG]`. Par défaut l'image est **brute** et le front dessine ; `VISION_ANNOTATE=1` = YOLO incruste ses dessins.
- `POST /api/vision/analyze` (admin) : image en entrée (corps JPEG/PNG) → détections + menace (+ image annotée en base64 avec `?annotated=true`).

### Alertes (`alerts.py`)
Une alerte part au passage « condition fausse → vraie ». Règles : **proximité** (< 80 cm, warning) et **chaleur** (maxC > 45 °C, warning) sur la donnée brute (immédiat, marchent sans IA) ; **anomalie d'environnement** (score DHT22 ≥ 70, warning) via l'analyse ;
**intrusion** (critical, avec `snapshot` = URL de la photo) : issue des événements de la vision quand elle est active (`intrusion` / `new_person`), sinon de l'analyse (personne ≥ 0,6). Les alertes sont **enregistrées en base** et rechargées au démarrage.

### Comptes, base, sécurité (`auth.py`, `db.py`, `cli.py`)
- Rôles : **admin** (tout : moteur / position de la caméra, source vidéo, simulations, `analyze`, gestion des comptes, audit) · **agent** (consultation seule). Seul `GET /api/health` est public. Droits **vérifiés côté serveur** (403 agent, 401 non connecté).
- Mots de passe : scrypt (stdlib). Session : jeton aléatoire en cookie `sentinel_session` (HttpOnly, SameSite=Lax), **seule son empreinte SHA-256 en base**, durée `SESSION_HOURS` (12). 5 échecs / 5 min par couple adresse+identifiant ⇒ 429.
  Identifiants insensibles à la casse (index d'unicité sur `lower(username)`).
- WebSocket : `/ws` et `/ws/video` exigent la session (refus : accept puis `close(4401)`). `/ws/camera` : **admin connecté** ou **jeton d'appareil** `?token=<DEVICE_TOKEN>` (le Pi). 4403 = rôle insuffisant.
- Base : SQLAlchemy 2, **SQLite par défaut** (`backend/data/sentinel.db`), **PostgreSQL** avec `DATABASE_URL=postgresql+psycopg://…` (testé sur postgres:17). Tables : `users`, `sessions`, `alerts`, `audit_log` (connexions, échecs, moteur, source vidéo, simulations, comptes).
- `python -m app.cli list|create <id> <admin|agent>|passwd <id>` (récupération).

### API
REST : `/api/health` (public) · `/api/auth/{login,logout,me}` · `/api/snapshot|analysis|vision|history|alerts` · `/api/captures/{nom}` · admin : `POST /api/motor`, `/api/vision/source` (`{mode:'browser'|'default'}`), `/api/vision/analyze`, `/api/mock/{intruder|heat|window}`, `/api/users` (+ `DELETE /{id}`, `POST /{id}/password`), `/api/audit`.
WebSocket JSON `/ws` : `hello` (état complet : provider, snapshot, analysis, vision, history{sensors,threat}, alerts) · `snapshot` · `analysis` · `alert` · `motor` · `vision`. Détails et exemples dans `README.md`.

### Configuration (`config.py`, variables d'environnement ou `backend/.env`)
`PROVIDER` (mock|ssh) · `ANALYZER` (mock|local) · `TICK_MS` · `VISION_SOURCE` · `YOLO_MODEL` · `YOLO_CONF` (0.5) · `YOLO_IMGSZ` (640) · `VISION_FPS` (10) · `VISION_ANNOTATE` · `INTRUSION_TIMEOUT_S` (3) · `CAPTURE_SETTLE_S` (1.5) ·
`CAPTURE_MAX_WIDTH`/`CAPTURE_JPEG_QUALITY` (640/70) · `CAPTURES_DIR` · `DATABASE_URL` · `ADMIN_USERNAME`/`ADMIN_PASSWORD` · `DEVICE_TOKEN` · `SESSION_HOURS` · `COOKIE_SECURE`. Seuils d'alerte dans `Thresholds` (80 cm, 45 °C, 0.6, score DHT22 70).

## 3. Frontend (`frontend/`)

React 18 + Vite 6 + Ant Design 6 (thème sombre, textes en français). `App.jsx` = **porte d'entrée** : vérifie la session (`useAuth`), sinon `LoginPage` ; rien du dashboard n'est chargé sans compte. `Dashboard.jsx` = grille de panneaux selon le rôle.
- Panneaux : `CameraPanel` (canvas) · `ThreatPanel` (score en différé) · `SystemPanel` · `UltrasonicPanel` (radar orienté selon l'angle du moteur) · `ThermalPanel` (heatmap 8×8) · `EnvironmentPanel` (DHT22) · `MotorPanel` (admin ; `readOnly` pour un agent) · `AlertsPanel` (miniatures des photos) · `UsersPanel` (admin : comptes + audit). Graphiques = SVG maison (`ui.jsx`).
- Hooks : `useSentinel` (WS `/ws`, reconnexion à backoff, état global) · `useVideoStream` (WS `/ws/video`, décode l'en-tête + JPEG, dessine sur le canvas) · `useWebcamUpload` (envoie la webcam du navigateur sur `/ws/camera`, ~8 img/s, avec retries si la caméra est occupée) · `useAuth`.
- `components/drawOverlay.js` : dessine l'image puis **carrés rouges, silhouettes, étiquettes, bandeau « INTRUSION DETECTED », « N PERSONNES DÉTECTÉES » et chip menace**. **Vue miroir** (`MIRROR = true` : image et positions retournées, textes lisibles) ; mettre `false` pour la caméra du Pi.
- `api.js` : `getJson/postJson/deleteJson` ; une réponse 401 déclenche l'événement `AUTH_EXPIRED` ⇒ retour à la page de connexion (WS fermée en `4401` idem).
- `vite.config.js` : proxy `/api`, `'^/ws$'` (événements, logue la connexion en vert/rouge dans le terminal), `'^/ws/(video|camera)$'` ; `API_PORT` pour viser un autre port de backend.
- Interface selon le mode vision : `vision.source` = `browser` ⇒ interrupteur « Webcam PC » (admin) ; `push` ⇒ « caméra du Raspberry », pas d'interrupteur ; sinon caméra du backend. Un agent ne peut ni changer la source ni envoyer sa webcam.

## 4. Raspberry Pi (`raspberry-pi/`) et atelier IA (`ml/`)

- `dht22_reader.py` : lit le DHT22 (GPIO4, une mesure / 2 s, pilote noyau `dtoverlay=dht11,gpiopin=4` ou Adafruit), imprime `{"tempC","humidityPct","readAt"}` par ligne (= champ `environment`). `--csv` journalise des données d'entraînement. Câblage : 3,3 V (**pas 5 V**), GPIO4, GND.
- `camera_push.py` : capture (picamera2 par défaut, webcam USB ou fichier vidéo via OpenCV) → JPEG → WebSocket `ws://<pc>:4000/ws/camera?token=…`. Capture juste avant d'envoyer (pas de retard cumulé), reconnexion. **Testé uniquement avec un fichier vidéo ; la partie picamera2 est écrite d'après la doc, non vérifiée sur un vrai Pi.**
- `ml/vision/` : `webcam_test.py`, `yolo_intrusion.py` (démos autonomes de l'équipe IA ; mêmes poids que le backend). `ml/environment/env_model.py` : Isolation Forest (`train|score|demo`) sur le DHT22, **non branché**.
