# État d'avancement, décisions, reste à faire

*Rédigé le mercredi 7 octobre 2026 (J-2 de la soutenance locale). À mettre à jour à chaque étape importante.*

## Ce qui marche (et a été testé)

- **Backend Python** (FastAPI) complet : chemins rapide / lent / vidéo, alertes, WebSocket, REST. Provider **mock** (Pi simulé) uniquement.
- **YOLO intégré** : détection de personnes avec silhouettes (`yolov8n-seg.pt`), image + positions renvoyées par image (`/ws/video`), React dessine carrés rouges / silhouettes / compteur / menace, **vue miroir**.
  Testé avec : vidéo de l'équipe IA, webcam réelle du PC (≈ 9,7 fps, intrusion détectée), fausse webcam Chrome. Vitesse (i7-1360P, CPU, sans GPU) : `yolov8n` 640 px ≈ 64 ms, 480 ≈ 24 ms, 320 ≈ 14 ms ; segmentation 640 ≈ 102 ms.
- **Sources vidéo** commutables : caméra du backend, webcam du navigateur (interrupteur « Webcam PC » ⇒ `/ws/camera`), Pi en push (`camera_push.py`, testé avec fichier vidéo).
- **Photos d'intrusion** avec latence de confirmation, photo allégée (≈ 15 Ko), alerte avec miniature ; testées en simulation d'horloge (scénarios clignotement 2-3-2-3 / 3-4 / bruit / retour) et avec le vrai YOLO.
- **DHT22** : lecture côté Pi (`dht22_reader.py`), simulation côté mock, détection d'anomalies en ligne (port Python **identique** au JS de Valentin sur ~4 000 mesures), alerte d'environnement, score de menace à 4 composantes.
- **Comptes admin / agent + base** : SQLite et PostgreSQL 17 (65 tests d'API identiques sur les deux), cookie de session, rôles vérifiés côté serveur, audit, historique des alertes en base, sweeper des WebSocket, jeton d'appareil. Parcours navigateur testé de bout en bout (18 vérifications).
- **Outillage** : F5 VS Code (3 configs YOLO + mock + caméra backend), tâche qui attend l'API avant le front, `npm run dev:yolo`, `scripts/run-api.mjs` (venv automatique), messages de connexion colorés dans les terminaux.

## Pas fait / pas testé (par ordre d'importance pour la soutenance)

1. **Aucun test sur le vrai Raspberry** : `providers/ssh.py` est un squelette (donc **pas de capteurs réels** dans le dashboard) ; `camera_push.py` (partie `picamera2`) et `dht22_reader.py` à valider sur le Pi ; flux MJPEG non testé.
2. **Écarts avec le sujet** : pas d'**ESP8266**, pas de **capteur de gaz**, pas de **MQTT/TLS** (MQTTS), pas de durcissement ni de preuves cyber (Wireshark, Lynis), pas de pentest croisé. Le sujet exige l'ESP8266 « Edge Node » et l'interconnexion des 4 briques (**éliminatoire**) : **à trancher avec l'équipe** (le Pi remplace-t-il l'ESP, ou les deux coexistent-ils ?). Le dashboard peut recevoir n'importe quelle source qui respecte le contrat de snapshot.
3. **HTTPS** du dashboard : sans lui, `COOKIE_SECURE=0` et la webcam du navigateur ne marche que sur `localhost` (voir pièges).
4. **Isolation Forest** (`ml/environment/env_model.py`) non branché dans `LocalAnalyzer` ; pas de modèle « Random Forest » ; pas de collecte de données normales réelle.
5. Livrables non techniques : **rapport**, **teaser « Sentinel Drop »** (60 s, fond vert), **pitch de 5 min**, **PPTX**, boîtier (Fusion360 / impression / gravure laser), nom-logo-univers AetherCorp, démo enregistrée de secours.
6. « Signatures » du plan (honeypot, Telegram + photo, WireGuard, HMAC anti-rejeu, alertes expliquées, mode dégradé ESP…) : aucune faite — décider mercredi soir lesquelles garder.
7. Pas de tests automatisés **dans le dépôt** (les scripts de vérification ont été écrits dans un dossier temporaire, voir `pieges-et-verifications.md`) ; pas d'historique des capteurs en base (seules alertes et audit le sont) ; un utilisateur ne peut pas changer lui-même son mot de passe (réinitialisation par un admin).

## Limites connues

- « Nouvelle personne » = *plus de personnes que le palier déjà photographié* (pas de suivi d'identité) : une personne qui part et une autre qui arrive en même temps ne déclenchent rien.
- Détecteur DHT22 en ligne : une dérive lente (fenêtre ouverte sur 5 min) est **absorbée** (score 0) ; à la fermeture d'une fenêtre la remontée > 2 °C/min peut déclencher le garde-fou « risque incendie » (score 100). Comportement hérité du code de Valentin, porté tel quel ; à signaler à l'équipe IA.
- YOLO : image « brute » au repos, détections ~10 Hz ; le score de menace joint à chaque image est celui de l'analyseur (≈ 1 Hz).
- Le journal Git contient ≈ 56 Mo de vidéos de test de l'équipe IA (`ml/vision/runs/`) : dans l'historique, impossible à retirer sans le réécrire. `ml/vision/captures|runs` sont ignorés pour l'avenir. Les 4 photos d'exemple ont été supprimées du dossier de travail par l'utilisateur.
- `yolo26n.pt` est rangé dans `backend/models/` mais **inutilisé**.
- Avertissement console antd « List deprecated » (inoffensif).

## Décisions d'architecture et pourquoi

| Décision | Raison |
|---|---|
| **Un seul backend Python (FastAPI)**, YOLO dans un thread du même process (le backend Node du premier prototype a été supprimé) | l'IA est en Python, pas d'images à transporter entre deux services, les 3 personnes IA peuvent toucher le backend ; l'inférence **ne tourne jamais dans la boucle async** (un YOLO lent ne bloque ni l'API ni l'affichage) |
| **Deux vitesses** : snapshot brut tout de suite, résultat IA en différé (`analysis`) | l'affichage des capteurs ne dépend pas du modèle ; si l'IA plante le dashboard continue (« IA hors ligne ») ; alertes à seuil immédiates sans IA |
| **Le Pi n'envoie que du brut** ; l'IA est sur le PC | choix de l'utilisateur ; le Pi peut être faible |
| **Positions renvoyées, React dessine** (carrés rouges, silhouettes) avec les résultats **dans le même message que l'image** | synchro parfaite image/cadres ; personnalisable (couleurs, miroir, bandeaux) ; l'option `VISION_ANNOTATE=1` existe aussi |
| **Webcam du navigateur envoyée au backend** (temporaire, par défaut en F5) | la webcam ne peut être ouverte que par un programme à la fois ; fonctionne même si le backend n'a pas de caméra |
| **Vidéo du Pi : WebSocket push** (plutôt que MJPEG pull / RTSP / MQTT) | aucun serveur de streaming à installer sur le Pi, dernier-gagnant, reconnexion ; MQTT n'a pas de « dernière image » ; SSH réservé au JSON/commandes (pas de rafale qui retarde le moteur) |
| **SQLite par défaut, PostgreSQL via `DATABASE_URL`** | zéro installation pour la démo, mais compatible avec la stack Postgres de l'infra ; SQLAlchemy = même code |
| **Comptes : cookie de session + rôles côté serveur**, WebSocket revérifiées | l'interface ne fait que refléter les droits ; un compte supprimé coupe aussi les flux ouverts |
| **Latence de confirmation avant de photographier** | YOLO hésite d'une image à l'autre ; évite 15 photos en 5 s |
| **Ant Design** pour les composants React | demande de l'utilisateur ; visuels sur mesure (radar, cadran, heatmap, canvas) en SVG/canvas |
| **Mode mock conservé** (`PROVIDER=mock`, `ANALYZER=mock`) | développer et faire la démo sans matériel ; scénarios déclenchables (intrus, pic thermique, fenêtre) |

## Prochaines étapes suggérées (à arbitrer avec l'utilisateur)

1. Trancher l'**ESP8266 / MQTT** avec l'équipe, puis implémenter **`providers/ssh.py`** (asyncssh, reconnexion) pour de vraies données du Pi ; valider `camera_push.py` et `dht22_reader.py` sur le Pi.
2. **Démo enregistrée de secours** + scénario de démo chronométré (intrus, pic thermique, fenêtre, admin vs agent).
3. Brancher l'**Isolation Forest** (équipe IA) ; collecter des données normales du DHT22.
4. Cyber : HTTPS pour le dashboard, `COOKIE_SECURE=1`, preuves (Wireshark, Lynis), honeypot / HMAC si le temps le permet.
5. Rapport, teaser, pitch, boîtier.
6. Transformer les vérifications ponctuelles en **tests dans `backend/tests/`**.

## Repères Git

- Branche `main`, dépôt `ValentinPhan/2026-10-05_workshop-M1-2026-EPSI`. Jalons : « mockup » (premier dashboard Node) → PR #1 de Valentin (DHT22) → « Python bakcend » (passage à FastAPI) → « Yolo worksop » (Silya) → « YOLO intégré au backend, dossiers renommés, webcam du navigateur » → comptes / base / caméra push / photos à latence / miroir / `.claude`.
- Branches distantes `claude/*` : sessions Claude des coéquipiers (certaines non fusionnées : plan d'action, contrat MQTT, squelette docker-compose).
- L'utilisateur pousse lui-même si l'environnement refuse le `git push` de Claude.
