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
                   │ [providers/ssh.py — testé sans vrai Pi]       │ [camera_push.py — testé sans vrai Pi]
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
- **Edge Node ESP8266** (exigé par le sujet, décision du 8 octobre : on le garde, **en plus** du Pi ; **finalement NON câblé le 9 octobre** : `EDGE=off`, tout ce qui suit est du code prêt mais non éprouvé sur matériel) : MQ-2 (gaz) + PIR → **MQTTS** (TLS 1.2, certificat client ECDSA, ACL par CN) → **Mosquitto en Docker sur le PC** (`infra/docker-compose.yml`, port 8883) → backend (`app/edge.py`, `EDGE=mqtt`). Liaison **indépendante du Pi**. Contrat : `docs/mqtt-contract.md` ; firmware : `firmware/esp8266/` ; PKI : `infra/pki/gen-certs.sh` (`infra/pki/out/` ignoré par git, `BROKER_IP` = IP du PC sur le hotspot, défaut 192.168.137.1).
- Une pile serveur Docker (Postgres, MQTT) existe **hors dépôt** chez l'utilisateur (`C:\Users\noamg\Bureau\sentinel-x-server`, retirée du dépôt par l'utilisateur). Son conteneur Postgres `sentinel-postgres`
  (postgres:17) **ne publie pas le port 5432** sur la machine : pour que le backend l'utilise, il faut `ports: ["127.0.0.1:5432:5432"]` dans son compose. Le broker de l'ESP est celui de `infra/` (mTLS + ACL), pas celui de cette pile.
- **Montage réel (9 octobre)** : Pi 3 Model B, caméra CSI, servo SG90, HC-SR04 sur breadboard (diviseur 1 kΩ / 2 kΩ sur Echo), DHT22 (AM2302) ; **pas de matrice thermique** (`thermal: null`, `ABSENT_MODULES=thermal`) ; photo : `docs/img/montage-raspberry.jpg`, détail : `raspberry-pi/README.md`.
  **Caméra CSI en panne** : la vidéo vient d'une caméra USB branchée au PC. Pi joint en `piadmin@192.168.137.75` (SSH :22, Mosquitto TLS :8883, nom `sentinel-x`).
- Plan d'action : `docs/PLAN.md` (§ 2 et 4 bis à jour au 9 octobre ; le reste = plan initial du lundi). Scénario de soutenance chronométré (sans ESP) : `docs/DEMO.md`.

## 2. Backend (`backend/app/`)

FastAPI + uvicorn, Python 3.13 (3.11+ OK). `main.py` : routes, handlers d'erreurs (toujours `{"error": "..."}`), WebSocket, `lifespan` (création de l'admin au premier lancement, démarrage du hub).

### Les trois chemins de données (`hub.py`)

| Chemin | Source → destination | Rythme | Détail |
|---|---|---|---|
| **Rapide** | provider (Pi) → front | 1 / s | message WS `snapshot` diffusé **sans attendre l'IA** ; alertes à seuil (proximité, chaleur) évaluées tout de suite |
| **Lent** | snapshot → analyseur (thread `asyncio.to_thread`) → front | 1 / s, en différé | message WS `analysis` (avec `forTs` = snapshot analysé, `latencyMs`) ; **pas de file d'attente** (si l'analyseur est occupé le snapshot est sauté) ; s'il plante : `{ok:false,error}` et le dashboard affiche « IA hors ligne » |
| **Vidéo** | caméra / images poussées → YOLO (thread `vision`) → front | ~10 img/s | message binaire sur `/ws/video` ; client lent = images sautées (`VideoClient.busy`) |

Le `Hub` lance aussi deux tâches de fond : **`_watch_modules`** (1 s, santé des modules) et **`_monitor_log`** (relevé périodique, 60 s). Il fournit `context()` : l'état complet joint à chaque ligne du journal.
Les callbacks du thread de vision repassent dans la boucle asyncio via `loop.call_soon_threadsafe`. Les `WebSocket` ouvertes sont revérifiées toutes les 15 s (`_sweep_sessions`) : compte supprimé / mot de passe réinitialisé / déconnexion ⇒ fermeture `4401`.

### Providers (source des données du Pi) — `providers/`
Contrat : `name`, `async start(on_snapshot)`, `async stop()`, `get_snapshot()`, `async send_motor_command(cmd)` (+ `trigger_scenario` pour le mock).
- `mock.py` : Pi simulé (intrus qui approche/reste/part, pic thermique, fenêtre ouverte, DHT22 avec inertie et lectures ratées, moteur avec balayage).
- `ssh.py` : `asyncssh`, **une connexion persistante**, lance `raspberry-pi/sentinel_agent.py` sur le Pi (`SSH_COMMAND`) : **un snapshot JSON par ligne** sur stdout, **une commande moteur JSON par ligne** sur stdin (validée par `apply_motor_command` avant l'envoi ; Pi absent ⇒ `ConnectionError` ⇒ `POST /api/motor` = 503). Reconnexion 1/2/5/10 s indéfiniment, keepalive 5 s, empreinte du Pi vérifiée (`~/.ssh/known_hosts` ou `SSH_KNOWN_HOSTS`, `none` = tests). Journal `provider.connect|disconnect` (une ligne par coupure), stderr de l'agent en console `[pi] …`. `AGENT_LOCAL=1` = agent `--fake` en sous-processus sur le PC. `absent_modules` (`ABSENT_MODULES`, défaut `thermal`) : `ModuleMonitor` les laisse `unknown` (jamais d'alerte).
- `raspberry-pi/sentinel_agent.py` : servo **SG90** sur GPIO18 (gpiozero `AngularServo`, PWM pigpio si `pigpiod` tourne, sinon logiciel ; −90..90° ; pas de retour de position ; signal coupé à l'arrêt ; balayage ±60°), HC-SR04 GPIO23/24 (diviseur sur Echo), DHT22 GPIO4 (réutilise `dht22_reader.py`), stats `/proc`. `thermal: null`. stdin fermé ⇒ arrêt + servo relâché ; **un seul agent à la fois** (`/tmp/sentinel_agent.pid`, l'ancien reçoit SIGTERM). `--fake` sans GPIO. Montage : `raspberry-pi/README.md`.
- `motor.py` : commandes `{type:'move',angle}` `{type:'step',delta}` `{type:'sweep',enabled}` `{type:'speed',value}` `{type:'stop'}` ; angle −90..90°, vitesse 5..90 °/s.

**Snapshot brut** (clés en camelCase = contrat avec le front) :
`{ts, ultrasonic:{distanceCm,maxRangeCm}, thermal:{avgC,maxC,grid[8][8]}, camera:{streamUrl,width,height,fps}, motor:{angle,target,speed,mode,moving}, environment:{tempC,humidityPct,readAt}, system:{link,cpuPct,ramPct,cpuTempC,uptimeS}}`

### Edge Node ESP8266 (`edge.py`) — `EDGE=mqtt|mock|off`
Défaut `mock` avec `PROVIDER=mock`, sinon `off`. Contrat : `name`, `async start(notify)`, `async stop()`, `state()` (+ `trigger_scenario` pour le mock : `gas`, `presence`).
- `MqttEdge` : paho-mqtt (≥ 2.1) dans **son propre thread** (`loop_start`, reconnexion 1 → 30 s) ; ses callbacks repassent dans la boucle via `Hub._from_vision_thread` (même mécanisme que la vision). CN `backend`, certificats `infra/pki/out/` par défaut (`MQTT_CA|CERT|KEY`, `MQTT_HOST|PORT`).
- `apply_message` (logique pure, testée) valide chaque message (topic, ≤ 512 octets, JSON, types et bornes), compte les messages perdus (`seq`), gère le Last Will `offline`.
- `state()` = `{source, broker, connected, error, gasThreshold, nodes:[{node, online, fw, ip, seq, lost, readAt, lastSeenMs, gasRaw, pir, rssi, tempC, humidityPct}]}` ; diffusé en message WS `edge` à chaque message de l'ESP, inclus dans `hello`, dans `context()` du journal et dans `GET /api/edge`.
- Alertes : `gas_<node>` (critical, MQ-2 ≥ `GAS_ALERT_RAW` = 600) et `presence_<node>` (warning, PIR) ; module `esp8266` (critical) : broker injoignable, `offline`, ou muet depuis `EDGE_TIMEOUT_S` (10 s). Journal : `edge.connected|disconnected|error|invalid|node_online|node_offline|pir`.
- **Dans le score de menace** : le Hub joint `edge_state()` au snapshot passé à l'analyseur (`snapshot["edge"]`, aussi pour `POST /api/vision/analyze`) ; PIR = 10 % de la somme pondérée, gaz = plancher (voir `threat.py`). Boîtier hors ligne ou muet > `EDGE_TIMEOUT_S` : ignoré.

### Broker MQTT du Raspberry (`pi_mqtt.py`) — `PI_MQTT=auto|on|off` (ajouté le 9 octobre)
Reprise **dans notre backend** du backend Docker de l'équipe infra (pile hors dépôt `sentinel-x-server-collegue` : compose + `install.ps1`). **En plus du SSH, jamais bloquant** (paho dans son thread, `connect_async`, reconnexion 1 → 30 s ; broker absent = une ligne `pimqtt.error`, rien d'autre ne change, pas d'alerte ni de module de santé).
- Protocole identique au leur : MQTT 3.1.1 / TLS 8883, CA `infra/pi-broker/ca.crt` (copiée de l'infra, publique), nom vérifié `sentinel-x`, identifiant / mot de passe ; abonnements QoS 1 `sentinel/+/{telemetry,cyber,status}` ; message JSON avec `event_id` + `timestamp` ISO ; stocké dans la table **`events`** (même schéma que la leur : `event_id` PK, `device_id`, `category`, `event_type`, `event_timestamp`, `payload` JSONB, `received_at`) puis ACK `{"event_id","status":"stored"}` sur `sentinel/<device>/ack` (doublon = ré-acquitté, pas réenregistré).
- Config : `PI_MQTT_ENV_FILE` = chemin de **leur `.env`** (lu à part, sans polluer `MQTT_HOST/PORT` de l'Edge) ; `PI_MQTT_HOST|PORT|USER|PASSWORD|IP|CA` prioritaires. `auto` = actif si un mot de passe est connu. Si `sentinel-x` ne se résout pas : connexion à `PI_MQTT_IP` / `RASPBERRY_IP` / `SSH_HOST`, **certificat toujours vérifié avec le nom** (sous-classe paho, équivalent de `extra_hosts`). Client id `sentinel-x-api` (≠ leur `sentinel-backend`).
- Journal : `pimqtt.connected|disconnected|error|invalid|cyber|status` (la télémétrie ne va qu'en base). État dans `context()` (`piMqtt`) et `GET /api/pi-mqtt` (+ derniers `events`). **Pas d'affichage dans le dashboard.** Testé en réel le 9 octobre contre le Pi (TLS, stockage, ACK OK). Tests : `tests/test_pi_mqtt.py`.

### Analyse (`ai/`) — `ANALYZER=mock|local`
Contrat : `analyze(snapshot) -> {detections:[{label,confidence,bbox{x,y,w,h},polygon?}], threat:{score 0-100,label}, environment?}` — **synchrone** (appelée dans un thread).
- `mock_analyzer.py` : faux modèle (déduit une « personne » de la tache chaude de la matrice + ultrason, latence 150–400 ms simulée).
- `local_analyzer.py` : détections **YOLO réelles** (`vision.latest_detections()`, vides si > 2 s) + `EnvDetector` + `threat_score`.
- `threat.py` : **score de menace = 40 % personne (confiance YOLO) + 20 % proximité ultrason + 10 % PIR (ESP8266, 0 si `EDGE=off`) + 15 % chaleur + 15 % anomalie d'environnement**, puis deux **planchers** qui ne s'additionnent pas : **gaz** `max(somme, 70 × risque gaz)` (risque = 0 sous la moitié de `GAS_ALERT_RAW`, 1 au seuil ; seulement avec un Edge Node) et **personne confirmée** (confiance ≥ `thresholds.person_confidence` = 0,6, le seuil de l'alerte d'intrusion) ⇒ `max(score, 60 + round(10 × confiance))` = « Menace ». Sans ce dernier la caméra seule plafonnait à 40. Constantes `VIGILANCE_FROM` = 30, `MENACE_FROM` = 60, `GAS_FLOOR_AT_THRESHOLD` = 70 ; heure via `clock.now_ms`. Tests : `backend/tests/test_threat.py`.
- `clock.py` : `now_ms()`, l'heure en millisecondes ; **seule définition**, importée par `hub`, `db`, `alerts`, `edge`, `providers/mock`, `vision/service`, `ai/threat`.
- `env_anomaly.py` : détecteur d'anomalies DHT22 **en ligne**, sans dépendance (z-score glissant sur température, humidité, pentes ; apprentissage 30 mesures ≈ 1 min ; garde-fous : > 45 °C ou +2 °C/min ⇒ 100, air proche de la saturation ⇒ ≥ 70). Sortie `{score,label Apprentissage|Normal|Inhabituel|Anomalie,dewPointC,reasons[],learning}`.
  Le vrai modèle (Isolation Forest, `ml/environment/env_model.py`) **n'est pas branché** : à intégrer dans `LocalAnalyzer`.

### Vision (`vision/`) — `VisionService` (thread dédié, démarre seulement avec `ANALYZER=local`)
- Sources commutables à chaud : **caméra du backend** (`VISION_SOURCE` = `0`, URL, ou fichier vidéo rejoué en boucle) ou **images poussées** (`browser` / `push` ⇒ `/ws/camera`, `push_frame`, dernier-gagnant). Passer en mode navigateur **relâche la caméra du backend**.
- `YoloDetector` (ultralytics) : classe « person » seule, `result.boxes` + silhouettes (`result.masks.xyn` simplifiées par Douglas-Peucker ≤ 60 points avec `yolov8n-seg.pt`), verrou (modèle non thread-safe), poids téléchargés dans `backend/models/` s'ils manquent. Modèle par défaut `yolov8n.pt` ; les configs F5 YOLO utilisent `yolov8n-seg.pt` + `YOLO_IMGSZ=480`.
- États : `loading` · `running` · `waiting` (mode push sans image depuis 3 s) · `error` · `stopped` ; message WS `vision`.
- **Photos d'intrusion** : à la première détection, puis à chaque **nouveau palier** du nombre de personnes, avec **latence de confirmation** `CAPTURE_SETTLE_S` (1,5 s) : on garde l'image montrant le plus de personnes et on prend **une photo**
  (un clignotement 2-3-2-3 = 1 photo ; 2-3 puis 3-4 = 2 photos). < 3 images de détection = bruit. Le niveau ne redescend qu'après `INTRUSION_TIMEOUT_S` (3 s) sans le revoir ; l'intrusion se termine après ce délai sans détection.
  **En `APP_ENV=dev` aucune photo n'est écrite** (`VisionService` reçoit `captures_dir=None`, l'événement n'a pas de `snapshot`). Photo allégée (640 px, JPEG q70, progressif ≈ 15 Ko), nom `intrusion_<date>_<ms>_<N>p.jpg` dans `backend/data/captures/` (ignoré par git), servie par `GET /api/captures/{nom}` (compte requis).
- **Clips vidéo** (`vision/recorder.py`, `ClipRecorder`) : un MP4 **H.264** (PyAV / libx264, CRF 28, preset veryfast, 640 px, faststart) **de la première détection à la fin de l'intrusion**, avec **2 s de pré-enregistrement** (`RECORD_PREROLL_S`) ; images horodatées (durée réelle respectée) ; clip coupé en parties `_p2`… au-delà de `RECORD_MAX_S` (180 s) ; **clip supprimé si la détection n'a jamais été confirmée** (bruit) ; quota `RECORD_KEEP_MB` (plus anciens supprimés, le dernier toujours gardé). **Résistant aux plantages** : écriture en MP4 **fragmenté** dans `<nom>.mp4.part` (image clé / fragment toutes les 20 images ≈ 2 s, écriture disque au fil de l'eau) ; fermeture normale ⇒ conversion sans ré-encodage en MP4 classique (`faststart`) et suppression du `.part` ; plantage ⇒ le `.part` reste lisible (perte ≤ ~2,5 s, mesurée en tuant le processus) et `ClipRecorder.recover()` (appelé au démarrage de `VisionService`) le convertit en `<nom>_interrompu.mp4` + événement `vision.clip` avec `recovered: true` (niveau warning). L'arrêt normal du service ferme le clip en cours. Les `.part` sont cachés de `GET /api/videos`. Mesuré : ≈ 46 Ko/s ≈ 2,7 Mo/min en 640×480. Dossier `backend/data/videos/` (`VIDEOS_DIR`). Actif en `prod` ; en `dev` désactivé sauf `RECORD_VIDEO=1`. Sans le paquet `av`, désactivé avec un avertissement. Événement du journal `vision.clip` (nom, fichier, poids, durée, images, fps, codec, url). Routes : `GET /api/videos` (liste) et `GET /api/videos/{nom}` (compte requis, lecture progressive Range). **Pas encore d'affichage dans le dashboard** (ni de lien dans l'alerte : la table `alerts` n'a pas de colonne vidéo).
- Message vidéo `/ws/video` : `[4 octets : taille N de l'en-tête, big-endian][N octets JSON {ts,width,height,annotated,personCount,detections,threat}][JPEG]`. Par défaut l'image est **brute** et le front dessine ; `VISION_ANNOTATE=1` = YOLO incruste ses dessins.
- `POST /api/vision/analyze` (admin) : image en entrée (corps JPEG/PNG) → détections + menace (+ image annotée en base64 avec `?annotated=true`).

### Journal JSON centralisé (`logger.py`)
- **Un seul point d'entrée** : `from .logger import logger` puis `logger.emit("domaine.action", "message", level="info|warning|error|critical", **données)`. `logger.setup()` (dans `main.py`) configure la console et recopie dans le fichier tout `logging` ≥ WARNING (y compris uvicorn / asyncio et les exceptions non gérées).
- Fichier : `backend/data/logs/events-AAAA-MM-JJ.jsonl` (JSON Lines, un fichier par jour, dossier `LOG_DIR`). **Une ligne** = `ts` (ISO) · `tsMs` · `seq` · `level` · `event` · `message` · `env` · `data` (détails de l'événement) · **`context`** (état complet : dernier snapshot capteurs complet dont la matrice thermique, analyse IA, état vision, alertes actives, santé des modules, clients connectés).
- Événements : `app.start|stop` · `audit.*` (hook dans `Database.audit` : connexions, échecs, comptes, moteur, source vidéo, scénarios ; IP dans le détail) · `http.denied|error` (401/403/429/5xx ; le 401 de `/api/auth/me` est ignoré) · `ws.connect|disconnect|refused|session_closed` · `camera.push_connect|disconnect` · `vision.intrusion|new_person|intrusion_ended|status` (détections sans polygones, taille d'image, modèle, source, `snapshotSaved`, chemin et taille de la photo en `prod`) · `vision.clip` · `alert.created|resolved` · `analysis.recovered` · `module.lost|recovered` · **`monitor.snapshot`** (relevé périodique `MONITOR_INTERVAL_S`, 60 s par défaut, même sans événement) · `log.warning|error|critical`.
- Écriture protégée par un verrou et jamais bloquante (toute erreur d'écriture est avalée). **Pas de rotation / purge** des anciens fichiers. Lecture : `Get-Content backend\data\logs\events-*.jsonl -Wait | ConvertFrom-Json`.

### Santé des modules (`modules.py`, `Hub._watch_modules`)
`ModuleMonitor` (logique pure, sans I/O) évalue chaque seconde : `raspberry` (aucun snapshot depuis `MODULE_TIMEOUT_S` = 5 s), `ultrasonic` / `thermal` / `motor` (clé absente ou invalide dans le snapshot), `dht22` (aucune mesure, ou `readAt` plus vieux que `DHT_STALE_S` = 30 s), `camera` (état vision `error`, ou `waiting` après avoir tourné ; l'attente d'une première connexion et un changement de source voulu par l'admin ne comptent pas : `hub.monitor.reset_camera()`), `ai` (analyse `ok:false`).
Raspberry perdu ⇒ ses capteurs sont « indéterminés » (une seule perte signalée). États `ok | lost | unknown` ; transitions ⇒ `module.lost` (error) / `module.recovered`, **alerte** `module_<nom>` « Perte de connexion : … » (critical pour Pi et caméra, warning pour le reste, résolue au retour), console rouge / verte. `GET /api/modules` (compte requis) donne l'état.
Un capteur muet ne fait plus planter le hub (`_sensor_point`, `evaluate_sensors`, `threat_score`, faux analyseur tolèrent une clé absente). **Le front n'a pas été vérifié avec un capteur muet.**

### Alertes (`alerts.py`)
Une alerte part au passage « condition fausse → vraie ». Règles : **proximité** (< 80 cm, warning) et **chaleur** (maxC > 45 °C, warning) sur la donnée brute (immédiat, marchent sans IA) ; **anomalie d'environnement** (score DHT22 ≥ 70, warning) via l'analyse ;
**perte de connexion d'un module** (`module_*`, voir ci-dessus) ; **intrusion** (critical, avec `snapshot` = URL de la photo, absent en `dev`) : issue des événements de la vision quand elle est active (`intrusion` / `new_person`), sinon de l'analyse (personne ≥ 0,6). Les alertes sont **enregistrées en base** et rechargées au démarrage.

### Comptes, base, sécurité (`auth.py`, `db.py`, `cli.py`)
- Rôles : **admin** (tout : moteur / position de la caméra, source vidéo, simulations, `analyze`, gestion des comptes, audit) · **agent** (consultation seule). Seul `GET /api/health` est public. Droits **vérifiés côté serveur** (403 agent, 401 non connecté).
- Choix assumé : **session serveur à jeton opaque, révocable, pas de JWT** (révocation immédiate, y compris des flux ouverts ; OWASP Session Management). Écarts connus : voir `etat-et-decisions.md`.
- Mots de passe : scrypt (stdlib). Session : jeton aléatoire en cookie `sentinel_session` (HttpOnly, SameSite=Lax), **seule son empreinte SHA-256 en base**, durée `SESSION_HOURS` (12). 5 échecs / 5 min par couple adresse+identifiant ⇒ 429.
  Identifiants insensibles à la casse (index d'unicité sur `lower(username)`).
- WebSocket : `/ws` et `/ws/video` exigent la session (refus : accept puis `close(4401)`). `/ws/camera` : **admin connecté** ou **jeton d'appareil** `?token=<DEVICE_TOKEN>` (le Pi). 4403 = rôle insuffisant.
- Base : SQLAlchemy 2, **SQLite par défaut** (`backend/data/sentinel.db`), **PostgreSQL** avec `DATABASE_URL=postgresql+psycopg://…` (testé sur postgres:17). Tables : `users`, `sessions`, `alerts`, `audit_log` (connexions, échecs, moteur, source vidéo, simulations, comptes).
- `python -m app.cli list|create <id> <admin|agent>|passwd <id>` (récupération).

### API
REST : `/api/health` (public) · `/api/auth/{login,logout,me}` · `/api/snapshot|analysis|vision|history|alerts|modules|videos` · `/api/captures/{nom}` · admin : `POST /api/motor`, `/api/vision/source` (`{mode:'browser'|'default'}`), `/api/vision/analyze`, `/api/mock/{intruder|heat|window}`, `/api/users` (+ `DELETE /{id}`, `POST /{id}/password`), `/api/audit`.
WebSocket JSON `/ws` : `hello` (état complet : provider, snapshot, analysis, vision, history{sensors,threat}, alerts) · `snapshot` · `analysis` · `alert` · `motor` · `vision`. Détails et exemples dans `README.md`.

### Configuration (`config.py`, variables d'environnement ou `backend/.env`)
`PROVIDER` (mock|ssh) · `SSH_HOST|PORT|USER|KEY|PASSWORD|KNOWN_HOSTS|COMMAND` · `STREAM_URL` · `AGENT_LOCAL` · `ABSENT_MODULES` · `ANALYZER` (mock|local) · `TICK_MS` · `VISION_SOURCE` · `YOLO_MODEL` · `YOLO_CONF` (0.5) · `YOLO_IMGSZ` (640) · `VISION_FPS` (10) · `VISION_ANNOTATE` · `INTRUSION_TIMEOUT_S` (3) · `CAPTURE_SETTLE_S` (1.5) ·
`CAPTURE_MAX_WIDTH`/`CAPTURE_JPEG_QUALITY` (640/70) · `CAPTURES_DIR` · **`APP_ENV`** (dev|prod) · **`LOG_DIR`** · **`MONITOR_INTERVAL_S`** (60) · **`RECORD_VIDEO`** (auto) · `RECORD_PREROLL_S` · `RECORD_CRF` · `RECORD_MAX_WIDTH` · `RECORD_MAX_S` · `RECORD_KEEP_MB` · `VIDEOS_DIR` · **`MODULE_TIMEOUT_S`** (5) · **`DHT_STALE_S`** (30) · `DATABASE_URL` · `ADMIN_USERNAME`/`ADMIN_PASSWORD` · `AGENT_USERNAME`/`AGENT_PASSWORD` (champs de config présents ; **la création automatique de l'agent n'est plus dans `bootstrap_admin`** : voir l'état) · `DEVICE_TOKEN` · `SESSION_HOURS` · `COOKIE_SECURE`. Seuils d'alerte dans `Thresholds` (80 cm, 45 °C, 0.6, score DHT22 70).

## 3. Frontend (`frontend/`)

React 18 + Vite 6 + Ant Design 6 (thème sombre, textes en français). `App.jsx` = **porte d'entrée** : vérifie la session (`useAuth`), sinon `LoginPage` ; rien du dashboard n'est chargé sans compte. `Dashboard.jsx` = grille de panneaux selon le rôle.
- Panneaux : `CameraPanel` (canvas) · `ThreatPanel` (score en différé) · `SystemPanel` · `UltrasonicPanel` (radar orienté selon l'angle du moteur) · `ThermalPanel` (heatmap 8×8) · `EnvironmentPanel` (DHT22) · `MotorPanel` (admin ; `readOnly` pour un agent) · `AlertsPanel` (miniatures des photos) · `UsersPanel` (admin : comptes + audit). Graphiques = SVG maison (`ui.jsx`).
- Hooks : `useSentinel` (WS `/ws`, reconnexion à backoff, état global) · `useVideoStream` (WS `/ws/video`, décode l'en-tête + JPEG, dessine sur le canvas) · `useWebcamUpload` (envoie la webcam du navigateur sur `/ws/camera`, ~8 img/s, avec retries si la caméra est occupée) · `useAuth`.
- `components/drawOverlay.js` : dessine l'image puis **carrés rouges, silhouettes, étiquettes, bandeau « INTRUSION DETECTED », « N PERSONNES DÉTECTÉES » et chip menace**. **Vue miroir** (`MIRROR = true` : image et positions retournées, textes lisibles) ; mettre `false` pour la caméra du Pi.
- **Thème « labo de Gru » (9 octobre)** : jetons CSS dans `styles.css` (`--accent` jaune, `--neon` bleu de la grille, `--danger`…) et thème Ant dans `main.jsx` (polices Bricolage Grotesque / Geist / Geist Mono, via `@fontsource-variable/*`, donc hors ligne). Le fond est une **grille néon** (`body::before` fixe + `body::after` en halo qui respire) ; l'alerte ambiante est `.app-shell::before` (`data-mood` = `calme|vigilance|menace|offline` sur `.app-shell` ; pulsation rouge en menace).
  - `components/Minion.jsx` : mascotte **SVG maison** (aucun asset officiel), memoïsée ; pupilles qui suivent le curseur, clignement, `data-mood` pilote bouche / sourcils / bras / **trois gyrophares** (côtés + dessus à la place des cheveux, en menace) / aura rouge, `shy` (yeux fermés pendant la saisie du mot de passe), `offline` = il dort. Page de connexion : le Minion se fâche et la carte tremble si le mot de passe est refusé.
  - `threat.js` : **source unique** des niveaux de menace (`THREAT_LEVELS` : ton, couleur, humeur) et des couleurs d'état (`STATUS_COLORS`, miroir des variables CSS car les canvas ne les lisent pas) ; `MOOD_SAYINGS` = phrases de la mascotte (« Bello ! », « Bee-do bee-do ! »).
  - `hooks/useAlarm.js` : sirène « bee-do » **synthétisée** (Web Audio, un contexte par alerte, fermé ensuite), jouée pendant l'humeur `menace` ; bouton haut-parleur dans l'en-tête, choix mémorisé dans `localStorage` (`sentinel.alarmSound`) ; ne joue qu'après un clic de l'utilisateur (la connexion compte). **Son non écouté par Claude** (tests en headless).
  - Perf : seules `opacity` et `transform` sont animées (pas de `filter` ni `box-shadow` animés) ; `prefers-reduced-motion` coupe les animations ; les panneaux (`.panel`) ont une lueur qui suit la souris (`--mx` / `--my`, `@property` non héritées) et le corps des cartes remplit la hauteur (`.alert-list` défile au lieu d'agrandir la ligne).
  - `EdgePanel` (gaz / PIR) n'apparaît que si le backend renvoie un `edge` (donc jamais avec `EDGE=off`).
- `api.js` : `getJson/postJson/deleteJson` ; une réponse 401 déclenche l'événement `AUTH_EXPIRED` ⇒ retour à la page de connexion (WS fermée en `4401` idem).
- `vite.config.js` : proxy `/api`, `'^/ws$'` (événements, logue la connexion en vert/rouge dans le terminal), `'^/ws/(video|camera)$'` ; `API_PORT` pour viser un autre port de backend.
- Interface selon le mode vision : `vision.source` = `browser` ⇒ interrupteur « Webcam PC » (admin) ; `push` ⇒ « caméra du Raspberry », pas d'interrupteur ; sinon caméra du backend. Un agent ne peut ni changer la source ni envoyer sa webcam.

## 4. Raspberry Pi (`raspberry-pi/`) et atelier IA (`ml/`)

- `dht22_reader.py` : lit le DHT22 (GPIO4, une mesure / 2 s, pilote noyau `dtoverlay=dht11,gpiopin=4` ou Adafruit), imprime `{"tempC","humidityPct","readAt"}` par ligne (= champ `environment`). `--csv` journalise des données d'entraînement. Câblage : 3,3 V (**pas 5 V**), GPIO4, GND.
- `camera_push.py` : capture (picamera2 par défaut, webcam USB ou fichier vidéo via OpenCV) → JPEG → WebSocket `ws://<pc>:4000/ws/camera?token=…`. Capture juste avant d'envoyer (pas de retard cumulé), reconnexion. **Testé uniquement avec un fichier vidéo ; la partie picamera2 est écrite d'après la doc, non vérifiée sur un vrai Pi.**
- `ml/vision/` : `webcam_test.py`, `yolo_intrusion.py` (démos autonomes de l'équipe IA ; mêmes poids que le backend). `ml/environment/env_model.py` : Isolation Forest (`train|score|demo`) sur le DHT22, **non branché**.
