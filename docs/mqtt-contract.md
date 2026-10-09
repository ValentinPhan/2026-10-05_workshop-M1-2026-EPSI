# Contrat MQTT — Edge Node ESP8266

Référence commune entre le firmware (`firmware/esp8266/`), le backend (`backend/app/edge.py`) et l'infra (`infra/`).
**Toute modification d'un topic ou d'un champ passe par une PR qui met à jour ce fichier.**

## 1. Où ça tourne

```
[ESP8266]  -- Wi-Fi (hotspot du PC) --  MQTTS 8883 (TLS 1.2 + certificat client)  -->  [Mosquitto, Docker sur le PC]
 MQ-2 (gaz, A0)                                                                           │ mTLS, 127.0.0.1:8883
 PIR HC-SR501 (D5)                                                                        ▼
 [DHT22 optionnel]                                                         [backend FastAPI : edge.py, EDGE=mqtt]
                                                                             → message WS `edge`, alertes gaz / PIR,
                                                                               santé du module « esp8266 »
```

L'ESP est **indépendant du Raspberry Pi** : sa propre liaison et son propre rythme. Si le Pi tombe, le gaz et la présence restent surveillés.

## 2. Broker

| Paramètre | Valeur |
|---|---|
| Broker | Mosquitto 2, `infra/docker-compose.yml`, sur le PC serveur |
| Adresse | `192.168.137.1:8883` depuis le hotspot (à vérifier : `ipconfig`), `127.0.0.1:8883` pour le backend |
| Transport | **TLS 1.2 minimum**, aucun port 1883 ouvert |
| Authentification | **certificat client obligatoire** (mTLS) ; le CN du certificat est l'identifiant MQTT |
| Anonyme | interdit |
| Autorisations | ACL par CN : `infra/mosquitto/config/acl` (tout ce qui n'est pas listé est refusé) |
| Certificats | ECDSA P-256, `infra/pki/gen-certs.sh` (CA privée Sentinel-X) |

| CN | Rôle | Droits |
|---|---|---|
| `esp-node-01` | boîtier ESP8266 (un CN par boîtier : `esp-node-02`…) | **écrit** uniquement `sentinel/esp-node-01/{telemetry,event,status}` |
| `backend` | backend FastAPI | **lit** `sentinel/#`, n'écrit rien |

Un boîtier compromis ne peut donc ni lire les autres, ni se faire passer pour un autre boîtier (testé : message refusé par l'ACL).

## 3. Conventions

- Préfixe `sentinel/{node}/`, `{node}` = CN du boîtier.
- Payload **JSON UTF-8**, clés courtes, < 256 octets (le backend rejette au-delà de 512).
- `ts` : secondes Unix (UTC) ; `0` si l'ESP n'a pas l'heure, le backend prend alors l'heure de réception.
- `seq` : compteur incrémenté à chaque message (repart à 0 au redémarrage) ; le backend en déduit les messages perdus.
- Publications de l'ESP en **QoS 0** (PubSubClient ne publie qu'en QoS 0) ; le Last Will est en QoS 1.

## 4. Topics

| Topic | Émetteur | Retain | Quand |
|---|---|---|---|
| `sentinel/{node}/telemetry` | ESP | non | toutes les 2 s |
| `sentinel/{node}/event` | ESP | non | dès que le PIR change d'état |
| `sentinel/{node}/status` | ESP + Last Will | **oui** | à la connexion (`online`) ; le broker publie `offline` si l'ESP disparaît |

## 5. Payloads

### `telemetry`

```json
{"seq": 1532, "ts": 1791201600, "gas": 312, "pir": 0, "rssi": -58, "t": 23.4, "h": 41.0}
```

| Champ | Type | Bornes acceptées | Description |
|---|---|---|---|
| `seq` | int | ≥ 0 | obligatoire |
| `ts` | int | ≥ 0 | heure Unix, ou 0 |
| `gas` | int | 0–1023 | lecture brute A0 du MQ-2 |
| `pir` | int | 0 / 1 | état du PIR |
| `rssi` | int | −120–0 | Wi-Fi en dBm |
| `t`, `h` | float | −40–85 °C, 0–100 % | **optionnels** : seulement si un DHT22 est câblé sur l'ESP |

Une valeur hors bornes est ignorée (affichée « — ») ; un message sans `seq` valide est rejeté.

### `event`

```json
{"seq": 1533, "ts": 1791201601, "type": "pir", "v": 1}
```

### `status` (retenu)

```json
{"state": "online", "fw": "0.1.0", "ip": "192.168.137.20"}
```

Last Will : `{"state": "offline"}`.

## 6. Côté backend

- `EDGE=mqtt` : client paho-mqtt (thread dédié, reconnexion 1 s → 30 s), certificats `infra/pki/out/backend.*` par défaut (`MQTT_CA`, `MQTT_CERT`, `MQTT_KEY`, `MQTT_HOST`, `MQTT_PORT`).
- `EDGE=mock` : ESP simulé (défaut avec `PROVIDER=mock`), boutons « Simuler une fuite de gaz / une présence » dans le dashboard. `EDGE=off` : désactivé.
- Alertes : **gaz** ≥ `GAS_ALERT_RAW` (600 par défaut, *critical*), **présence PIR** (*warning*), **perte de l'ESP** (module `esp8266`, *critical*) si broker injoignable, Last Will `offline`, ou aucun message depuis `EDGE_TIMEOUT_S` (10 s).
- API : `GET /api/edge` (compte requis) ; WebSocket `/ws` : `hello.edge` puis un message `edge` à chaque mesure.
- Score de menace (`backend/app/ai/threat.py`) : le PIR compte pour 10 % de la somme pondérée ; le gaz impose un plancher (0 sous la moitié de `GAS_ALERT_RAW`, 70 = « Menace » au seuil). Un boîtier hors ligne ou muet ne compte pas.

## 7. Tests rapides (depuis `infra/`, broker lancé)

```bash
# Simuler l'ESP (certificat du boîtier)
mosquitto_pub -h 127.0.0.1 -p 8883 --cafile pki/out/ca.crt --cert pki/out/esp-node-01.crt --key pki/out/esp-node-01.key \
  -t sentinel/esp-node-01/telemetry -m '{"seq":1,"ts":0,"gas":750,"pir":1,"rssi":-58}'

# Écouter comme le backend
mosquitto_sub -h 127.0.0.1 -p 8883 --cafile pki/out/ca.crt --cert pki/out/backend.crt --key pki/out/backend.key -t 'sentinel/#' -v

# Preuves pour la soutenance — doivent être REFUSÉS :
mosquitto_sub -h 127.0.0.1 -p 8883 --cafile pki/out/ca.crt -t 'sentinel/#'                       # sans certificat client
mosquitto_pub -h 127.0.0.1 -p 8883 --cafile pki/out/ca.crt --cert pki/out/esp-node-01.crt --key pki/out/esp-node-01.key \
  -t sentinel/esp-node-02/telemetry -m '{"seq":1,"gas":999}'                                     # usurpation d'un autre boîtier (ACL)
```

Wireshark sur le port 8883 : seuls des enregistrements TLS sont visibles, aucune donnée en clair.
