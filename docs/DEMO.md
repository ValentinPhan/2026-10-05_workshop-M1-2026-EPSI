# Scénario de démo — soutenance locale du vendredi 9 octobre

**5 minutes strictes**, pitch compris. Le jury note la démo live (5 pts), la technicité et la sécurité (4 pts) et le respect du temps (dans les 4 pts « posture »). L'interconnexion des 4 briques est **éliminatoire** : elle doit se *voir* à l'écran, pas seulement se dire.

Principe : **une histoire, pas une visite guidée**. On ne montre pas chaque module : on rejoue une attaque de 2050, et chaque brique apparaît parce qu'elle répond à un moment de l'attaque.

> Ce document remplace, pour la soutenance, le « Scénario de démo » du README (liste de fonctionnalités, non chronométrée). Il suppose la PR « Score de menace : gaz et PIR » fusionnée.

---

## 1. Rôles (4 personnes en scène)

| Rôle | Qui | Fait quoi |
|---|---|---|
| **Orateur** | la personne la plus à l'aise à l'oral | raconte, ne touche pas au clavier |
| **Opérateur** | quelqu'un qui connaît le dashboard | pilote le PC projeté (dashboard, terminal préparé) |
| **Intrus** | n'importe qui, idéalement en noir / capuche | entre dans le champ de la caméra, passe devant le PIR, approche du boîtier, approche le briquet du MQ-2 |
| **Filet de sécurité** | un membre qui reste en coulisse | surveille la console du backend, lance le plan B, garde le chrono et fait le signe « 1 minute » |

Les deux autres membres répondent aux questions de leur brique pendant le Q&A.

---

## 2. Déroulé chronométré

### 0:00 – 0:35 · Accroche (orateur, slide titre)

> « 9 octobre 2050. Une micro-centrale AetherCorp, en zone isolée, sans personne sur place. Cette nuit, quelqu'un va y entrer, et ce n'est pas le seul danger. Sentinel-X est là pour le voir avant qu'il ne frappe. On vous le montre en direct. »

### 0:35 – 1:05 · Architecture en une slide (orateur)

Le schéma des 4 briques, une phrase chacune :
- **IoT** : Raspberry Pi (caméra, ultrason, DHT22, servo) **et** Edge Node ESP8266 (gaz, présence), deux liaisons indépendantes.
- **Infra** : réseau Wi-Fi dédié, broker Mosquitto en Docker, backend FastAPI, base de données.
- **IA** : YOLO en temps réel sur la caméra, détection d'anomalies sur l'environnement, score de menace qui fusionne tous les capteurs.
- **Cyber** : liaison ESP chiffrée (TLS 1.2) avec certificat client et droits par boîtier, comptes à rôles, journal d'audit.

> « Tout ce que vous allez voir passe par ces quatre briques, en direct, sur notre propre réseau. »

### 1:05 – 3:35 · Démo live (2 min 30, opérateur + intrus, l'orateur commente)

| Temps | Acte | Action | Ce que le jury voit | Phrase de l'orateur |
|---|---|---|---|---|
| 1:05 | **1. Calme** (20 s) | rien, l'opérateur montre l'écran | tous les modules verts, score « Calme », panneau Edge Node « En ligne · MQTTS » | « La centrale dort. Chaque capteur, chaque liaison est surveillé. Si l'un d'eux tombe, on le sait. » |
| 1:25 | **2. Intrusion** (45 s) | l'intrus entre dans le champ de la caméra, passe devant le PIR, s'approche à moins de 80 cm du boîtier | silhouette et carré rouge, bandeau « INTRUSION DETECTED », alerte critique **avec la photo**, alerte PIR, alerte de proximité, le score monte vers « Menace » | « La caméra le voit, l'IA le reconnaît, la photo est prise automatiquement. L'ESP le sent, l'ultrason mesure sa distance. Trois capteurs, un seul score. » |
| 2:10 | **3. Fuite de gaz** (40 s) | l'intrus sort du champ, puis approche un **briquet non allumé** du MQ-2 et appuie 3 à 5 s | la courbe de gaz franchit le seuil en pointillés, alerte critique « Gaz détecté », le score reste en « Menace » **alors que plus personne n'est à l'image** | « L'intrus est parti, mais il a laissé une fuite. Une menace, ce n'est pas qu'une personne : notre score le sait. » |
| 2:50 | **4. Cyber** (45 s) | l'opérateur bascule sur le terminal préparé et lance la commande « connexion sans certificat » (§ 4) | le broker coupe la connexion (« The connection was lost ») ; puis slide ou capture Wireshark : uniquement du TLS sur le port 8883 | « Et si l'attaquant passe par le réseau ? Sans certificat signé par nous, le broker refuse. Et même sur le Wi-Fi, il ne lit que du chiffré. Chaque boîtier n'écrit que sur ses propres canaux : un ESP compromis ne peut pas se faire passer pour un autre. » |
| 3:35 | fin de la démo | retour au dashboard | journal d'alertes rempli, score qui redescend | — |

### 3:35 – 4:30 · Ce qui fait la différence (orateur, 2 slides)

- **IA** : YOLO tourne en temps réel sur CPU (environ 10 images/s, 24 à 64 ms par image selon la taille, mesuré sur le PC de démo). L'environnement est jugé par un détecteur d'anomalies qui apprend la normale de la pièce, pas par des seuils fixes. Le score fusionne 6 signaux, et le gaz agit comme un plancher de danger.
- **Sécurité prouvée** : mTLS et droits par boîtier sur l'ESP, mots de passe hachés (scrypt), sessions révocables, rôles admin / agent vérifiés côté serveur, journal d'audit.
- **Résilience** : chaque module est surveillé, une perte de liaison déclenche une alerte, l'ESP et le Pi fonctionnent indépendamment, les clips vidéo survivent à un plantage du serveur.

### 4:30 – 5:00 · Conclusion (orateur)

> « Un système sécurisé à 100 %, ça n'existe pas. Mais Sentinel-X voit, comprend, et prévient avant que la menace frappe. Merci, place à vos questions. »

**Si on est en retard** à 3:35, sauter la première des deux slides « différence » et aller directement à la conclusion. Le signe « 1 minute » du filet de sécurité tombe à 4:00.

---

## 3. Mise en place

### La veille (jeudi soir)

- [ ] Préchauffer le MQ-2 (idéalement 24 h) : le laisser branché toute la nuit.
- [ ] Régler `GAS_ALERT_RAW` d'après les vraies valeurs : lecture au repos, puis avec le briquet. Viser un seuil franchi en 2 à 3 s de briquet, jamais au repos.
- [ ] Régler les potentiomètres du PIR HC-SR501 : sensibilité moyenne, temporisation minimale (environ 5 s).
- [ ] Enregistrer la **démo de secours** (capture d'écran vidéo du déroulé complet, 2 min 30), sur le PC **et** sur une clé USB.
- [ ] Préparer la capture Wireshark (port 8883, que du TLS) et la mettre dans une slide.
- [ ] Deux répétitions chronométrées du déroulé complet, avec les 4 rôles.

### T-30 min (dans la salle)

1. Brancher le routeur ou activer le hotspot du PC (**jamais le Wi-Fi de l'école**), puis allumer le Pi et l'ESP.
2. Sur le PC : Docker Desktop lancé, puis `cd infra && docker compose up -d` (broker).
3. `backend/.env` : `APP_ENV=prod`, `PROVIDER=ssh`, `ANALYZER=local`, `EDGE=mqtt`, `VISION_SOURCE=push` (caméra du Pi) ou `browser` (webcam du PC), mot de passe admin connu.
4. Lancer le backend et le front (F5 « Sentinel-X + YOLO (caméra du Raspberry, push) », ou `npm run dev:yolo`). Sur le Pi : `camera_push.py` si `VISION_SOURCE=push`.
5. Se connecter en **admin**, plein écran, zoom du navigateur réglé pour que tout le dashboard tienne à l'écran.
6. Ouvrir le terminal préparé (§ 4) dans `infra/`, commande déjà tapée, sans l'exécuter.

### T-10 min : test express (2 minutes)

- [ ] Tous les modules sont verts et le panneau Edge Node affiche « En ligne · MQTTS ».
- [ ] Main devant la caméra : carré rouge. Main devant le PIR : « Présence ». Main près de l'ultrason : alerte de proximité.
- [ ] **Pas** de test du briquet (le MQ-2 met 30 à 60 s à redescendre).
- [ ] Les alertes de ce test resteront dans le journal (elles sont en base, il n'y a pas de bouton pour les effacer) : l'annoncer (« nos derniers tests, il y a 10 minutes »).
- [ ] **Choisir le niveau de démo** (§ 5) **maintenant**, pas pendant la soutenance : changer de mode demande de relancer le backend.

---

## 4. Commandes préparées (terminal, dossier `infra/`)

```bash
# Acte 4 : connexion sans certificat client -> refusée par le broker
mosquitto_sub -h 127.0.0.1 -p 8883 --cafile pki/out/ca.crt -t 'sentinel/#'

# En réserve (Q&A) : l'ESP essaie d'écrire sur le canal d'un autre boîtier -> refusé par l'ACL
mosquitto_pub -h 127.0.0.1 -p 8883 --cafile pki/out/ca.crt --cert pki/out/esp-node-01.crt --key pki/out/esp-node-01.key \
  -t sentinel/esp-node-02/telemetry -m '{"seq":1,"gas":999}'
```

Pas de `mosquitto_sub` sur le PC Windows ? Utiliser celui du conteneur : `docker compose exec mosquitto mosquitto_sub …` avec les chemins `/mosquitto/certs/...`.

---

## 5. Niveaux de démo et plan B

Décidés à T-10 min, du plus réel au plus sûr :

| Niveau | Configuration | Quand |
|---|---|---|
| **A. Tout réel** | `PROVIDER=ssh`, `EDGE=mqtt`, `ANALYZER=local` | tout est vert au test express |
| **B. ESP réel, Pi simulé** | `PROVIDER=mock`, `EDGE=mqtt`, `ANALYZER=local`, `VISION_SOURCE=browser` (webcam du PC) | le Pi ou sa caméra ne répond pas ; l'ESP et la vision restent réels. Attention : le Pi simulé fait passer un **faux intrus** toutes les 20 à 40 s (alertes de proximité) ; le prévenir dans le récit |
| **C. Tout simulé** | `npm run dev:yolo` (`PROVIDER=mock`, `EDGE=mock`) | ESP et Pi en panne ; YOLO reste réel sur la webcam ; gaz, PIR et intrus via les boutons « Simuler » du journal d'alertes |
| **D. Vidéo de secours** | la démo enregistrée | le PC ou le backend ne démarre pas |

Le dire **franchement** si on passe en B ou C : « Le Pi nous a lâchés ce matin, on vous montre la même chaîne avec ses données simulées. » Le jury pardonne une panne annoncée, pas une panne cachée.

**Incidents pendant la démo**

| Incident | Réaction |
|---|---|
| YOLO ne détecte pas l'intrus | l'intrus se place de face, plus près, en pleine lumière ; l'orateur continue sur le PIR et l'ultrason |
| Le gaz ne franchit pas le seuil | encore 3 s de briquet ; sinon l'orateur montre la courbe qui monte et passe à l'acte 4 |
| Un module passe « perdu » | **le montrer** : « Vous voyez, une liaison vient de tomber, et le système l'a détecté tout seul. » C'est une fonctionnalité. |
| Le dashboard se fige | F5 dans le navigateur (reconnexion automatique) ; si rien après 10 s, passer au niveau D |
| Dépassement de temps | couper l'acte 4 en direct et ne garder que la slide Wireshark |

---

## 6. Questions probables du jury (Q&A, 3 pts)

| Question | Réponse courte | Qui |
|---|---|---|
| Pourquoi un ESP8266 **et** un Raspberry Pi ? | Le sujet impose l'ESP comme Edge Node autonome. Les deux liaisons sont indépendantes : si le Pi tombe, le gaz et la présence restent surveillés, et inversement. | IoT |
| Comment prouvez-vous le chiffrement ? | Capture Wireshark sur le port 8883 : uniquement du TLS 1.2. Connexion sans certificat refusée en direct. Aucun port MQTT en clair ouvert. | Cyber |
| Que se passe-t-il si on vole l'ESP ? | Sa clé ne lui permet d'écrire que sur ses propres canaux (ACL par certificat) : il ne peut ni lire les autres, ni se faire passer pour eux. On retire son identifiant de l'ACL et il ne peut plus rien publier ; les autres boîtiers ne sont pas touchés. (Pas encore de liste de révocation de certificats : piste pour la finale.) | Cyber |
| Ce n'est pas qu'un seuil fixe pour le gaz ? | L'alerte gaz est un seuil (danger immédiat, réglé sur le vrai capteur), mais le score de menace fusionne 6 signaux, et l'environnement est jugé par un détecteur d'anomalies qui apprend la normale de la pièce. | IA |
| Quelle est la vitesse de l'IA ? | YOLOv8n sur CPU : environ 24 ms par image en 480 px, environ 10 images/s affichées ; l'affichage des capteurs n'attend jamais l'IA. | IA |
| Pourquoi l'IA sur le PC et pas sur le Pi ? | Le Pi 3 est trop faible pour YOLO en temps réel. Il n'envoie que des données brutes ; toute l'analyse est centralisée et plus facile à faire évoluer. | IA / Infra |
| Et si le serveur plante ? | Chaque module est surveillé (perte = alerte), les clips vidéo d'intrusion sont récupérables après un arrêt brutal, et le backend se reconnecte seul au broker et au Pi. | Infra |
| Comment sont gérés les accès au dashboard ? | Comptes admin et agent, mots de passe hachés (scrypt), sessions révocables immédiatement, droits vérifiés côté serveur, journal d'audit de chaque action. | Dev / Cyber |
| Qu'est-ce qui n'est pas fini ? | Le dire honnêtement (par exemple : HTTPS du dashboard, Isolation Forest pas encore branché en production), avec ce qu'on ferait pour la finale nationale. | Orateur |

---

## 7. Après la soutenance

- Récupérer `backend/data/logs/` et `backend/data/videos/` : ils documentent la démo réelle (utile pour le rapport et pour la vidéo nationale).
- Noter le temps réel de chaque partie et ce qui a coincé, pour ajuster avant les qualifications nationales (jury à distance : la démo enregistrée devient le plan A).
