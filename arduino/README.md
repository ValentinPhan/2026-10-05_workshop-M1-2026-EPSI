# Arduino (Elegoo Uno R3) — ultrason + servo

Firmware : `sentinel_io/sentinel_io.ino`. Hypothèse : capteur **HC-SR04** et servo **SG90** (kit Elegoo). Si le moteur est un 28BYJ-48 (5 fils + carte ULN2003), le code du moteur est à adapter.

## Câblage

| Composant | Broche | Arduino |
|---|---|---|
| HC-SR04 | VCC | 5V |
| HC-SR04 | Trig | D7 |
| HC-SR04 | Echo | D8 |
| HC-SR04 | GND | GND |
| Servo | signal (orange/jaune) | D9 |
| Servo | + (rouge) | 5 V d'une **alimentation séparée** (≥ 1 A) |
| Servo | − (marron/noir) | − de l'alimentation **et** GND Arduino (masse commune) |

**Ne rien brancher sur D0 / D1** : elles servent à la liaison USB. Un fil dessus bloque le téléversement (débranchez-le avant) et perturbe la communication.

## Installer et tester

1. Arduino IDE 2 → *Outils → Type de carte → Arduino Uno*, puis choisir le port.
2. Ouvrir `sentinel_io/sentinel_io.ino`, cliquer ✓ puis →.
3. *Outils → Moniteur série*, **115200 bauds**, fin de ligne « Nouvelle ligne » :
   - des lignes JSON défilent, `distanceCm` suit votre main ;
   - tapez `MOVE 45` : le servo tourne doucement, `angle` progresse jusqu'à 45 ;
   - `SWEEP 1` lance le balayage, `STOP` l'arrête.

## Protocole série (115200 bauds, 1 ligne par message)

- Arduino → Pi, 10 fois par seconde : `{"distanceCm":123.4,"angle":12.0,"target":30.0,"moving":true,"mode":"manual","speed":40.0}`
- Pi → Arduino : `MOVE <-90..90>` · `SPEED <5..90>` · `SWEEP 1|0` · `STOP`

Angle du dashboard 0° = servo à 90° (face avant). Si le sens est inversé, mettre `SERVO_DIR = -1` dans le firmware.
