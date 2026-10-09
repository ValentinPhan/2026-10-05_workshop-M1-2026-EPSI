# Scénario de démo — soutenance locale du vendredi 9 octobre

**5 minutes strictes**, pitch compris. Le jury note la démo live (5 pts), la technicité et la sécurité (4 pts) et le respect du temps (dans les 4 pts « posture »). L'interconnexion des 4 briques est **éliminatoire** : elle doit se *voir* à l'écran, pas seulement se dire.

Principe : **une histoire, pas une visite guidée**. On ne montre pas chaque module : on rejoue une attaque de 2050, et chaque brique apparaît parce qu'elle répond à un moment de l'attaque.

> Ce document remplace, pour la soutenance, le « Scénario de démo » du README (liste de fonctionnalités, non chronométrée).
>
> **Mise à jour du 9 octobre : l'Edge Node ESP8266 (gaz MQ-2, présence PIR) n'est pas câblé.** La démo repose sur le Raspberry Pi (caméra, ultrason HC-SR04, DHT22, servo SG90) et le serveur (voir la photo `docs/img/montage-raspberry.jpg`). Le backend tourne en **`EDGE=off`** : pas de panneau Edge Node, pas de gaz ni de PIR. Les actes « PIR » et « fuite de gaz » de la version précédente sont retirés. **Risque à assumer** : le sujet impose un Edge Node ; il faut le dire avant que le jury le demande (§ 6).

---

## 1. Rôles (4 personnes en scène)

| Rôle | Qui | Fait quoi |
|---|---|---|
| **Orateur** | la personne la plus à l'aise à l'oral | raconte, ne touche pas au clavier |
| **Opérateur** | quelqu'un qui connaît le dashboard | pilote le PC projeté (dashboard, terminal préparé) |
| **Intrus** | n'importe qui, idéalement en noir / capuche | entre dans le champ de la caméra, puis s'approche à moins de 80 cm du capteur ultrason |
| **Filet de sécurité** | un membre qui reste en coulisse | surveille la console du backend, lance le plan B, garde le chrono et fait le signe « 1 minute » |

Les deux autres membres répondent aux questions de leur brique pendant le Q&A.

---

## 2. Déroulé chronométré

### 0:00 – 0:35 · Accroche (orateur, slide titre)

> « 9 octobre 2050. Une micro-centrale AetherCorp, en zone isolée, sans personne sur place. Cette nuit, quelqu'un va y entrer, et ce n'est pas le seul danger. Sentinel-X est là pour le voir avant qu'il ne frappe. On vous le montre en direct. »

### 0:35 – 1:05 · Architecture en une slide (orateur)

Le schéma des 4 briques, une phrase chacune :
- **IoT** : Raspberry Pi 3 (caméra, ultrason, DHT22, servo SG90), relié au PC par SSH ; l'image de la caméra arrive en WebSocket.
- **Infra** : réseau Wi-Fi dédié (hotspot du PC), backend FastAPI, base de données.
- **IA** : YOLO en temps réel sur la caméra, détection d'anomalies sur l'environnement, score de menace qui fusionne les capteurs.
- **Cyber** : comptes à rôles (admin / agent), mots de passe hachés, sessions révocables, verrouillage après 5 échecs, journal d'audit ; liaison SSH avec vérification de l'empreinte du Pi.

> « Tout ce que vous allez voir passe par ces quatre briques, en direct, sur notre propre réseau. »

### 1:05 – 3:35 · Démo live (2 min 30, opérateur + intrus, l'orateur commente)

| Temps | Acte | Action | Ce que le jury voit | Phrase de l'orateur |
|---|---|---|---|---|
| 1:05 | **1. Calme** (20 s) | rien, l'opérateur montre l'écran ; la mascotte Minion est « calme » | tous les modules verts, score « Calme », radar du servo qui balaie | « La centrale dort. Chaque capteur, chaque liaison est surveillé. Si l'un d'eux tombe, on le sait. » |
| 1:25 | **2. Intrusion** (55 s) | l'intrus entre dans le champ de la caméra, puis s'approche à moins de 80 cm de l'ultrason | silhouette et carré rouge, bandeau « INTRUSION DETECTED », alerte critique **avec la photo**, alerte de proximité, score en **« Menace »** (une personne confirmée suffit), gyrophares et sirène du Minion | « La caméra le voit, l'IA le reconnaît, la photo est prise automatiquement, l'ultrason mesure sa distance. Deux capteurs, un seul score. » |
| 2:20 | **3. Pilotage et environnement** (35 s) | l'opérateur oriente le servo (balayage auto, ou position) ; l'intrus souffle sur le DHT22 *(à répéter : l'effet sur l'anomalie d'environnement n'est pas garanti)* | le radar suit le servo ; température et humidité réagissent, le score d'anomalie du DHT22 peut monter | « On ne fait pas que voir : on pilote le capteur à distance. Et l'environnement est jugé par un détecteur d'anomalies qui apprend la normale de la pièce. » |
| 2:55 | **4. Cyber** (40 s) | l'opérateur se reconnecte en **agent** : tout en lecture seule ; puis en admin : panneau « Comptes et journal d'audit » ; option : 5 mots de passe faux, la connexion est bloquée | boutons de commande désactivés pour l'agent ; journal d'audit avec connexions, échecs, simulations ; message « Trop de tentatives » | « Et si quelqu'un essaie d'entrer dans le dashboard ? Deux rôles, droits vérifiés côté serveur, chaque action journalisée, et un verrou après cinq échecs. » |
| 3:35 | fin de la démo | retour au dashboard | journal d'alertes rempli, score qui redescend | — |

### 3:35 – 4:30 · Ce qui fait la différence (orateur, 2 slides)

- **IA** : YOLO tourne en temps réel sur CPU (environ 10 images/s, 24 à 64 ms par image selon la taille, mesuré sur le PC de démo). L'environnement est jugé par un détecteur d'anomalies qui apprend la normale de la pièce, pas par des seuils fixes. Le score fusionne la caméra, l'ultrason, la thermique éventuelle et l'anomalie d'environnement, et une personne confirmée suffit à passer en « Menace ».
- **Sécurité prouvée** : mots de passe hachés (scrypt), sessions révocables, rôles admin / agent vérifiés côté serveur, verrou anti-force brute, journal d'audit, empreinte SSH du Pi vérifiée.
- **Résilience** : chaque module est surveillé, une perte de liaison déclenche une alerte, les clips vidéo survivent à un plantage du serveur, le backend se reconnecte seul au Pi.

### 4:30 – 5:00 · Conclusion (orateur)

> « Un système sécurisé à 100 %, ça n'existe pas. Mais Sentinel-X voit, comprend, et prévient avant que la menace frappe. Merci, place à vos questions. »

**Si on est en retard** à 3:35, sauter la première des deux slides « différence » et aller directement à la conclusion. Le signe « 1 minute » du filet de sécurité tombe à 4:00.

---

## 3. Mise en place

### La veille (jeudi soir)

- [ ] Valider `PROVIDER=ssh` sur le vrai Raspberry (jamais testé sur le matériel : GPIO, servo SG90, HC-SR04, DHT22) : `raspberry-pi/README.md`, § 4 à 6.
- [ ] Vérifier que le diviseur 1 kΩ / 2 kΩ de l'Echo du HC-SR04 est bien en place (le GPIO du Pi est en 3,3 V).
- [ ] Enregistrer la **démo de secours** (capture d'écran vidéo du déroulé complet, 2 min 30), sur le PC **et** sur une clé USB.
- [ ] Deux répétitions chronométrées du déroulé complet, avec les 4 rôles.

### T-30 min (dans la salle)

1. Brancher le routeur ou activer le hotspot du PC (**jamais le Wi-Fi de l'école**), puis allumer le Pi. (L'ESP n'est pas utilisé. Le broker Mosquitto **du Pi** est facultatif : le backend s'y connecte s'il répond, sinon il continue sans.)
2. `backend/.env` : `APP_ENV=prod`, `PROVIDER=ssh`, `ANALYZER=local`, **`EDGE=off`**, `VISION_SOURCE=browser` (caméra USB branchée au PC, choisie dans le navigateur) ; `PI_MQTT_ENV_FILE` = `.env` de l'infra ; mots de passe admin **et agent** connus (`AGENT_PASSWORD`). **La caméra du Pi ne fonctionne pas** (9 octobre) : pas de `push`.
3. Lancer le backend et le front (`npm run dev:yolo`, ou F5 « Sentinel-X + YOLO (webcam navigateur) » ; variante : F5 « caméra du backend » avec `VISION_SOURCE=1`, l'index de la caméra USB). Vérifier `GET /api/pi-mqtt` : `connected: true`.
4. Se connecter en **admin**, plein écran, zoom du navigateur réglé pour que tout le dashboard tienne à l'écran.
5. Préparer un second onglet pour la reconnexion en **agent** (acte 4).

### T-10 min : test express (2 minutes)

- [ ] Tous les modules sont verts et **aucun panneau Edge Node n'apparaît** (`EDGE=off`) : s'il apparaît avec « Simulé », arrêter et relancer sans `EDGE=mock`.
- [ ] Main devant la caméra : carré rouge. Main près de l'ultrason : alerte de proximité. Servo : un balayage auto, le radar suit.
- [ ] Les alertes de ce test resteront dans le journal (elles sont en base, il n'y a pas de bouton pour les effacer) : l'annoncer (« nos derniers tests, il y a 10 minutes »).
- [ ] **Choisir le niveau de démo** (§ 5) **maintenant**, pas pendant la soutenance : changer de mode demande de relancer le backend.

---

## 4. Préparation de l'acte 4 (cyber)

- Deux comptes prêts : `admin` et `agent` (créés au premier lancement depuis `ADMIN_PASSWORD` et `AGENT_PASSWORD` du `backend/.env`).
- L'agent voit tout mais ne peut rien piloter : boutons moteur et caméra désactivés (« Lecture seule »).
- Verrou : 5 échecs en 5 minutes sur un même identifiant bloquent la connexion (message « Trop de tentatives »). **À ne montrer que sur un compte de test** : le blocage dure quelques minutes ; ne pas le faire sur `admin` juste avant de passer.
- En réserve pour le Q&A, depuis `backend/` avec le venv : `python -m app.cli list` (comptes), `python -m app.cli passwd admin` (mot de passe perdu).

*(Les commandes `mosquitto_sub` / `mosquitto_pub` de la version précédente servaient à prouver le MQTTS de l'ESP : elles ne servent plus tant que l'ESP n'est pas branché, voir `docs/mqtt-contract.md`.)*

---

## 5. Niveaux de démo et plan B

Décidés à T-10 min, du plus réel au plus sûr :

| Niveau | Configuration | Quand |
|---|---|---|
| **A. Tout réel** | `PROVIDER=ssh`, `EDGE=off`, `ANALYZER=local` | tout est vert au test express |
| **B. Pi simulé, vision réelle** | `PROVIDER=mock`, **`EDGE=off`**, `ANALYZER=local`, `VISION_SOURCE=browser` (webcam du PC) | le Pi ou sa caméra ne répond pas ; la vision reste réelle. Attention : le Pi simulé fait passer un **faux intrus** toutes les 20 à 40 s (alertes de proximité) ; le prévenir dans le récit |
| **C. Tout simulé** | `npm run dev:yolo` avec **`EDGE=off`** (sinon `EDGE=mock` affiche un faux Edge Node « Simulé ») | le Pi est en panne ; YOLO reste réel sur la webcam ; intrus, pic thermique et fenêtre ouverte via les boutons « Simuler » du journal d'alertes |
| **D. Vidéo de secours** | la démo enregistrée | le PC ou le backend ne démarre pas |

Le dire **franchement** si on passe en B ou C : « Le Pi nous a lâchés ce matin, on vous montre la même chaîne avec ses données simulées. » Le jury pardonne une panne annoncée, pas une panne cachée. **Même règle pour l'ESP8266** : ne jamais laisser croire qu'il est branché.

**Incidents pendant la démo**

| Incident | Réaction |
|---|---|
| YOLO ne détecte pas l'intrus | l'intrus se place de face, plus près, en pleine lumière ; l'orateur continue sur l'ultrason (alerte de proximité) |
| Le servo ou l'ultrason ne répond plus | montrer l'alerte « module perdu » (c'est une fonctionnalité) et continuer sur la caméra ; sinon niveau B |
| Un module passe « perdu » | **le montrer** : « Vous voyez, une liaison vient de tomber, et le système l'a détecté tout seul. » C'est une fonctionnalité. |
| Le dashboard se fige | F5 dans le navigateur (reconnexion automatique) ; si rien après 10 s, passer au niveau D |
| Dépassement de temps | couper l'acte 4 en direct et le résumer en une phrase (comptes, rôles, audit) |

---

## 6. Questions probables du jury (Q&A, 3 pts)

| Question | Réponse courte | Qui |
|---|---|---|
| Où est l'Edge Node ESP8266 imposé par le sujet ? | **Répondre franchement** : « Il est développé (firmware, broker MQTT chiffré avec certificats clients, ACL par boîtier, intégration au backend et au dashboard, tests en simulation), mais nous n'avons pas eu le temps de le câbler : il n'a jamais été éprouvé sur une vraie carte, donc nous ne le montrons pas. C'est notre priorité pour la finale. » Ne pas prétendre l'inverse. | IoT / Orateur |
| Comment protégez-vous la liaison avec le Raspberry ? | SSH avec vérification de l'empreinte du Pi (un appareil qui se ferait passer pour lui est refusé), clé plutôt que mot de passe. La vidéo arrive par un WebSocket authentifié par jeton d'appareil. | Cyber |
| Et la sécurité de la liaison ESP ? | Conçue, pas encore démontrée : TLS 1.2, certificat client obligatoire, ACL par boîtier (`docs/mqtt-contract.md`). À prouver à la finale avec Wireshark sur le port 8883. | Cyber |
| Le score de menace, c'est un seuil fixe ? | Non : une somme pondérée de la caméra, de l'ultrason, de la thermique éventuelle et de l'anomalie d'environnement (détecteur qui apprend la normale de la pièce), avec un plancher « Menace » dès qu'une personne est confirmée par YOLO. | IA |
| Quelle est la vitesse de l'IA ? | YOLOv8n sur CPU : environ 24 ms par image en 480 px, environ 10 images/s affichées ; l'affichage des capteurs n'attend jamais l'IA. | IA |
| Pourquoi l'IA sur le PC et pas sur le Pi ? | Le Pi 3 est trop faible pour YOLO en temps réel. Il n'envoie que des données brutes ; toute l'analyse est centralisée et plus facile à faire évoluer. | IA / Infra |
| Et si le serveur plante ? | Chaque module est surveillé (perte = alerte), les clips vidéo d'intrusion sont récupérables après un arrêt brutal, et le backend se reconnecte seul au broker et au Pi. | Infra |
| Comment sont gérés les accès au dashboard ? | Comptes admin et agent, mots de passe hachés (scrypt), sessions révocables immédiatement, droits vérifiés côté serveur, journal d'audit de chaque action. | Dev / Cyber |
| Qu'est-ce qui n'est pas fini ? | Le dire honnêtement (par exemple : HTTPS du dashboard, Isolation Forest pas encore branché en production), avec ce qu'on ferait pour la finale nationale. | Orateur |

---

## 7. Après la soutenance

- Récupérer `backend/data/logs/` et `backend/data/videos/` : ils documentent la démo réelle (utile pour le rapport et pour la vidéo nationale).
- Noter le temps réel de chaque partie et ce qui a coincé, pour ajuster avant les qualifications nationales (jury à distance : la démo enregistrée devient le plan A).
