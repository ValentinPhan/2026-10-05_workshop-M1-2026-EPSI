# Firmware Edge Node ESP8266

Lit le gaz (MQ-2), la présence (PIR) et, en option, un DHT22, puis publie en **MQTTS** (TLS 1.2 + certificat client) vers le broker Mosquitto du PC. Contrat : [`docs/mqtt-contract.md`](../../docs/mqtt-contract.md).

## Câblage (NodeMCU v2)

| Capteur | Broche ESP | Remarque |
|---|---|---|
| MQ-2, sortie analogique AO | A0 | **pont diviseur obligatoire** : la sortie du module va jusqu'à 5 V, A0 du NodeMCU accepte 0–3,3 V (ex. 10 kΩ / 20 kΩ) ; chauffe du MQ-2 en 5 V (VIN), préchauffe ≈ 24 h pour des valeurs stables |
| PIR HC-SR501, OUT | D5 (GPIO14) | sortie 3,3 V, alimentation 5 V (VIN) |
| DHT22 (optionnel) | D4 (GPIO2) | 3,3 V ; mettre `HAS_DHT 1` dans `config.h` |
| GND communs | GND | |

## Compiler et téléverser

1. Générer les certificats (une fois, sur le PC serveur, Git Bash) : `infra/pki/gen-certs.sh`
   (`BROKER_IP=… ./gen-certs.sh` si le PC n'est pas en `192.168.137.1`).
2. `cp infra/pki/out/esp-node-01.h firmware/esp8266/include/certs.h`
3. `cp firmware/esp8266/include/config.example.h firmware/esp8266/include/config.h` puis renseigner le Wi-Fi et l'IP du PC.
4. Avec PlatformIO (extension VS Code ou `pip install platformio`), dans `firmware/esp8266/` : `pio run -t upload`, puis `pio device monitor`.

`config.h` et `certs.h` sont ignorés par git : **ils contiennent le mot de passe Wi-Fi et la clé privée du boîtier**.

## Comportement

- Télémétrie toutes les 2 s ; événement immédiat quand le PIR change d'état.
- Heure : NTP (`NTP_SERVER`) si le hotspot a Internet, sinon **heure de compilation** pour vérifier la validité des certificats (ils doivent avoir été générés avant la compilation).
- Le broker est authentifié par la CA Sentinel-X (`setTrustAnchors`) ; connexion par IP (pas de DNS sur le hotspot), donc sans vérification du nom d'hôte.
- Tampons TLS de 512 octets si le broker accepte la fragmentation (économise ~16 Ko de RAM).
- Reconnexion MQTT avec backoff 1 s → 30 s, sans bloquer la lecture des capteurs ; Last Will `offline` retenu.

## Dépannage (moniteur série, 115200 bauds)

- `échec MQTT (état -2, erreur TLS …)` : broker injoignable (IP, pare-feu Windows sur 8883, `docker compose ps`) ou certificat refusé (heure, CA régénérée sans recompiler).
- `état 5` : refusé par le broker (CN absent de l'ACL).

**Non testé sur un vrai ESP8266** : le code a été vérifié contre les signatures du cœur ESP8266 et de PubSubClient, mais la compilation PlatformIO n'a pas pu être faite dans l'environnement de développement (registre bloqué). À compiler et valider sur la carte.
