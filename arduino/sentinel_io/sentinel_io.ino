// Sentinel-X : firmware Arduino Uno R3 (Elegoo) — ultrason HC-SR04 + moteur pas à pas 28BYJ-48 (carte ULN2003).
//
// Liaison série USB avec le Raspberry Pi, 115200 bauds, une ligne par message.
//
// Arduino -> Pi, toutes les REPORT_MS (une ligne JSON) :
//   {"distanceCm":123.4,"angle":12.0,"target":30.0,"moving":true,"mode":"manual","speed":40.0}
//   distanceCm = 400 si aucun écho (rien dans la portée)
//
// Pi -> Arduino (une commande par ligne, voir server/src/providers/motor.js) :
//   MOVE <angle>   aller à un angle absolu, -90..90
//   SPEED <v>      vitesse en °/s, 5..MAX_SPEED
//   SWEEP 1|0      balayage automatique on/off
//   STOP           arrêt immédiat
//   ZERO           déclare la position actuelle comme angle 0 (recalage à la main)
//
// ATTENTION : un moteur pas à pas n'a aucun capteur de position. Au démarrage (ou au reset de
// l'Arduino), la position actuelle est considérée comme 0° (face avant). Orientez le capteur
// vers l'avant AVANT de brancher / réinitialiser, ou utilisez ZERO après l'avoir recentré.
//
// Câblage : carte ULN2003  IN1->D8  IN2->D9  IN3->D10  IN4->D11   (D8..D11 = PORTB bits 0..3)
//           HC-SR04        Trig->D6  Echo->D7  VCC->5V  GND->GND
// D0 et D1 sont réservées à la liaison USB : ne rien y brancher.

const uint8_t PIN_TRIG = 6;
const uint8_t PIN_ECHO = 7;

const int MOTOR_DIR = 1;                 // 1 ou -1 : inverse le sens de rotation
const float STEPS_PER_REV = 4076.0f;     // 28BYJ-48 en demi-pas (2038 pas complets, réducteur 63,68:1)
const float STEPS_PER_DEG = STEPS_PER_REV / 360.0f;
const float MIN_ANGLE = -90, MAX_ANGLE = 90;
const float MIN_SPEED = 5;
const float MAX_SPEED = 60;              // au-delà, le 28BYJ-48 décroche (perd des pas)
const float SWEEP_ANGLE = 60;            // amplitude du balayage automatique
const unsigned long IDLE_RELEASE_MS = 500;  // coupe les bobines à l'arrêt (évite la surchauffe)

const float MAX_RANGE_CM = 400;
const unsigned long ECHO_TIMEOUT_US = 25000UL;  // ~4 m aller-retour
const unsigned long MEASURE_MS = 60;     // période de mesure ultrason (>= 50 ms)
const unsigned long REPORT_MS = 100;     // période d'envoi vers le Pi

// Séquence demi-pas pour IN1..IN4 (bit 0 = IN1)
const uint8_t HALF_STEP[8] = {0b0001, 0b0011, 0b0010, 0b0110, 0b0100, 0b1100, 0b1000, 0b1001};

long posSteps = 0;                       // position courante en pas (0 = face avant)
long targetSteps = 0;
uint8_t phase = 0;
bool coilsOn = false;
float target = 0, speedDps = 40;
bool sweeping = false;
int sweepDir = 1;
float distanceCm = MAX_RANGE_CM;

char line[32];
uint8_t lineLen = 0;

float clampf(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
float angleNow() { return posSteps / STEPS_PER_DEG; }

void setCoils(uint8_t bits) { PORTB = (PORTB & 0xF0) | (bits & 0x0F); }

void releaseCoils() { setCoils(0); coilsOn = false; }

void setTarget(float deg) {
  target = clampf(deg, MIN_ANGLE, MAX_ANGLE);
  targetSteps = lroundf(target * STEPS_PER_DEG);
}

// Un pas de moteur si l'intervalle est écoulé.
void stepMotor(unsigned long nowUs, unsigned long nowMs) {
  static unsigned long lastStepUs = 0, lastActiveMs = 0;

  if (sweeping) {
    if (fabs(angleNow() - target) < 1) sweepDir = -sweepDir;
    setTarget(sweepDir * SWEEP_ANGLE);
  }

  if (posSteps == targetSteps) {
    if (coilsOn && nowMs - lastActiveMs > IDLE_RELEASE_MS) releaseCoils();
    return;
  }
  lastActiveMs = nowMs;
  unsigned long interval = (unsigned long)(1000000.0f / (speedDps * STEPS_PER_DEG));
  if (nowUs - lastStepUs < interval) return;
  lastStepUs = nowUs;

  int dir = targetSteps > posSteps ? 1 : -1;
  posSteps += dir;
  phase = (phase + 8 + dir * MOTOR_DIR) & 7;
  setCoils(HALF_STEP[phase]);
  coilsOn = true;
}

// Mesure ultrason sans bloquer (pulseIn arrêterait le moteur pendant jusqu'à 25 ms).
void measure(unsigned long nowMs) {
  static enum { IDLE, WAIT_RISE, WAIT_FALL } state = IDLE;
  static unsigned long lastStartMs = 0, trigUs = 0, riseUs = 0;

  switch (state) {
    case IDLE:
      if (nowMs - lastStartMs < MEASURE_MS) return;
      lastStartMs = nowMs;
      digitalWrite(PIN_TRIG, HIGH);
      delayMicroseconds(10);
      digitalWrite(PIN_TRIG, LOW);
      trigUs = micros();
      state = WAIT_RISE;
      break;
    case WAIT_RISE:
      if (digitalRead(PIN_ECHO)) { riseUs = micros(); state = WAIT_FALL; }
      else if (micros() - trigUs > 30000UL) { distanceCm = MAX_RANGE_CM; state = IDLE; }
      break;
    case WAIT_FALL:
      if (!digitalRead(PIN_ECHO)) {
        distanceCm = min((micros() - riseUs) / 58.0f, MAX_RANGE_CM);
        state = IDLE;
      } else if (micros() - riseUs > ECHO_TIMEOUT_US) { distanceCm = MAX_RANGE_CM; state = IDLE; }
      break;
  }
}

void report() {
  Serial.print(F("{\"distanceCm\":"));
  Serial.print(distanceCm, 1);
  Serial.print(F(",\"angle\":"));
  Serial.print(angleNow(), 1);
  Serial.print(F(",\"target\":"));
  Serial.print(target, 1);
  Serial.print(F(",\"moving\":"));
  Serial.print(posSteps != targetSteps ? F("true") : F("false"));
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
    setTarget(atof(arg));
  } else if (!strcmp(cmd, "SPEED") && arg) {
    speedDps = clampf(atof(arg), MIN_SPEED, MAX_SPEED);
  } else if (!strcmp(cmd, "SWEEP") && arg) {
    sweeping = atoi(arg) != 0;
    if (!sweeping) setTarget(angleNow());
  } else if (!strcmp(cmd, "STOP")) {
    sweeping = false;
    targetSteps = posSteps;
    target = angleNow();
  } else if (!strcmp(cmd, "ZERO")) {
    sweeping = false;
    posSteps = targetSteps = 0;
    target = 0;
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
  DDRB |= 0x0F;  // D8..D11 en sortie
  releaseCoils();
}

void loop() {
  static unsigned long lastReport = 0;
  unsigned long nowMs = millis();

  readSerial();
  stepMotor(micros(), nowMs);
  measure(nowMs);
  if (nowMs - lastReport >= REPORT_MS) {
    report();
    lastReport = nowMs;
  }
}
