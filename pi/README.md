# Raspberry Pi 3 — montage et mise en service

Matériel : Raspberry Pi 3 Model B, caméra Raspberry Pi (nappe CSI), moteur 28BYJ-48 + carte ULN2003, capteur ultrason HC-SR04, capteur DHT22 (module 3 broches « V182 »).
Pas de matrice thermique : le dashboard masque ce module. L'ESP32 et le Uno ne font pas partie du boîtier.

**Toujours câbler Pi éteint et débranché.** Les GPIO sont en 3,3 V : tout signal 5 V sur une broche GPIO l'endommage.

Matériel à prévoir en plus : fils Dupont mâle/femelle, une breadboard, **1 résistance de 1 kΩ et 1 de 2 kΩ** (diviseur de tension du HC-SR04), carte SD, alimentation micro-USB 5 V 2,5 A.

## Étape 1 — Installer le système

1. Sur le PC, installer *Raspberry Pi Imager*. Choisir « Raspberry Pi OS Lite (64-bit) ».
2. Dans les réglages avancés (roue crantée) : nom `sentinel`, utilisateur `pi` + mot de passe, Wi-Fi du PC, **SSH activé**.
3. Écrire la SD, l'insérer dans le Pi, brancher l'alimentation. Attendre 2 minutes.
4. Depuis le PC : `ssh pi@sentinel.local` (ou `ssh pi@<adresse IP>`). Si la connexion fonctionne, passer à la suite.

## Étape 2 — Tester la caméra (nappe déjà branchée)

`rpicam-hello --list-cameras` doit lister une caméra (avec une ancienne version du système : `libcamera-hello`). Si elle n'apparaît pas, rebrancher la nappe Pi éteint : **côté contacts métalliques vers le HDMI**, languette du connecteur bien rabattue.

## Étape 2 bis — Flux vidéo vers le dashboard

Rien à installer : `pi/camera_stream.py` (bibliothèque standard Python) est lancé automatiquement par l'agent. Il diffuse la caméra en MJPEG sur le port 8080 et n'allume la caméra que lorsqu'on regarde.
Test, une fois le Pi installé (étape 3) : `python3 ~/sentinel-x/pi/camera_stream.py`, puis ouvrir `http://<ip du Pi>:8080/stream.mjpg` dans le navigateur du PC. Arrêter avec Ctrl+C.
Webcam USB à la place de la caméra : `--cmd "ffmpeg -loglevel error -f v4l2 -i /dev/video0 -f mjpeg -q:v 5 -"`.

## Étape 3 — Installer les logiciels

```bash
sudo apt update && sudo apt install -y git python3-gpiozero python3-lgpio python3-pip
pip3 install --break-system-packages adafruit-circuitpython-dht   # seulement si le pilote noyau DHT22 est absent
git clone https://github.com/ValentinPhan/2026-10-05_workshop-M1-2026-EPSI ~/sentinel-x
cd ~/sentinel-x && git checkout claude/funny-einstein-p0e7f3
```

## Étape 4 — Câbler le DHT22

| DHT22 | Pi (broche physique) |
|---|---|
| + | 3,3 V (1) |
| out | GPIO4 (7) |
| − | GND (6) |

Test : `python3 ~/sentinel-x/pi/dht22_reader.py` → une ligne JSON toutes les 2 s (température et humidité plausibles).
Recommandé : ajouter `dtoverlay=dht11,gpiopin=4` à `/boot/firmware/config.txt` puis redémarrer (lecture plus fiable).

## Étape 5 — Câbler l'ultrason HC-SR04

| HC-SR04 | Pi (broche physique) |
|---|---|
| VCC | 5 V (2) |
| Trig | GPIO23 (16) |
| Echo | **diviseur ci-dessous** → GPIO24 (18) |
| GND | GND (9) |

Diviseur (Echo sort en 5 V) : fil Echo → résistance **1 kΩ** → point milieu relié à GPIO24 ; du point milieu → résistance **2 kΩ** → GND.

Test : `python3 -c "from gpiozero import DistanceSensor as D; s=D(echo=24,trigger=23,max_distance=4); print(s.distance*100,'cm')"` — la valeur suit votre main.

## Étape 6 — Câbler le moteur (carte ULN2003)

| ULN2003 | Pi (broche physique) |
|---|---|
| IN1 | GPIO17 (11) |
| IN2 | GPIO18 (12) |
| IN3 | GPIO27 (13) |
| IN4 | GPIO22 (15) |
| + | 5 V (4) |
| − | GND (14) |

Le moteur se branche sur la carte avec sa prise blanche. Fixer l'ultrason sur l'axe du moteur, **orienté vers l'avant avant la mise sous tension** : au démarrage, la position courante vaut 0° (pas de capteur de position).

## Étape 7 — Tester l'agent seul

```bash
python3 ~/sentinel-x/pi/sentinel_agent.py --period 1
```

Un snapshot JSON par seconde s'affiche. Pour tester le moteur, taper puis valider : `{"type":"move","angle":30}` (le capteur tourne de 30°), `{"type":"stop"}`. Quitter avec Ctrl+C.
Sens de rotation inversé : mettre `MOTOR_DIR = -1` dans `sentinel_agent.py`.

## Étape 8 — Lancer le dashboard sur le PC

```bash
SSH_PASSWORD=<mot de passe du Pi> PROVIDER=ssh SSH_HOST=sentinel.local npm run dev
# ou avec une clé :  SSH_KEY=~/.ssh/id_ed25519 PROVIDER=ssh SSH_HOST=<IP> npm run dev
```

Ouvrir http://localhost:5173 et vérifier : distance et radar réagissent à la main, les boutons du panneau Moteur font tourner le capteur, le DHT22 s'affiche. Débrancher le Wi-Fi du Pi : le serveur réessaie tout seul (1 s, 2 s, 5 s, 10 s).

## Test sans Raspberry

`PROVIDER=ssh AGENT_LOCAL=1 npm run dev` lance l'agent en mode simulé (`--fake`) sur le PC.

## Flux vidéo et détection YOLO

Le dashboard ouvre le flux du Pi directement : `http://<ip du Pi>:8080/stream.mjpg` (déduit de `SSH_HOST` ; `CAMERA=0` le désactive, `STREAM_PORT` et `STREAM_URL` le modifient).
Si l'image n'apparaît pas, le dashboard affiche un avertissement avec l'adresse à tester dans le navigateur.
La détection YOLO lit le même flux, depuis le PC : `python yolo_workshop/yolo_intrusion.py http://<ip du Pi>:8080/stream.mjpg` (sans argument, elle utilise la webcam du PC).
