// Sentinel-X : firmware Arduino Uno R3 (Elegoo) — ultrason HC-SR04 + servomoteur (SG90).
//
// Liaison série USB avec le Raspberry Pi, 115200 bauds, une ligne par message.
//
// Arduino -> Pi, toutes les REPORT_MS (une ligne JSON) :
//   {"distanceCm":123.4,"angle":12.0,"target":30.0,"moving":true,"mode":"manual","speed":40.0}
//   distanceCm = 400 si aucun écho (rien dans la portée)
//
// Pi -> Arduino (une commande par ligne, voir server/src/providers/motor.js) :
//   MOVE <angle>   aller à un angle absolu, -90..90
//   SPEED <v>      vitesse en °/s, 5..90
//   SWEEP 1|0      balayage automatique on/off
//   STOP           arrêt immédiat
//
// Angle « dashboard » : 0 = vers l'avant. Servo : 90° = vers l'avant (servo = 90 + angle).
// Si le radar tourne dans le mauvais sens, passer SERVO_DIR à -1.
//
// Câblage :  HC-SR04  VCC->5V  Trig->D7  Echo->D8  GND->GND
//            Servo    signal->D9, + -> 5 V d'une alimentation séparée, - -> GND commun avec l'Arduino
// D0 et D1 sont réservées à la liaison USB : ne rien y brancher.
#include <Servo.h>

const uint8_t PIN_TRIG = 7;
const uint8_t PIN_ECHO = 8;
const uint8_t PIN_SERVO = 9;

const int SERVO_DIR = 1;               // 1 ou -1
const float MIN_ANGLE = -90, MAX_ANGLE = 90;
const float MIN_SPEED = 5, MAX_SPEED = 90;
const float SWEEP_ANGLE = 60;          // amplitude du balayage automatique

const float MAX_RANGE_CM = 400;
const unsigned long ECHO_TIMEOUT_US = 25000UL;  // ~4 m aller-retour
const unsigned long MEASURE_MS = 60;   // période de mesure ultrason (>= 50 ms pour éviter les échos parasites)
const unsigned long REPORT_MS = 100;   // période d'envoi vers le Pi
const unsigned long MOTOR_MS = 20;     // pas de mise à jour du servo

Servo servo;
float angle = 0, target = 0, speedDps = 40;
bool sweeping = false;
int sweepDir = 1;
bool moving = false;
float distanceCm = MAX_RANGE_CM;

char line[32];
uint8_t lineLen = 0;

float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }

void writeServo() {
  servo.write((int)(90 + SERVO_DIR * angle + 0.5f));
}

void measure() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);
  unsigned long us = pulseIn(PIN_ECHO, HIGH, ECHO_TIMEOUT_US);
  distanceCm = us ? min(us / 58.0f, MAX_RANGE_CM) : MAX_RANGE_CM;
}

void stepMotor(float dt) {
  if (sweeping) {
    target = sweepDir * SWEEP_ANGLE;
    if (fabs(angle - target) < 1) sweepDir = -sweepDir;
  }
  float diff = target - angle;
  float maxStep = speedDps * dt;
  moving = fabs(diff) > 0.5f;
  angle = fabs(diff) <= maxStep ? target : angle + (diff > 0 ? maxStep : -maxStep);
  writeServo();
}

void report() {
  Serial.print(F("{\"distanceCm\":"));
  Serial.print(distanceCm, 1);
  Serial.print(F(",\"angle\":"));
  Serial.print(angle, 1);
  Serial.print(F(",\"target\":"));
  Serial.print(target, 1);
  Serial.print(F(",\"moving\":"));
  Serial.print(moving ? F("true") : F("false"));
  Serial.print(F(",\"mode\":\""));
  Serial.print(sweeping ? F("sweep") : F("manual"));
  Serial.print(F("\",\"speed\":"));
  Serial.print(speedDps, 1);
  Serial.println('}');
}

void handleCommand(char* cmd) {
  char* arg = strchr(cmd, ' ');
  if (arg) { *arg = 0; arg++; }
  if (!strcmp(cmd, "MOVE") && arg) {
    sweeping = false;
    target = clampf(atof(arg), MIN_ANGLE, MAX_ANGLE);
  } else if (!strcmp(cmd, "SPEED") && arg) {
    speedDps = clampf(atof(arg), MIN_SPEED, MAX_SPEED);
  } else if (!strcmp(cmd, "SWEEP") && arg) {
    sweeping = atoi(arg) != 0;
    if (!sweeping) target = angle;
  } else if (!strcmp(cmd, "STOP")) {
    sweeping = false;
    target = angle;
  }
  // commande inconnue : ignorée
}

void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (lineLen) { line[lineLen] = 0; handleCommand(line); }
      lineLen = 0;
    } else if (lineLen < sizeof(line) - 1) {
      line[lineLen++] = c;
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  servo.attach(PIN_SERVO);
  writeServo();  // position de départ : face avant
}

void loop() {
  static unsigned long lastMeasure = 0, lastReport = 0, lastMotor = 0;
  unsigned long now = millis();

  readSerial();
  if (now - lastMotor >= MOTOR_MS) {
    stepMotor((now - lastMotor) / 1000.0f);
    lastMotor = now;
  }
  if (now - lastMeasure >= MEASURE_MS) {
    measure();
    lastMeasure = now;
  }
  if (now - lastReport >= REPORT_MS) {
    report();
    lastReport = now;
  }
}
