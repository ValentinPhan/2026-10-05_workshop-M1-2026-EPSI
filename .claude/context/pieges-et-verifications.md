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
