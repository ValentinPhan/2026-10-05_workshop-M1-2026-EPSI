# Contrat MQTT — Sentinel-X

Ce document est la référence commune entre le firmware (Cyber 1), l'IA (IA 1, IA 2), l'API (IA 3) et l'infra (DevOps, Cyber 2).
**Toute modification d'un topic ou d'un champ passe par une PR qui met à jour ce fichier.**

## 1. Broker

| Paramètre | Valeur |
|---|---|
| Broker | Mosquitto 2, conteneur `mosquitto` sur le Pi |
| Adresse | `10.50.0.1:8883` (depuis le Wi-Fi), `mosquitto:8883` (depuis les conteneurs) |
| Transport | **TLS 1.2 minimum** (aucun port 1883 ouvert) |
| Authentification | **Certificat client obligatoire** (mTLS). Le CN du certificat sert d'identifiant MQTT |
| Anonyme | Interdit |
| Autorisations | ACL par identifiant, voir `infra/mosquitto/config/acl` |
| Heure | Le Pi sert l'heure en NTP sur `10.50.0.1` (requis par l'ESP pour vérifier la validité des certificats) |

Identifiants (CN des certificats, générés par `infra/pki/gen-certs.sh`) :

| CN | Rôle |
|---|---|
| `esp-node-01` | Boîtier ESP8266 (un CN par boîtier : `esp-node-02`…) |
| `api` | Backend FastAPI : stocke en base, relaie au dashboard en WebSocket |
| `ia-anomaly` | Détection d'anomalies capteurs |
| `ia-vision` | Détection d'intrus par webcam |

## 2. Conventions

- Préfixe racine : `sentinel/`.
- Payload : **JSON UTF-8**, clés courtes côté ESP (RAM limitée), message < 256 octets.
- Unités : °C, % HR, valeur brute ADC 0–1023 pour le gaz.
- Horodatage : `ts` en secondes Unix (UTC). Si l'ESP n'a pas encore l'heure NTP, il envoie `ts: 0` et l'API utilise l'heure de réception.
- Chaque message ESP contient un compteur `seq` (détection de pertes et de rejeu).

## 3. Topics

| Topic | Émetteur | Abonnés | QoS | Retain | Fréquence |
|---|---|---|---|---|---|
| `sentinel/{node}/telemetry` | ESP | api, ia-anomaly | 0 | non | toutes les 2 s |
| `sentinel/{node}/event` | ESP | api, ia-anomaly | 1 | non | sur changement du PIR |
| `sentinel/{node}/status` | ESP (+ LWT) | api | 1 | **oui** | à la connexion / déconnexion |
| `sentinel/{node}/cmd` | api | ESP | 1 | non | à la demande |
| `sentinel/alerts/anomaly` | ia-anomaly | api | 1 | non | sur détection |
| `sentinel/alerts/vision` | ia-vision | api | 1 | non | sur détection (anti-rebond 5 s) |
| `sentinel/services/{service}/status` | services IA | api | 1 | **oui** | à la connexion (+ LWT) |

`{node}` = CN du boîtier, par exemple `esp-node-01`.

## 4. Payloads

### `sentinel/{node}/telemetry`

```json
{"seq": 1532, "ts": 1791201600, "t": 23.4, "h": 41.0, "gas": 312, "pir": 0, "rssi": -58}
```

| Champ | Type | Description |
|---|---|---|
| `seq` | int | Compteur incrémenté à chaque message (repart à 0 au reboot) |
| `ts` | int | Heure Unix, ou 0 si pas encore synchronisé |
| `t` | float | Température en °C (1 décimale) |
| `h` | float | Humidité relative en % (1 décimale) |
| `gas` | int | Lecture brute A0 du MQ-2, 0–1023 |
| `pir` | int | 0 = rien, 1 = présence |
| `rssi` | int | Puissance Wi-Fi en dBm |

### `sentinel/{node}/event`

Envoyé immédiatement quand le PIR change d'état, sans attendre la prochaine télémétrie.

```json
{"seq": 1533, "ts": 1791201601, "type": "pir", "v": 1}
```

### `sentinel/{node}/status` (retained)

À la connexion, l'ESP publie :

```json
{"state": "online", "fw": "0.1.0", "ip": "10.50.0.10"}
```

Le Last Will (LWT) configuré à la connexion est :

```json
{"state": "offline"}
```

### `sentinel/{node}/cmd`

```json
{"cmd": "set_interval", "ms": 1000}
{"cmd": "reboot"}
{"cmd": "ping"}
```

L'ESP ignore toute commande inconnue. La réponse à `ping` est publiée sur `sentinel/{node}/event` avec `{"type": "pong"}`.

### `sentinel/alerts/anomaly`

```json
{
  "ts": 1791201620,
  "node": "esp-node-01",
  "sensor": "gas",
  "severity": "warning",
  "score": -0.21,
  "value": 498,
  "trend": {"slope_per_min": 85.0, "eta_threshold_s": 140},
  "model": "iforest-v1",
  "message": "Hausse anormale du gaz, seuil critique estimé dans 2 min 20"
}
```

| Champ | Description |
|---|---|
| `sensor` | `t`, `h` ou `gas` |
| `severity` | `info`, `warning` ou `critical` |
| `score` | Score de l'Isolation Forest (plus bas = plus anormal) |
| `trend.eta_threshold_s` | Temps estimé avant le seuil critique, `null` si pas de tendance |
| `model` | Version du modèle, pour la traçabilité dans le rapport |

### `sentinel/alerts/vision`

```json
{
  "ts": 1791201625,
  "camera": "cam-01",
  "severity": "critical",
  "label": "person",
  "confidence": 0.87,
  "count": 1,
  "zone": "intrusion",
  "snapshot": "2026-10-07T14-20-25_cam-01.jpg",
  "fps": 11.2
}
```

L'image n'est **pas** envoyée dans MQTT : `ia-vision` l'écrit dans le volume partagé `snapshots` (nom de fichier dans `snapshot`), et l'API la sert en HTTPS.

### `sentinel/services/{service}/status` (retained)

```json
{"state": "online", "version": "0.1.0", "model": "yolov8n-ncnn-320"}
```

LWT : `{"state": "offline"}`. Le dashboard peut ainsi afficher l'état de chaque brique.

## 5. Côté ESP8266 (rappels)

- `WiFiClientSecure` (BearSSL) + `PubSubClient`, CA de la PKI Sentinel + certificat client ECDSA P-256 (`esp-node-01.crt` / `.key`).
- `secureClient.setBufferSizes(512, 512)` pour économiser la RAM.
- Synchroniser l'heure (NTP sur `10.50.0.1`) **avant** la connexion TLS, sinon la vérification du certificat échoue.
- `PubSubClient` : `setBufferSize(256)`, keepalive 15 s, LWT sur `sentinel/{node}/status`, client ID = CN.
- Reconnexion Wi-Fi et MQTT avec backoff (1 s, 2 s, 4 s… max 30 s), sans bloquer la lecture des capteurs.

## 6. Tests rapides (depuis le Pi, dossier `infra/`)

```bash
# Écouter tout le trafic Sentinel avec le certificat de l'API
mosquitto_sub -h 10.50.0.1 -p 8883 \
  --cafile pki/out/ca.crt --cert pki/out/api.crt --key pki/out/api.key \
  -t 'sentinel/#' -v

# Doit être REFUSÉ (preuve pour la soutenance) : connexion sans certificat client
mosquitto_sub -h 10.50.0.1 -p 8883 --cafile pki/out/ca.crt -t 'sentinel/#'

# Doit être REFUSÉ par l'ACL : ia-vision tente de lire la télémétrie
mosquitto_sub -h 10.50.0.1 -p 8883 \
  --cafile pki/out/ca.crt --cert pki/out/ia-vision.crt --key pki/out/ia-vision.key \
  -t 'sentinel/+/telemetry' -v
```
