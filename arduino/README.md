# Arduino (Elegoo Uno R3) — ultrason + moteur pas à pas 28BYJ-48

Firmware : `sentinel_io/sentinel_io.ino`. Matériel : **HC-SR04** (ultrason) et **28BYJ-48 5 V + carte driver ULN2003** (kit Elegoo).
Le moteur tourne de −90° à +90° autour de la face avant ; le capteur ultrason est fixé dessus pour faire un radar.

## Câblage (Arduino débranché de l'USB)

| Composant | Broche | Arduino |
|---|---|---|
| Carte ULN2003 | IN1 | D8 |
| Carte ULN2003 | IN2 | D9 |
| Carte ULN2003 | IN3 | D10 |
| Carte ULN2003 | IN4 | D11 |
| Carte ULN2003 | + (alim) | 5V |
| Carte ULN2003 | − (alim) | GND |
| HC-SR04 | VCC | 5V |
| HC-SR04 | Trig | D6 |
| HC-SR04 | Echo | D7 |
| HC-SR04 | GND | GND |

- Le moteur se branche sur la carte ULN2003 avec sa prise blanche à 5 broches (détrompée). Laissez le cavalier de la carte en place.
- Le 28BYJ-48 consomme environ 250 mA. Pour les tests sur le PC, l'alimentation par la broche 5V de l'Arduino suffit. Une fois relié au Raspberry Pi, préférez une alimentation 5 V séparée pour la carte ULN2003, avec **GND commun** à l'Arduino.
- **Ne rien brancher sur D0 / D1** : elles servent à la liaison USB. Un fil dessus bloque le téléversement.

## Installer et tester

1. Arduino IDE 2 → *Outils → Type de carte → Arduino Uno*, puis choisir le port.
2. Ouvrir `sentinel_io/sentinel_io.ino`, cliquer ✓ puis →.
3. *Outils → Moniteur série*, **115200 bauds**, fin de ligne « Nouvelle ligne » :
   - des lignes JSON défilent et `distanceCm` suit votre main ;
   - `MOVE 45` : le moteur tourne doucement et `angle` progresse jusqu'à 45 ;
   - `SWEEP 1` lance le balayage, `STOP` l'arrête.

## Points d'attention

- **Pas de capteur de position.** Au démarrage ou au reset, la position courante est prise pour 0°. Placez le capteur vers l'avant avant d'alimenter, ou recentrez-le à la main puis envoyez `ZERO`.
- **Vitesse limitée à 60 °/s** : au-delà, le 28BYJ-48 perd des pas. Le serveur accepte jusqu'à 90 °/s, le firmware écrête.
- **Sens de rotation inversé** : mettre `MOTOR_DIR = -1` dans le firmware.
- **Le moteur vibre sans tourner** : vérifiez l'ordre des fils IN1 à IN4.
- Les bobines sont coupées 0,5 s après l'arrêt pour éviter la surchauffe ; le capteur n'est alors plus maintenu en position, mais l'engrenage est très freiné.

## Protocole série (115200 bauds, 1 ligne par message)

- Arduino → Pi, 10 fois par seconde : `{"distanceCm":123.4,"angle":12.0,"target":30.0,"moving":true,"mode":"manual","speed":40.0}`
- Pi → Arduino : `MOVE <-90..90>` · `SPEED <5..60>` · `SWEEP 1|0` · `STOP` · `ZERO`
