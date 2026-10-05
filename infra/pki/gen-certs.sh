#!/usr/bin/env bash
# Génère la PKI Sentinel-X (ECDSA P-256, léger pour l'ESP8266) dans infra/pki/out/.
# Usage : ./gen-certs.sh [CN supplémentaires...]   ex. ./gen-certs.sh esp-node-02
# Les clés privées ne doivent JAMAIS être commitées (out/ est dans .gitignore).
set -euo pipefail

cd "$(dirname "$0")"
OUT=out
DAYS=825
mkdir -p "$OUT"

newkey() { openssl ecparam -name prime256v1 -genkey -noout -out "$1"; }

if [[ ! -f "$OUT/ca.key" ]]; then
  newkey "$OUT/ca.key"
  openssl req -x509 -new -key "$OUT/ca.key" -sha256 -days 3650 \
    -subj "/O=Sentinel-X/CN=Sentinel-X Root CA" -out "$OUT/ca.crt"
  echo "CA créée"
fi

# sign <cn> <extensions>
sign() {
  local cn=$1 ext=$2
  [[ -f "$OUT/$cn.crt" ]] && { echo "$cn existe déjà, ignoré"; return; }
  newkey "$OUT/$cn.key"
  openssl req -new -key "$OUT/$cn.key" -subj "/O=Sentinel-X/CN=$cn" -out "$OUT/$cn.csr"
  openssl x509 -req -in "$OUT/$cn.csr" -CA "$OUT/ca.crt" -CAkey "$OUT/ca.key" \
    -CAcreateserial -days "$DAYS" -sha256 -extfile <(printf '%s\n' "$ext") -out "$OUT/$cn.crt"
  rm -f "${OUT:?}/${cn:?}.csr"
  echo "Certificat $cn créé"
}

sign mosquitto "subjectAltName=DNS:mosquitto,DNS:sentinel.local,DNS:localhost,IP:10.50.0.1,IP:127.0.0.1
extendedKeyUsage=serverAuth"

for cn in api ia-anomaly ia-vision esp-node-01 "$@"; do
  sign "$cn" "extendedKeyUsage=clientAuth"
done

chmod 644 "$OUT"/*.crt
chmod 600 "$OUT"/*.key
# Mosquitto tourne en uid 1883 dans le conteneur : il doit pouvoir lire sa clé.
# Durcissement (Cyber 2) : sudo chown 1883:1883 out/mosquitto.key && chmod 600 out/mosquitto.key
chmod 644 "$OUT/mosquitto.key"
