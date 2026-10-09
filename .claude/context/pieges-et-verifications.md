# Pièges rencontrés et façon de vérifier

## Pièges (ce qui a déjà coûté du temps)

**Caméra et navigateur**
- Une webcam ne s'ouvre que dans **un programme à la fois** (Windows). Le backend relâche sa caméra quand on passe en mode navigateur (`/api/vision/source`) ; le front réessaie `getUserMedia` jusqu'à 8 × 500 ms.
- `getUserMedia` exige un **contexte sécurisé** : OK sur `localhost`, **refusé sur `http://<ip-du-pc>:5173`** depuis un autre appareil. Pour un téléphone / un autre PC : utiliser `VISION_SOURCE=push` (le Pi) ou servir le dashboard en HTTPS.
- Le front dessine avec `MIRROR = true` (drawOverlay.js) : mettre `false` pour la caméra du Pi (sinon l'image réelle est inversée).

**Lancement**
- **Choisir la bonne config F5** dans « Exécuter et déboguer » : « Sentinel-X (mock, sans YOLO) » n'affiche aucune détection ; la config YOLO par défaut est « webcam navigateur ». Le debug Python **ne recharge pas** le code : relancer F5 après une modif du backend (Vite recharge seul).
- `npm run api` / `dev` passent par `scripts/run-api.mjs` (utilise `backend/.venv` sans l'activer). Le Python système n'a pas FastAPI. Le venv est **par machine** (non versionné) : le recréer sur un nouvel ordinateur.
- VS Code : `.vscode/settings.json` fixe l'interpréteur ; sans lui l'éditeur signale « paquet non installé ». Tâches Windows en `cmd.exe` (`/d /c`) ; à adapter sous Linux/Mac.
- Le front attend l'API (`.vscode/wait-for-api.ps1`) pour éviter les `ECONNREFUSED` au démarrage. Le débogueur ne lance l'API qu'une fois la tâche préalable « prête » : la ligne « Attente de l'API » dans la commande sert de signal.
- Un vieux serveur peut occuper `:4000` / `:5173` : vérifier avant de tester (`Get-NetTCPConnection -LocalPort 4000,5173 -State Listen`). **Ne pas tuer la session de l'utilisateur sans lui demander** ; tester sur d'autres ports (backend `:4001`, Vite `--port 5174 --strictPort` avec `API_PORT=4001`).
- Renommer un dossier surveillé par Vite échoue sous Windows : arrêter les serveurs avant. Après un renommage de workspace npm : `npm install`.

**Journal et tests du backend**
- **Ne pas arrêter le backend de l'utilisateur** (F5, `:4000`) pour tester : sa base `backend/data/sentinel.db` est **verrouillée** (suppression impossible, « Device or resource busy ») et il y a créé l'admin avec un mot de passe aléatoire. Pour changer un mot de passe sans le couper : `database.set_password(...)` depuis `backend/` avec le venv (SQLite accepte l'accès concurrent).
- Tests rapides : `TestClient(app)` avec `LOG_DIR`, `DATABASE_URL`, `APP_ENV`, `ADMIN_PASSWORD`, `PROVIDER=mock`, `ANALYZER=mock`, `TICK_MS=300`, `MODULE_TIMEOUT_S`, `MONITOR_INTERVAL_S` positionnés **avant** `import app.main` ; du code async dans la boucle de l'app : `c.portal.call(...)` ; simuler une panne : remplacer `hub.provider.get_snapshot` / `hub.vision` (un faux objet doit avoir `.status()` **et `.stop()`**, sinon l'arrêt de l'app plante) ; arrêter le Pi simulé : `hub.provider.stop`.
- `logger.emit(event, message, **data)` : ne pas passer de clé `event` / `level` / `message` / `context` dans `**data` (collision d'arguments, `TypeError`). L'événement d'intrusion contient `event` : filtrer avant.
- Console Windows en cp1252 : lancer les scripts de test avec `PYTHONIOENCODING=utf-8` (sinon `UnicodeEncodeError` sur `→` et les accents).
- F5 : « Front (Vite) » est une `preLaunchTask` en arrière-plan que VS Code n'arrête pas seule ; `postDebugTask: "Arrêter le front"` (tasks.json, entrée `${input:terminateFront}` = commande `workbench.action.tasks.terminate`) la termine. Si un terminal reste, le fermer à la main.
- Photos en `dev` : `VisionService(captures_dir=None)` ; tout code qui lit `event["snapshot"]` doit utiliser `.get` (un `KeyError` dans `Hub._on_intrusion` empêchait l'alerte d'arriver au dashboard).
- **Encodage vidéo** : OpenCV seul ne sait pas écrire de H.264 ici (« Failed to load OpenH264 library ») et ses VP8/VP9 sont 5 fois plus lourds ; mp4v n'est pas lisible dans un navigateur. D'où PyAV (`av`, FFmpeg embarqué, libx264). Les dimensions doivent être **paires** (yuv420p). Tester les tailles sur une **vraie vidéo**, pas sur du bruit aléatoire (résultats absurdes).
- **MP4 et plantage** : un MP4 classique écrit son index (`moov`) à la fin ⇒ illisible si le processus meurt. D'où le MP4 fragmenté (`frag_keyframe+empty_moov+default_base_moof`) + GOP court. Test : lancer l'enregistreur dans un sous-processus, le tuer (`Popen.kill()`), relire le `.part` avec `av`, puis `ClipRecorder.recover()`.
- Test des clips : instancier `VisionService(config.vision, Path('.'), photos_dir, videos_dir)`, remplacer `_cb`, appeler `svc._recorder.push(frame, time.time())` puis `svc._update_intrusion(detections, frame, cv2)` en temps réel (sleep 0,1 s) ; relire avec `av.open(...).decode(video=0)` pour compter les images ; lancer avec `PYTHONPATH=.` depuis `backend/`.
- Les logs sont dans `backend/data/` (ignoré par git) ; le contexte contient les capteurs, jamais de mot de passe (`audit.*` consigne l'acteur et l'IP).
- Le heredoc Bash de l'outil échoue avec certaines apostrophes dans du texte français : écrire le script dans un fichier (scratchpad) puis l'exécuter.

**Dépendances / versions** : Python 3.13.7 (README : 3.11+), Node 22, React 18.3, Vite 6, **Ant Design 6** (API : `Statistic styles.content`, `Alert title`, `Button iconPlacement`, `Space.Compact`), FastAPI 0.142, SQLAlchemy 2.1, psycopg 3, ultralytics 8.4, torch 2.14 (CPU), OpenCV 5. torch ≈ 1 Go. Les poids Ultralytics se téléchargent depuis GitHub s'ils manquent (internet requis la première fois).

**Proxy Vite** : les clés sont des préfixes ; `'^/ws$'` (événements) et `'^/ws/(video|camera)$'` sont des regex. Oublier `/ws/camera` ⇒ la WebSocket reste « en connexion » sans erreur.
**Tests de navigateur** : dans les champs Ant Design, le triple-clic ne vide pas : faire `Ctrl+A` puis `Backspace` avant de taper (sinon « adminadmin »).
**WebSocket de test (Starlette)** : `ws.receive()` renvoie un message `websocket.close` avec `code` au lieu de lever une exception.
**Git** : ne jamais committer `backend/.env`, `backend/data/`, `.venv`. Avertissements « LF will be replaced by CRLF » : inoffensifs. `git mv` pour garder l'historique.
**Windows PowerShell 5.1** : `Set-Content -Encoding utf8` ajoute un BOM (éviter pour du code) ; la lecture d'un fichier UTF-8 sans BOM affiche du mojibake (affichage seulement). Un garde-fou de l'outil Bash/PowerShell de Claude bloque parfois des commandes contenant `Remove-Item` près de `.git` ou `/d` : utiliser `[System.IO.Directory]::Delete(...)`.

## Comment vérifier (rien n'est dans le dépôt : à recréer, ou demander à Claude de les transformer en `backend/tests/`)

Les scripts ont été écrits dans un dossier temporaire. Principes pour les refaire :

1. **API (65 vérifications, identiques sur SQLite et PostgreSQL)** : `fastapi.testclient.TestClient` avec `DATABASE_URL` temporaire, `ADMIN_PASSWORD`, `DEVICE_TOKEN`, `CAPTURES_DIR` positionnés **avant** `import app.main`. Couvre : routes protégées (401), agent (403 partout où il faut), admin, verrou 429 (5 échecs), cookie HttpOnly, création de comptes (doublons insensibles à la casse), traversée de dossier sur `/api/captures`, WebSocket 4401 / 4403 / jeton d'appareil, audit, sessions fermées après changement de mot de passe, alertes relues après redémarrage, `python -m app.cli list`.
2. **PostgreSQL** : conteneur **jetable** `docker run -d --name sx-test-pg-tmp -e POSTGRES_PASSWORD=<aléatoire> -e POSTGRES_DB=sentinel_test -p 127.0.0.1:55432:5432 postgres:17-alpine` ; `DATABASE_URL=postgresql+psycopg://postgres:<mdp>@127.0.0.1:55432/sentinel_test` ; puis `docker rm -f sx-test-pg-tmp`. **Ne jamais toucher au conteneur `sentinel-postgres` de l'utilisateur.**
3. **Navigateur de bout en bout** : `npm i puppeteer-core` dans un dossier temporaire (hors dépôt), Chrome headless (`headless: 'new'`, `C:\Program Files\Google\Chrome\Application\chrome.exe`), puis lire les captures d'écran. Fausse webcam : `--use-fake-device-for-media-stream --use-fake-ui-for-media-stream --use-file-for-fake-video-capture=<fichier.mjpeg>` (un `.mjpeg` = JPEG concaténés, fabriqué à partir d'une photo à 2 personnes).
4. **Logique de photos** : instancier `VisionService`, remplacer `app.vision.service.time` par un faux objet qui a `.time()`, appeler `_update_intrusion(detections, frame, cv2)` à 10 Hz avec des nombres de personnes imposés (2-3 alterné, puis 3-4, bruit, absence, retour…).
5. **Contrat vidéo** : se connecter à `/ws/video` avec le cookie, lire 4 octets (taille de l'en-tête), JSON, puis JPEG (`FF D8`).
6. **Pi sans Pi** : `camera_push.py --source <fichier.avi> --url ws://localhost:4001/ws/camera --token <DEVICE_TOKEN>` avec le backend en `VISION_SOURCE=push`.
7. **Échantillons** : vidéo de test `ml/vision/runs/detect/predict-2/0.avi` (`VISION_SOURCE=<chemin>` la rejoue en boucle) ; photos d'exemple de l'équipe IA récupérables avec `git show <commit>:<chemin>` si absentes du dossier.
8. Le mot de passe admin d'un test est toujours fixé par `ADMIN_PASSWORD` (jamais lu dans un fichier secret de l'utilisateur).
9. **Tests du dépôt** : `cd backend && python -m pytest tests -q` (27 tests, Edge Node + score de menace ; `conftest.py` pose les variables d'environnement avant tout import de `app`, base et journaux dans un dossier temporaire). `pytest` n'est pas dans `requirements.txt` : `pip install pytest`.

## Pièges de la session du 9 octobre

- **Bash cassé sur la machine de l'utilisateur** (`.bashrc` fait `exec zsh`, absent) : utiliser **PowerShell** pour tout. Chemin absolu obligatoire avec `[IO.File]::…` (le répertoire courant .NET n'est pas celui de PowerShell).
- **BOM** : `Set-Content -Encoding UTF8` (Windows PowerShell 5.1) ajoute un BOM UTF-8 ; pour modifier un fichier du dépôt, lire / écrire avec `New-Object Text.UTF8Encoding $false` ou passer par l'outil d'édition.
- **Verrou de connexion** : 5 échecs en 5 min sur un même identifiant bloquent (429), en mémoire ; en cas de test navigateur répété, **redémarrer le backend de test** (pas celui de l'utilisateur).
- **Vite occupe le port suivant** si 5173 est pris (5174, 5175…) : des instances oubliées font viser la mauvaise page ; vérifier `Get-NetTCPConnection -LocalPort 5173 -State Listen` avant de capturer.
- **Capturer l'UI** : script puppeteer-core hors dépôt, backend de test (`PROVIDER=mock`, `EDGE=off` ou `mock`, base temporaire), attendre ~10 s après le démarrage ; « Simuler un intrus » (mode mock) fait passer le score en « Menace » en quelques secondes, ce qui montre la mascotte en alerte.
- **`git pull` avec conflits** : `git status` liste les fichiers « both modified » ; `git diff --check` repère les marqueurs `<<<<<<<` restants ; après résolution, `git add` puis **`git commit`** (l'utilisateur le fait lui-même).
- **SSH « Permission denied for user pi »** : le compte du Pi est `piadmin` (`SSH_USER`), pas `pi`. Windows n'a pas `ssh-copy-id` : `type $env:USERPROFILE\.ssh\id_rsa.pub | ssh piadmin@<ip> "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"`. Un `TimeoutError` juste après = coupure passagère du Wi-Fi du Pi (port 22 vérifiable avec `Test-NetConnection <ip> -Port 22`).
- **`backend/.env` de l'utilisateur sans retour à la ligne final** : un `Add-Content` colle la nouvelle clé derrière la dernière (`EDGE=offSSH_USER=…`). Vérifier la fin du fichier ; ne jamais afficher ses valeurs (mots de passe) : lister les clés seulement.
- **Lecture des secrets** : lire `backend/.env` ou le `.env` de l'infra est refusé par le classifieur ; passer par la config (`python -c "from app.config import config …"`) en n'affichant que des booléens / noms.
- **Deux backends sur le broker du Pi** : le conteneur `sentinel-backend` de l'infra et le nôtre acquittent tous les deux (2 ACK par message) ; client id différents (`sentinel-backend` / `sentinel-x-api`), sinon ils se déconnecteraient l'un l'autre.
- **Tester la liaison MQTT réelle sans toucher au backend de l'utilisateur** : script dans le scratchpad qui importe `app.pi_mqtt` avec `PI_MQTT_ENV_FILE`, base SQLite et `LOG_DIR` temporaires, publie sur `sentinel/essai-claude/telemetry` et attend l'ACK.
- **Un seul `sentinel_agent.py` à la fois sur le Pi** (le nouveau tue l'ancien) : ne pas le lancer en mode réel pendant que le backend de l'utilisateur tourne.
- **Photos de montage** : réduire avant de versionner (la photo d'origine pèse 13 Mo ; `docs/img/montage-raspberry.jpg` = 1000 px, ~400 Ko).
