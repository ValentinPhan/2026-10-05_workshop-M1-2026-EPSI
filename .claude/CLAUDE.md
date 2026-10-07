# Sentinel-X — contexte du projet pour Claude

Ce fichier est chargé automatiquement par Claude Code. Il permet de **reprendre le travail sur n'importe quel ordinateur**
sans la conversation d'origine. Détails dans `.claude/context/` (importés ci-dessous).

## En deux phrases

Sentinel-X = boîtier de surveillance autonome pour le workshop M1 2026 de l'ESPI (concours inter-écoles, scénario « AetherCorp 2050 »).
Un **Raspberry Pi** (capteurs ultrason, matrice thermique 8×8, DHT22 température/humidité, caméra, moteur de rotation) envoie de la donnée
brute au **PC** qui héberge un **backend Python** (FastAPI + YOLO + base de données), lequel alimente un **dashboard React** temps réel.

- Dépôt GitHub : `ValentinPhan/2026-10-05_workshop-M1-2026-EPSI` (branche `main`). Équipe de 6 : dev (Noam, git `N0amG`, utilisateur principal de Claude), 3 IA (dont Silya pour YOLO), infra/cloud, cyber (Valentin a poussé le DHT22).
- Calendrier : lundi 5 → **soutenance locale vendredi 9 octobre 2026**, puis qualifications nationales si qualifiés (l'architecture doit rester évolutive).
- Objectif : **podium**. Le jury note aussi le non-technique (teaser, pitch, rapport) : voir `context/projet.md`.

## Arborescence

```
backend/        API FastAPI + vision YOLO + comptes/BDD          (tourne sur le PC)
  app/          main.py hub.py alerts.py config.py auth.py db.py cli.py console.py
                logger.py (journal JSON centralisé) · modules.py (santé des modules : perte de connexion)
    providers/  mock.py (Pi simulé) · ssh.py (À IMPLÉMENTER) · motor.py
    vision/     service.py (caméra+YOLO en thread) · detector.py
    ai/         mock_analyzer.py · local_analyzer.py · threat.py · env_anomaly.py
  models/       poids YOLO (yolov8n.pt, yolov8n-seg.pt, yolo26n.pt)
frontend/       dashboard React 18 + Vite 6 + Ant Design 6 (thème sombre)
raspberry-pi/   scripts qui tournent sur le Pi : dht22_reader.py, camera_push.py
ml/             atelier IA hors ligne : vision/ (tests YOLO), environment/ (Isolation Forest DHT22)
scripts/        run-api.mjs (lance le backend avec le venv, sans l'activer)
.vscode/        F5 = back (debug Python) + front ; tâches ; settings (interpréteur = backend/.venv)
.claude/        ce contexte
```

## Démarrer (nouvel ordinateur)

```bash
git clone https://github.com/ValentinPhan/2026-10-05_workshop-M1-2026-EPSI.git && cd 2026-10-05_workshop-M1-2026-EPSI
npm install
cd backend && python -m venv .venv
.venv\Scripts\activate                          # Linux/Mac : source .venv/bin/activate
pip install -r requirements.txt -r requirements-vision.txt   # vision = torch, ~1 Go ; ajouter ../ml/environment/requirements.txt si besoin
cp .env.example .env                            # optionnel : APP_ENV, DATABASE_URL, ADMIN_PASSWORD, DEVICE_TOKEN, LOG_DIR
cd .. && npm run dev:yolo                       # ou F5 dans VS Code (config « Sentinel-X + YOLO (webcam navigateur) »)
```

- Dashboard : http://localhost:5173 ; API : http://localhost:4000 (`/docs` = documentation interactive).
- **Premier lancement** : le compte `admin` est créé et son mot de passe aléatoire est **affiché une seule fois dans la console du backend**
  (ou fixé par `ADMIN_PASSWORD`). Perdu : `cd backend && python -m app.cli passwd admin`.
- **`APP_ENV=dev|prod`** (défaut `prod` ; `backend/.env` de l'utilisateur est en `dev`) : en `dev`, **aucune photo d'intrusion enregistrée** (l'alerte est créée sans image, log « mode dev activé : capture d'écran désactivée »). Mettre `prod` pour la soutenance.
- **Journal JSON** : `backend/data/logs/events-AAAA-MM-JJ.jsonl` (une ligne JSON par événement, avec l'état complet de l'application) ; voir `architecture.md`, § Journal.
- Modes : `npm run dev` = mock (aucun YOLO) ; `npm run dev:yolo` = YOLO sur la webcam du navigateur. Variables dans `README.md`.
- Windows : les tâches VS Code utilisent `cmd.exe` et `backend\.venv\Scripts\python.exe` ; sur Linux/Mac, adapter `.vscode/` (chemins `Scripts` → `bin`).

## Comment travailler avec l'utilisateur (à respecter)

- **Répondre en français, direct et concis.** Prioriser : *socle d'abord, signatures (bonus) ensuite* ; prévenir si une demande met le calendrier en danger et proposer la version simple.
- Si une information manque : **une seule question courte** plutôt que de supposer. Être honnête sur l'incertitude et sur ce qui n'a **pas** été testé.
- Relier chaque fonctionnalité à la grille de notation (démontrable en démo live, utile au pitch de 5 min ou au rapport).
- Code exécutable avec dépendances, commandes de test et pièges. Ne pas développer de modèle d'IA sauf demande explicite (l'équipe IA s'en charge) : brancher / intégrer seulement.
- Quand l'utilisateur dit « opération la plus légère possible » : le plus petit changement qui marche.
- **Ne jamais écrire de mot de passe réel dans `.claude/`** : les comptes de démo vivent dans `backend/.env` (ignoré par git).
- Décision prise : **ne pas migrer vers Django** ni un autre framework (voir `etat-et-decisions.md`). **Ne pas arrêter le backend de l'utilisateur** pour tester : `TestClient` avec `DATABASE_URL` / `LOG_DIR` temporaires.
- **Ne pas committer ni pousser sans demande.** L'utilisateur pousse directement sur `main`, comme l'équipe : `git fetch` puis `git pull --no-rebase` avant (des coéquipiers poussent). (Le push a été refusé une fois par l'environnement : si ça arrive, s'arrêter, expliquer, donner la commande à l'utilisateur.)
- Pronoms : neutres (ne jamais deviner d'après un prénom). Tests offensifs (Nmap, Metasploit, désauth Wi-Fi) : **uniquement sur notre réseau et notre matériel**.
- Vérifier plutôt que supposer : lancer le test, lire la capture d'écran (Chrome headless + `puppeteer-core` installé hors dépôt) — voir `context/pieges-et-verifications.md`.

## Contexte détaillé

@.claude/context/projet.md
@.claude/context/architecture.md
@.claude/context/etat-et-decisions.md

À lire seulement si besoin : `.claude/context/pieges-et-verifications.md` (pièges rencontrés, comment tester) et `README.md` (référence utilisateur : installation, variables, API).
