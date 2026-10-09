# Le projet : sujet, notation, équipe, planning

Source : sujet distribué (PPTX « 2526_PRESENTATION-WORKSHOP_M1 ») et document de contexte de l'utilisateur. Les points **[À CONFIRMER]** sont des hypothèses non validées.

## Situation

- Étudiant·e·s ESPI, rentrée 2026. **Une semaine** : lundi 5 octobre → soutenance locale **vendredi 9 octobre 2026**. Concours entre plusieurs écoles en France, **objectif podium**.
- Si qualifiés en local : affinage pour les qualifications nationales (jury **à distance** : prévoir démo enregistrée de secours, écran lisible avec la stack visible, idéalement accès distant au dashboard).
- Équipe de 6 : 1 dev (utilisateur principal), 3 IA, 1 infra/cloud, 1 cyber **[répartition infra/cloud/cyber À CONFIRMER]**.
- Matériel : petit budget de commande (capteurs, Arduino, moteurs, modules) + stock existant **[liste du stock À COMPLÉTER]**.

## Le sujet — Mission Sentinel-X

« Un système sécurisé à 100 %, ça n'existe pas. La vraie question : le vôtre tiendra-t-il jusqu'à vendredi ? »
En 2050, AetherCorp Industrial Solutions déploie des micro-centrales énergétiques en zones isolées et subit des attaques coordonnées
(cyber, physiques, environnementales). Il faut concevoir **Sentinel-X**, un boîtier de surveillance autonome qui détecte la menace avant qu'elle frappe.

Exigences du sujet :
- Boîtier **ESP8266 autonome (Edge Node)** avec capteurs température / gaz / présence. *(Notre équipe : code écrit, mais **non câblé** le 9 octobre ; démo sur le Pi seul. Un jury qui s'en tient au sujet peut le pénaliser : en parler franchement.)*
- Liaison sans fil vers un **serveur local** : option A = Raspberry Pi 5 dans le boîtier ; option B = PC portable d'un apprenant (choix dès lundi/mardi).
- **IA embarquée** : détection d'intrus par vision en temps réel (webcam, YOLOv8-tiny/OpenCV) + détection prédictive d'anomalies température/gaz
  (Isolation Forest / Random Forest), pas de simples seuils fixes.
- **4 briques à interconnecter : IoT, IA, Infra, Cybersécurité.** L'interconnexion complète est un **prérequis éliminatoire** pour valider la démo finale.

Stack suggérée par filière : DEV (C++ Arduino/PlatformIO, API REST/WebSocket, dashboard React/Vue) · IA (Python, YOLOv8-tiny/OpenCV, Isolation Forest/RF) ·
INFRA (Docker Compose, base de données, Wi-Fi dédié + plan d'adressage IP) · CYBER (TLS/MQTTS, hardening, audit Nmap/Wireshark/Metasploit) · fabrication (Fusion360, impression 3D, découpe laser).

**Livrables** : rapport technique ; vidéo teaser « Sentinel Drop » (60 s, fond vert) ; archive du code source ; support de soutenance (PPTX) ; Sentinel-X fonctionnel.

**Planning du sujet** : présentation + équipes → choix d'architecture + schémas réseau → câblage + conteneurs → firmware + premiers modèles IA → intégration globale (Edge-to-Server) →
tournage du teaser → finalisation du code → pentest croisé entre équipes → soutenance locale. Règles : émargement Edusign, propreté des locaux.

## Grilles d'évaluation

**Soutenance locale (20 pts)** : démo live & intégration globale **5** · technicité, innovation & sécurité (preuve du chiffrement, niveau d'inférence IA, durcissement prouvé) **4** ·
marketing & teaser « Sentinel Drop » (clip 60 s fond vert, finitions du boîtier gravé laser) **4** · posture, storytelling & pitch (5 min strictes) **4** · qualité documentaire & Q&A **3**.
→ **11 points sur 20 sont non techniques** : c'est là qu'on se différencie.

**Qualification nationale (70 pts listés)** : démonstration produit live **25** · vulgarisation & pitch (jury à distance) **20** · complexité technique & innovation **15** · impact visuel du « Drop » (vidéo) **10**.
→ démo + pitch = 45/70 : **stabilité et clarté > nombre de fonctionnalités**.

## Plan de survie (semaine)

1. Lundi/mardi : choix d'architecture, schémas réseau, commande du matériel manquant (après vérification du stock), Docker Compose de base, premier message capteur → serveur, certificats TLS (cyber).
2. **Mercredi (7 oct)** : flux complet de bout en bout (même moche) ; collecte de données normales ; modèle vision qui détecte une personne. **Décision : on garde ou on coupe les signatures.**
3. Jeudi : tournage du teaser, TLS + hardening, pentest croisé, signatures retenues, répétition de la démo chronométrée.
4. Vendredi matin : gel du code, **démo enregistrée de secours**, pitch de 5 min répété deux fois.

Règle d'or : le socle de bout en bout doit tourner mercredi soir, sinon on coupe toutes les « signatures ».
Dépendance critique du plan d'origine : le cyber livre mardi soir les certificats TLS et la config du broker.

## Idées « signatures » (2-3 maximum, une fois le socle stable)

| Idée | Intérêt / effort |
|---|---|
| Honeypot (SSH Cowrie, faux topic MQTT) qui alerte le dashboard : le pentest croisé devient une démo | fort / faible |
| Alerte Telegram avec photo de l'intrus | concret en vidéo / faible (les photos d'intrusion existent déjà) |
| Dashboard accessible à distance (WireGuard/Tailscale) : le jury national l'ouvre en direct | faible |
| Anti-rejeu HMAC (compteur + signature par message, capture Wireshark) | preuve cyber démontrable / moyen |
| IA multimodale : audio (YAMNet) via le micro de la webcam | moyen |
| Alertes expliquées (« pourquoi ? », contribution de chaque capteur) | répond au jury / moyen — le DHT22 donne déjà des `reasons` |
| Mode dégradé autonome : l'ESP calcule une anomalie simple et déclenche seul buzzer/relais si le serveur est coupé | autonomie du boîtier / moyen |
| Surveillance de consommation (INA219) + mini-turbine comme maquette de micro-centrale | moyen |
| Détection d'attaques Wi-Fi par l'ESP (trames de désauthentification) | très original / élevé : prototyper 1 h max, sur notre réseau seulement |

Non technique : nom, logo et univers AetherCorp 2050 dès mardi (gravure laser sur le boîtier) ; teaser : fond vert éclairé uniformément, personne ne porte de vert ;
score de menace par fusion de capteurs + compte à rebours « temps avant seuil dangereux » ; preuves cyber à l'écran (Wireshark split-screen MQTT clair vs chiffré, score Lynis avant/après, résultats du pentest croisé) ;
bonus « wow » : caméra sur pan-tilt (2 servos) pilotée par l'IA.

## Répartition proposée **[À CONFIRMER]**

Dev : firmware, capteurs, client, API WebSocket, dashboard (goulot d'étranglement : déléguer le front) · IA 1 : vision YOLO (Silya) · IA 2 : anomalies (collecte de données normales dès mardi) · IA 3 : front/teaser ·
Infra/cloud : Docker Compose, broker, base, Wi-Fi dédié + plan IP, boîtier Fablab · Cyber : TLS, hardening, preuves Wireshark/Lynis, honeypot, HMAC, pentest croisé, assemblage du rapport.
Pitch de 5 min : la personne qui parle le mieux, pas forcément le dev. Wi-Fi de soutenance : **apporter son propre routeur/hotspot**, ne pas compter sur celui de l'école.
