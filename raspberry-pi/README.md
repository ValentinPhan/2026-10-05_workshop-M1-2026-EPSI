# Raspberry Pi 3 — montage et mise en service

Matériel : Raspberry Pi 3, caméra Raspberry Pi v1 (nappe CSI), micro-servo SG90, capteur ultrason HC-SR04, DHT22 (module 3 broches « V182 »).
Pas de matrice thermique : le snapshot envoie `thermal: null`, le dashboard masque ce panneau et la santé des modules ne la signale pas en panne.

Le Pi ne fait **aucun calcul d'IA** : `sentinel_agent.py` lit les capteurs et pilote le servo ; le backend (sur le PC) le lance par SSH.

**Toujours câbler Pi éteint et débranché.** Les GPIO sont en 3,3 V : un signal 5 V sur une broche GPIO l'endommage.
À prévoir : fils Dupont, breadboard, **une résistance de 1 kΩ et une de 2 kΩ** (diviseur du HC-SR04), alimentation 5 V 2,5 A.

## 1. Système et SSH

1. *Raspberry Pi Imager* → « Raspberry Pi OS Lite » ; réglages avancés : nom `sentinel`, utilisateur `pi`, Wi-Fi du hotspot du PC, **SSH activé**.
2. Depuis le PC : `ssh pi@sentinel.local` (ou `ssh pi@<IP>`). Fixer l'IP du Pi (réservation DHCP du hotspot ou IP statique).
3. **Clé SSH plutôt que mot de passe** (depuis le PC) : `ssh-keygen -t ed25519` puis `ssh-copy-id pi@<IP>`.
   La première connexion enregistre l'empreinte du Pi dans `~/.ssh/known_hosts` : le backend refuse ensuite un appareil qui se ferait passer pour lui.

## 2. Logiciels

```bash
sudo apt update && sudo apt install -y git python3-gpiozero python3-lgpio
sudo apt install -y pigpio python3-pigpio && sudo systemctl enable --now pigpiod   # PWM matériel : servo sans tremblement
git clone https://github.com/ValentinPhan/2026-10-05_workshop-M1-2026-EPSI ~/sentinel-x
```

Le backend lance par défaut `python3 -u ~/sentinel-x/raspberry-pi/sentinel_agent.py` (autre chemin : variable `SSH_COMMAND`).

## 3. Câblage

| Composant | Broche du composant | Pi (BCM, broche physique) |
|---|---|---|
| DHT22 | + / out / − | 3,3 V (1) / **GPIO4 (7)** / GND (9) |
| HC-SR04 | VCC / Trig / GND | 5 V (4) / **GPIO23 (16)** / GND (6) |
| HC-SR04 | Echo | **diviseur** → **GPIO24 (18)** : Echo → 1 kΩ → point milieu (vers GPIO24) → 2 kΩ → GND |
| Servo SG90 | signal (orange) / + (rouge) / − (marron) | **GPIO18 (12)** / 5 V (2) / GND (14) |

- DHT22 : ajouter `dtoverlay=dht11,gpiopin=4` à `/boot/firmware/config.txt` puis redémarrer (lecture plus fiable, voir `dht22_reader.py`).
- Servo : il peut tirer jusqu'à ~0,6 A en forçant. Si le Pi redémarre quand le servo bouge, l'alimenter par une source 5 V séparée (GND commun avec le Pi).
- Fixer l'ultrason sur le palonnier du servo, **orienté face avant quand le servo est à 0°** (au démarrage, l'agent le centre).

## 4. Tester l'agent seul (sur le Pi)

```bash
python3 ~/sentinel-x/raspberry-pi/sentinel_agent.py --period 1
```

Un snapshot JSON par seconde. Taper puis Entrée : `{"type":"move","angle":45}` (le servo tourne), `{"type":"sweep","enabled":true}`, `{"type":"stop"}`. Ctrl+D ou Ctrl+C pour quitter.
- Servo inversé par rapport au dashboard : `SERVO_DIR = -1` ; course trop courte ou butée qui force : ajuster `SERVO_MIN_PULSE` / `SERVO_MAX_PULSE`.
- Distance toujours à 400 cm ou absente : vérifier le diviseur et Trig/Echo inversés.

## 5. Brancher le dashboard (sur le PC)

Dans `backend/.env` :

```
PROVIDER=ssh
SSH_HOST=<IP du Pi>
SSH_USER=pi
# SSH_KEY=C:\Users\<vous>\.ssh\id_ed25519     (vide = clés par défaut de ~/.ssh)
```

Puis F5 / `npm run dev`. Vérifier : distance et radar suivent la main, les boutons du panneau Moteur font tourner le servo, le DHT22 s'affiche.
Couper le Wi-Fi du Pi : alerte « Perte de connexion : Raspberry Pi » au bout de 5 s, le backend réessaie seul (1, 2, 5 puis 10 s), alerte résolue au retour.

**Sans Raspberry** : `PROVIDER=ssh AGENT_LOCAL=1` lance l'agent en mode `--fake` sur le PC (tout le chemin, sauf le réseau).
