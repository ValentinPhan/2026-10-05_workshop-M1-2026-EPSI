// Copier en include/config.h (ignoré par git) et adapter.
#pragma once

#define WIFI_SSID "SENTINEL-X"          // hotspot du PC serveur (jamais le Wi-Fi de l'école)
#define WIFI_PASS "change-me"

#define NODE_ID "esp-node-01"           // = CN du certificat client (infra/pki/gen-certs.sh) et identifiant MQTT
#define BROKER_IP 192, 168, 137, 1      // PC serveur sur le hotspot Windows (à vérifier : ipconfig)
#define BROKER_PORT 8883
#define NTP_SERVER "pool.ntp.org"       // sans Internet, l'heure de compilation sert à valider les certificats

#define TELEMETRY_MS 2000               // une télémétrie toutes les 2 s
#define PIR_PIN D5                      // HC-SR501 : sortie 3,3 V
// MQ-2 sur A0 : la sortie analogique du module est en 5 V -> pont diviseur obligatoire (A0 du NodeMCU : 0–3,3 V)

#define HAS_DHT 0                       // 1 si un DHT22 est aussi câblé sur l'ESP (sinon t / h ne sont pas envoyés)
#define DHT_PIN D4
