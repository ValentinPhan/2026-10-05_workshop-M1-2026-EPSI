# Plan d'action — Mission Sentinel-X (Workshop M1 2026)

Équipe : 3 développeurs IA, 2 développeurs cybersécurité, 1 DevOps.
Architecture retenue : **Option A — Raspberry Pi 5 embarqué dans le boîtier**.

---

## 1. Lecture stratégique du sujet

- **Éliminatoire** : interconnexion des 4 briques (IoT, IA, Infra, Cyber) en démo. Priorité absolue = le flux complet ESP8266 → serveur → dashboard.
- **Barème local** : démo live 5, technique/sécurité 4, teaser 4, pitch 4, documentation 3. Le marketing et le pitch pèsent **8/20** : la vidéo et le boîtier ne se font pas le jeudi soir.
- **Barème national** : 25 pts sur 70 pour une démo sans plantage, avec la stack visible à l'écran. Il faut viser la robustesse plutôt que l'ajout de fonctionnalités.
- **Point d'attention** : pas de profil « DEV » dans l'équipe. Le firmware C++, l'API et le dashboard sont répartis entre les profils IA et Cyber.

## 2. Architecture cible

```
[ESP8266 + capteurs]  --Wi-Fi WPA2 dédié, MQTTS 8883 (TLS + certificat client)-->  [Raspberry Pi 5]
  DHT22/BME280 (temp)                                                              ├─ hostapd : point d'accès "SENTINEL-NET" 10.50.0.0/24
  MQ-2 (gaz, via pont diviseur → A0)                                               └─ docker-compose :
  PIR HC-SR501 (présence)                                                             mosquitto (TLS, ACL, pas d'anonyme)
                                                                                      api (FastAPI : REST + WebSocket)
[Webcam USB] -------------------------------------------------------------->          ia-vision (YOLOv8n → ONNX/NCNN)
                                                                                      ia-anomaly (Isolation Forest)
                                                                                      db (InfluxDB ou TimescaleDB)
                                                                                      caddy/nginx (HTTPS) → dashboard (Vue/React)
```

**Choix techniques**

- **API en Python/FastAPI** : c'est le langage commun aux 3 profils IA, et les modèles s'intègrent sans passer par un autre langage.
- **TLS sur l'ESP8266** : BearSSL avec des **certificats ECDSA P-256** (plus légers en RAM), `setBufferSizes(512, 512)`, messages MQTT courts en JSON.
- **Vision sur le Pi 5 en CPU** : YOLOv8n exporté en NCNN ou ONNX, entrée en 320 px, environ 8 à 15 FPS attendus. Seule la classe `person` est retenue, dans une zone d'intrusion définie.
- **Anomalies « prédictives »** : features calculées sur fenêtres glissantes (moyenne, pente, variance), passées à un Isolation Forest, plus une tendance (EWMA ou régression linéaire) pour annoncer « seuil atteint dans X min ». Pas de seuils fixes.
- **Plan d'adressage** : Pi en `10.50.0.1`, ESP en `10.50.0.10` (bail fixe), poste de démo en `10.50.0.100`. Pare-feu nftables : seuls les ports 22 (clé uniquement), 443 et 8883 sont ouverts.

## 3. Répartition des rôles

| Membre | Responsabilité principale | Secondaire |
|---|---|---|
| **IA 1** | Vision : YOLOv8n, zone d'intrusion, optimisation NCNN, alerte MQTT et snapshot | Mesure des FPS et de la latence (preuve pour l'axe 2) |
| **IA 2** | Anomalies : collecte de données, entraînement de l'Isolation Forest, prédiction de tendance, scénarios de démo | Rapport technique (partie IA) |
| **IA 3** | API FastAPI (REST + WebSocket) et dashboard temps réel | **Lead teaser vidéo** (script, fond vert, montage) |
| **Cyber 1** | Firmware ESP8266 en C++/PlatformIO (capteurs, MQTTS, reconnexion), PKI (CA, certificats serveur et client) | Câblage, intégration dans le boîtier |
| **Cyber 2** | Durcissement du Pi (SSH, nftables, fail2ban, utilisateurs, mises à jour), ACL Mosquitto, preuves Nmap/Wireshark | **Lead pentest croisé** (défense et attaque), rapport sécurité |
| **DevOps** | Pi OS, point d'accès Wi-Fi, docker-compose, base de données, sauvegarde de l'image SD, démarrage automatique | **Boîtier Fablab** (Fusion360, découpe laser), chef de projet et intégration |

Désigner aussi **un porteur du pitch**, par exemple la personne la plus à l'aise à l'oral, qui n'est pas forcément le lead technique.

## 4. Planning jour par jour

| Créneau | Objectif équipe | Critère de « fini » |
|---|---|---|
| **Lun. PM** | Option A validée, schéma réseau et architecture, contrat MQTT (topics et format JSON), dépôt Git structuré. **Réserver les créneaux Fablab**. | Schéma validé par l'encadrant, `docs/architecture.md` et `docs/mqtt-contract.md` commités |
| **Mar. AM** | Pi installé avec le point d'accès Wi-Fi, docker-compose en route (Mosquitto en TLS, base de données, API vide). Câblage des capteurs sur breadboard. PKI générée. | `docker compose up` fonctionne, l'ESP lit ses 3 capteurs sur le port série |
| **Mar. PM** | Firmware : publication en MQTTS. YOLO tourne sur la webcam. Collecte de données « normales » pour l'IA. Premier croquis du boîtier. | Des messages chiffrés arrivent dans la base, la détection de personne s'affiche dans la console |
| **Mer. AM** | **Intégration de bout en bout** : capteurs → MQTT → API → dashboard. Alertes vision et anomalies poussées en WebSocket. | **Jalon critique** : le flux complet tourne 30 min sans plantage |
| **Mer. PM** | Tournage du teaser (script prêt la veille). Découpe et gravure du boîtier. Durcissement terminé. | Rushes tournés, boîtier découpé |
| **Jeu. AM** | Finalisation : robustesse (reconnexion Wi-Fi/MQTT, redémarrage auto des conteneurs), montage vidéo, rapport technique. | Démarrage à froid → tout remonte seul en moins de 2 min |
| **Jeu. PM** | Pentest croisé : défendre (journaux, captures) et attaquer les autres équipes (Nmap, Wireshark, tentatives MQTT anonymes, SSH). | Rapport de pentest, corrections appliquées |
| **Vendredi** | Soutenance : 2 répétitions chronométrées (5 min strictes), démo sur scénario scripté. | Les 5 livrables déposés |

## 5. Démo, preuves et plan B

**Scénario de démo (environ 90 s)**

1. Le dashboard est au calme et montre la stack à l'écran.
2. Une personne entre dans le champ : alerte vision avec snapshot.
3. On approche un briquet du MQ-2 sans l'allumer : le gaz monte et l'alerte d'anomalie se déclenche **avant** le seuil.
4. On souffle de l'air chaud sur le capteur : la température dérive et une prédiction s'affiche.

**Preuves de sécurité**

- Une capture Wireshark montre du TLS sur le port 8883 et aucun port 1883 ouvert.
- Un scan `nmap -sV` du Pi est montré avant et après durcissement.
- Une tentative de connexion `mosquitto_sub` sans certificat est refusée.

**Plan B**

- Un mode « rejeu » réinjecte des données enregistrées si un capteur lâche.
- Une vidéo de la démo complète sert de secours.
- Une image de la carte SD est clonée le jeudi soir.

**Points pratiques**

- Prévoir l'alimentation officielle 27 W du Pi 5 (sinon il bride ses performances).
- Mettre un ventilateur actif et des aérations dans le boîtier : le Pi 5 chauffe une fois enfermé.
- Le MQ-2 demande environ 24 h de préchauffe pour être stable : le brancher dès mardi.

## 6. Livrables

- [ ] Rapport technique
- [ ] Vidéo « Sentinel Drop » (60 s, fond vert)
- [ ] Archive du code source
- [ ] Support de soutenance (PPTX, charte graphique Montserrat / #261E48 / #E4E6F3 / #A1A6D4)
- [ ] Sentinel-X fonctionnel

## 7. Organisation

- Un daily de 10 min à 9 h et un point d'intégration à 14 h.
- Un tableau Kanban (GitHub Projects) avec une issue par tâche du planning.
- Une branche par brique (`firmware/`, `ia/`, `infra/`, `cyber/`, `dashboard/`), avec des merges sur `main` après revue.
