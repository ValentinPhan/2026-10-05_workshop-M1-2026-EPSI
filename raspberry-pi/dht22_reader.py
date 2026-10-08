#!/usr/bin/env python3
"""Lecture du DHT22 / AM2302 sur le Raspberry Pi -> une ligne JSON par mesure sur stdout.

Câblage (module 3 broches) :  +  -> broche 1 (3,3 V, PAS 5 V : la ligne de données irait à 5 V)
                              out -> GPIO4 (broche 7)
                              -  -> broche 6 (GND)
La résistance de tirage est déjà sur le module.

Méthode recommandée : le pilote du noyau (timing à la µs, bien plus fiable que Python).
    /boot/firmware/config.txt :   dtoverlay=dht11,gpiopin=4     (le pilote "dht11" gère aussi le DHT22)
    puis redémarrer ; les valeurs apparaissent dans /sys/bus/iio/devices/iio:device*/
Repli : bibliothèque Adafruit (pip install adafruit-circuitpython-dht ; apt install libgpiod2).

Sortie (champ `environment` du snapshot, voir backend/app/providers/ssh.py) :
    {"tempC": 22.8, "humidityPct": 47.3, "readAt": 1759651200000}

Le Pi ne fait que lire : l'analyse (anomalies) est faite par le modèle IA sur le PC (ml/environment/env_model.py).
Usage :  python3 dht22_reader.py [--gpio 4] [--period 2] [--csv dht22_log.csv]
"""
import argparse
import glob
import json
import sys
import time

MIN_PERIOD_S = 2.0  # le DHT22 ne supporte pas plus d'une mesure toutes les 2 s


def iio_reader():
    """Lecteur via le pilote noyau (dtoverlay=dht11). None si le pilote n'est pas chargé."""
    devices = [d for d in glob.glob("/sys/bus/iio/devices/iio:device*") if glob.glob(f"{d}/in_humidityrelative_input")]
    if not devices:
        return None
    dev = devices[0]

    def read():
        with open(f"{dev}/in_temp_input") as f:
            t = int(f.read()) / 1000  # milli-°C
        with open(f"{dev}/in_humidityrelative_input") as f:
            h = int(f.read()) / 1000  # milli-%
        return t, h

    return read


def adafruit_reader(gpio):
    import adafruit_dht  # import tardif : seulement si le pilote noyau est absent
    import board

    sensor = adafruit_dht.DHT22(getattr(board, f"D{gpio}"), use_pulseio=False)

    def read():
        t, h = sensor.temperature, sensor.humidity
        if t is None or h is None:
            raise OSError("lecture vide")
        return t, h

    return read


def plausible(t, h, prev):
    """Rejette les lectures aberrantes (bits corrompus malgré le checksum)."""
    if not (-40 <= t <= 80 and 0 <= h <= 100):
        return False
    return prev is None or abs(t - prev[0]) <= 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpio", type=int, default=4)
    ap.add_argument("--period", type=float, default=MIN_PERIOD_S)
    ap.add_argument("--csv", help="journalise aussi les mesures (données d'entraînement de ml/environment/env_model.py)")
    args = ap.parse_args()
    period = max(args.period, MIN_PERIOD_S)

    read = iio_reader() or adafruit_reader(args.gpio)
    log = open(args.csv, "a", buffering=1) if args.csv else None
    if log and log.tell() == 0:
        log.write("ts,temp,hum\n")

    prev = None
    while True:
        started = time.monotonic()
        try:
            t, h = read()
            if plausible(t, h, prev):
                prev = (t, h)
                ts = int(time.time() * 1000)
                print(json.dumps({"tempC": round(t, 1), "humidityPct": round(h, 1), "readAt": ts}), flush=True)
                if log:
                    log.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')},{t:.1f},{h:.1f}\n")
        except (OSError, RuntimeError) as err:  # checksum / timeout : fréquent, on réessaie au tour suivant
            print(f"lecture DHT22 ratée : {err}", file=sys.stderr)
        time.sleep(max(0.0, period - (time.monotonic() - started)))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
