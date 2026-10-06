$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================="
Write-Host " Sentinel-X"
Write-Host "========================================="
Write-Host ""

# ---------------------------------------------------------
# 1. Verification de Docker
# ---------------------------------------------------------

Write-Host "[1/6] Verification de Docker..."

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "ERREUR : Docker n'est pas installe ou n'est pas accessible."
    exit 1
}

try {
    docker info *> $null
}
catch {
    Write-Host "ERREUR : Docker est installe mais le moteur Docker ne fonctionne pas."
    Write-Host "Demarrez Docker Desktop puis relancez ce script."
    exit 1
}

Write-Host "Docker : OK"
Write-Host ""

# ---------------------------------------------------------
# 2. Verification des fichiers
# ---------------------------------------------------------

Write-Host "[2/6] Verification des fichiers..."

if (-not (Test-Path ".\compose.yaml")) {
    Write-Host "ERREUR : compose.yaml est introuvable."
    exit 1
}

Write-Host "compose.yaml : OK"
Write-Host ""

# ---------------------------------------------------------
# 3. Configuration uniquement lors du premier lancement
# ---------------------------------------------------------

Write-Host "[3/6] Verification de la configuration..."

if (Test-Path ".\.env") {

    Write-Host ".env existe deja."
    Write-Host "Configuration existante conservee."
    Write-Host "Aucun mot de passe ne sera redemande."

}
else {

    Write-Host ""
    Write-Host "Premiere installation detectee."
    Write-Host "Creation de la configuration Sentinel-X."
    Write-Host ""

    $PostgresSecure = Read-Host "Choisissez le mot de passe PostgreSQL" -AsSecureString
    $MqttSecure = Read-Host "Saisissez le mot de passe MQTT Sentinel-X" -AsSecureString

    $PostgresPassword = [System.Net.NetworkCredential]::new("", $PostgresSecure).Password
    $MqttPassword = [System.Net.NetworkCredential]::new("", $MqttSecure).Password

    $EnvContent = @"
# PostgreSQL
POSTGRES_ADMIN_USER=sentinel_admin
POSTGRES_ADMIN_PASSWORD=$PostgresPassword

# MQTT - Raspberry Pi
MQTT_HOST=10.145.67.225
MQTT_PORT=1883
MQTT_USER=sentinelel
MQTT_PASSWORD=$MqttPassword
"@

    Set-Content -Path ".\.env" -Value $EnvContent -Encoding UTF8

    Write-Host ""
    Write-Host ".env cree avec succes."

    # Nettoyage des variables contenant les mots de passe
    $PostgresPassword = $null
    $MqttPassword = $null
    $PostgresSecure = $null
    $MqttSecure = $null

    Remove-Variable PostgresPassword -ErrorAction SilentlyContinue
    Remove-Variable MqttPassword -ErrorAction SilentlyContinue
    Remove-Variable PostgresSecure -ErrorAction SilentlyContinue
    Remove-Variable MqttSecure -ErrorAction SilentlyContinue
}

Write-Host ""

# ---------------------------------------------------------
# 4. Validation Docker Compose
# ---------------------------------------------------------

Write-Host "[4/6] Validation de Docker Compose..."

docker compose config --quiet

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERREUR : la configuration Docker Compose est invalide."
    exit 1
}

Write-Host "Configuration Docker Compose : OK"
Write-Host ""

# ---------------------------------------------------------
# 5. Verification / demarrage de PostgreSQL
# ---------------------------------------------------------

Write-Host "[5/6] Verification de PostgreSQL..."

$ContainerRunning = docker ps `
    --filter "name=^sentinel-postgres$" `
    --filter "status=running" `
    --format "{{.Names}}"

if ($ContainerRunning -eq "sentinel-postgres") {

    Write-Host "PostgreSQL est deja demarre."
    Write-Host "Aucune reinstallation necessaire."

}
else {

    Write-Host "PostgreSQL n'est pas demarre."
    Write-Host "Demarrage de l'infrastructure..."

    docker compose up -d

    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERREUR : impossible de demarrer PostgreSQL."
        exit 1
    }
}

# ---------------------------------------------------------
# Attendre que PostgreSQL soit HEALTHY
# ---------------------------------------------------------

$MaxAttempts = 12
$Attempt = 0
$PostgresHealthy = $false

while ($Attempt -lt $MaxAttempts) {

    $Health = docker inspect `
        --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' `
        sentinel-postgres 2>$null

    if ($Health -eq "healthy") {
        $PostgresHealthy = $true
        break
    }

    if ($Health -eq "unhealthy") {

        Write-Host ""
        Write-Host "ERREUR : PostgreSQL est unhealthy."
        Write-Host ""
        Write-Host "Consultez les logs avec :"
        Write-Host "docker logs sentinel-postgres"

        exit 1
    }

    Write-Host "PostgreSQL demarre... Etat : $Health"

    Start-Sleep -Seconds 5
    $Attempt++
}

if (-not $PostgresHealthy) {

    Write-Host ""
    Write-Host "ERREUR : PostgreSQL n'est pas devenu healthy dans le delai attendu."
    Write-Host ""
    Write-Host "Consultez les logs avec :"
    Write-Host "docker logs sentinel-postgres"

    exit 1
}

Write-Host "PostgreSQL : HEALTHY"
Write-Host ""

# ---------------------------------------------------------
# 6. Verification de la connexion au Raspberry / MQTT
# ---------------------------------------------------------

Write-Host "[6/6] Verification du Raspberry Pi / MQTT..."

# ---------------------------------------------------------
# Lecture de la configuration MQTT depuis .env
# ---------------------------------------------------------

$EnvValues = @{}

Get-Content ".\.env" | ForEach-Object {

    if ($_ -match '^\s*([^#][^=]*)=(.*)$') {

        $Key = $matches[1].Trim()
        $Value = $matches[2]

        $EnvValues[$Key] = $Value
    }
}

$MqttHost = $EnvValues["MQTT_HOST"]
$MqttPort = $EnvValues["MQTT_PORT"]
$MqttUser = $EnvValues["MQTT_USER"]
$MqttPassword = $EnvValues["MQTT_PASSWORD"]

if (-not $MqttHost -or
    -not $MqttPort -or
    -not $MqttUser -or
    -not $MqttPassword) {

    Write-Host ""
    Write-Host "ERREUR : configuration MQTT incomplete dans .env."
    exit 1
}

# ---------------------------------------------------------
# Test TCP vers le Raspberry / Mosquitto
# ---------------------------------------------------------

$MqttConnection = Test-NetConnection `
    -ComputerName $MqttHost `
    -Port $MqttPort `
    -WarningAction SilentlyContinue

if (-not $MqttConnection.TcpTestSucceeded) {

    Write-Host ""
    Write-Host "ATTENTION : PostgreSQL fonctionne mais MQTT est inaccessible."
    Write-Host ""
    Write-Host "Raspberry : $MqttHost"
    Write-Host "Port MQTT : $MqttPort"
    Write-Host ""
    Write-Host "Verifier que :"
    Write-Host "- le Raspberry Pi est allume ;"
    Write-Host "- le PC serveur peut joindre le Raspberry ;"
    Write-Host "- Mosquitto est demarre ;"
    Write-Host "- le port TCP $MqttPort est accessible."

    exit 1
}

Write-Host ""
Write-Host "Raspberry Pi     : JOIGNABLE"
Write-Host "Mosquitto TCP    : OK"

# ---------------------------------------------------------
# Test MQTT authentifie depuis Docker
# ---------------------------------------------------------

Write-Host ""
Write-Host "Test de l'authentification MQTT..."

docker run --rm `
    -e MQTT_HOST="$MqttHost" `
    -e MQTT_PORT="$MqttPort" `
    -e MQTT_USER="$MqttUser" `
    -e MQTT_PASSWORD="$MqttPassword" `
    eclipse-mosquitto `
    sh -c 'mosquitto_pub -h "$MQTT_HOST" -p "$MQTT_PORT" -u "$MQTT_USER" -P "$MQTT_PASSWORD" -t "sentinel/healthcheck" -m "Sentinel-X healthcheck"'

$MqttExitCode = $LASTEXITCODE

# ---------------------------------------------------------
# Nettoyage du mot de passe MQTT en memoire
# ---------------------------------------------------------

$MqttPassword = $null
$EnvValues["MQTT_PASSWORD"] = $null

Remove-Variable MqttPassword -ErrorAction SilentlyContinue

# ---------------------------------------------------------
# Verification du resultat MQTT
# ---------------------------------------------------------

if ($MqttExitCode -eq 0) {

    Write-Host "MQTT Auth        : OK"
    Write-Host "MQTT Publication : OK"

}
else {

    Write-Host ""
    Write-Host "ERREUR : connexion MQTT authentifiee impossible."
    Write-Host ""
    Write-Host "Le Raspberry et le port MQTT sont accessibles,"
    Write-Host "mais l'authentification ou la publication MQTT a echoue."
    Write-Host ""
    Write-Host "Verifier :"
    Write-Host "- MQTT_USER dans .env ;"
    Write-Host "- MQTT_PASSWORD dans .env ;"
    Write-Host "- les droits MQTT de l'utilisateur."

    exit 1
}

# ---------------------------------------------------------
# Resume final
# ---------------------------------------------------------

Write-Host ""
Write-Host "========================================="
Write-Host " Sentinel-X operationnel"
Write-Host "========================================="
Write-Host ""
Write-Host "PostgreSQL       : HEALTHY"
Write-Host "Raspberry Pi     : $MqttHost"
Write-Host "MQTT TCP/$MqttPort    : OK"
Write-Host "MQTT Auth        : OK"
Write-Host "MQTT Publication : OK"
Write-Host ""