# Heure de compilation, utilisée par le firmware pour vérifier la validité des certificats TLS
# quand il n'obtient pas l'heure en NTP (hotspot sans Internet). Voir src/main.cpp, setupClock().
import time

Import("env")  # noqa: F821 — fourni par PlatformIO
env.Append(CPPDEFINES=[("BUILD_UNIX_TIME", int(time.time()))])  # noqa: F821
