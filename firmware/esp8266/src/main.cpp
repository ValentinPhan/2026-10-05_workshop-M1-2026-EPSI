// Sentinel-X — Edge Node ESP8266 : gaz (MQ-2), présence (PIR), [température / humidité (DHT22)]
// publiés en MQTTS (TLS 1.2 + certificat client ECDSA) vers le broker Mosquitto du PC serveur.
// Contrat des messages : docs/mqtt-contract.md.
#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <WiFiClientSecure.h>
#include <time.h>

#include "certs.h"   // généré par infra/pki/gen-certs.sh (out/<NODE_ID>.h), ignoré par git
#include "config.h"  // copie de config.example.h, ignorée par git

#if HAS_DHT
#include <DHT.h>
static DHT dht(DHT_PIN, DHT22);
#endif

static BearSSL::WiFiClientSecure net;
static BearSSL::X509List caCert(CA_CERT);
static BearSSL::X509List clientCert(CLIENT_CERT);
static BearSSL::PrivateKey clientKey(CLIENT_KEY);
static PubSubClient mqtt(net);
static const IPAddress brokerIp(BROKER_IP);

static char topicTelemetry[64], topicEvent[64], topicStatus[64];
static uint32_t seq = 0;
static int lastPir = -1;
static unsigned long lastTelemetry = 0, nextTry = 0, backoffMs = 1000;

static const time_t VALID_TIME = 1700000000;  // en dessous : l'horloge n'est pas réglée

static uint32_t unixTime() {
  time_t t = time(nullptr);
  return t > VALID_TIME ? (uint32_t)t : 0;  // 0 = « pas encore l'heure » : le backend prend l'heure de réception
}

// BearSSL vérifie la période de validité des certificats : il lui faut l'heure AVANT la connexion TLS.
static void setupClock() {
  configTime(0, 0, NTP_SERVER);
  unsigned long start = millis();
  while (time(nullptr) < VALID_TIME && millis() - start < 5000) delay(100);
  if (time(nullptr) < VALID_TIME) {
    Serial.println(F("NTP indisponible : validité des certificats vérifiée avec l'heure de compilation"));
    net.setX509Time(BUILD_UNIX_TIME);
  }
}

static void setupTls() {
  net.setTrustAnchors(&caCert);  // seul le broker signé par la CA Sentinel-X est accepté
  net.setClientECCert(&clientCert, &clientKey, BR_KEYTYPE_SIGN, BR_KEYTYPE_EC);
  // Petits tampons TLS si le broker accepte de fragmenter (économise ~16 Ko de RAM), sinon tampons par défaut.
  if (net.probeMaxFragmentLength(brokerIp, BROKER_PORT, 512)) {
    net.setBufferSizes(512, 512);
    Serial.println(F("TLS : fragments de 512 octets"));
  }
}

static bool connectMqtt() {
  Serial.print(F("MQTTS -> "));
  Serial.println(brokerIp);
  // Last Will : le broker publie « offline » (retenu) si l'ESP disparaît sans prévenir
  if (!mqtt.connect(NODE_ID, nullptr, nullptr, topicStatus, 1, true, "{\"state\":\"offline\"}")) {
    Serial.printf("échec MQTT (état %d, erreur TLS %d)\n", mqtt.state(), net.getLastSSLError());
    return false;
  }
  char buf[96];
  snprintf(buf, sizeof buf, "{\"state\":\"online\",\"fw\":\"%s\",\"ip\":\"%s\"}", FW_VERSION, WiFi.localIP().toString().c_str());
  mqtt.publish(topicStatus, buf, true);
  Serial.println(F("MQTTS connecté"));
  return true;
}

static void publishPir(int pir) {
  char buf[96];
  snprintf(buf, sizeof buf, "{\"seq\":%lu,\"ts\":%lu,\"type\":\"pir\",\"v\":%d}", (unsigned long)++seq, (unsigned long)unixTime(), pir);
  if (mqtt.connected()) mqtt.publish(topicEvent, buf);
}

static void publishTelemetry() {
  char buf[200];
  int n = snprintf(buf, sizeof buf, "{\"seq\":%lu,\"ts\":%lu,\"gas\":%d,\"pir\":%d,\"rssi\":%d",
                   (unsigned long)++seq, (unsigned long)unixTime(), analogRead(A0), digitalRead(PIR_PIN), WiFi.RSSI());
#if HAS_DHT
  float t = dht.readTemperature(), h = dht.readHumidity();
  if (!isnan(t) && !isnan(h)) n += snprintf(buf + n, sizeof buf - n, ",\"t\":%.1f,\"h\":%.1f", t, h);
#endif
  snprintf(buf + n, sizeof buf - n, "}");
  if (mqtt.connected()) mqtt.publish(topicTelemetry, buf);  // seq avance même hors ligne : le backend compte les pertes
}

void setup() {
  Serial.begin(115200);
  Serial.printf("\nSentinel-X Edge Node %s (fw %s)\n", NODE_ID, FW_VERSION);
  pinMode(PIR_PIN, INPUT);
#if HAS_DHT
  dht.begin();
#endif
  snprintf(topicTelemetry, sizeof topicTelemetry, "sentinel/%s/telemetry", NODE_ID);
  snprintf(topicEvent, sizeof topicEvent, "sentinel/%s/event", NODE_ID);
  snprintf(topicStatus, sizeof topicStatus, "sentinel/%s/status", NODE_ID);

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print(F("Wi-Fi"));
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
    Serial.print('.');
  }
  Serial.println(WiFi.status() == WL_CONNECTED ? WiFi.localIP().toString() : String(F(" pas encore connecté")));

  setupClock();
  setupTls();
  mqtt.setServer(brokerIp, BROKER_PORT);  // par IP : pas de DNS sur le hotspot
  mqtt.setBufferSize(256);
  mqtt.setKeepAlive(15);
  mqtt.setSocketTimeout(5);
}

void loop() {
  if (WiFi.status() == WL_CONNECTED && !mqtt.connected() && millis() >= nextTry) {
    if (connectMqtt()) {
      backoffMs = 1000;
    } else {
      nextTry = millis() + backoffMs;  // 1 s, 2 s, 4 s… 30 s max, sans bloquer la lecture des capteurs
      backoffMs = min(backoffMs * 2, 30000UL);
    }
  }
  mqtt.loop();

  int pir = digitalRead(PIR_PIN);
  if (pir != lastPir) {  // événement immédiat, sans attendre la prochaine télémétrie
    lastPir = pir;
    publishPir(pir);
  }
  if (millis() - lastTelemetry >= TELEMETRY_MS) {
    lastTelemetry = millis();
    publishTelemetry();
  }
  delay(10);
}
