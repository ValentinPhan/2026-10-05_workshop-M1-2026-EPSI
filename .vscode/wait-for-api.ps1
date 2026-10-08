# Attend que l'API réponde sur le port donné avant de laisser le front démarrer.
# Au bout du délai, on rend la main quand même (le front se reconnectera tout seul).
param([int]$Port = 4000, [int]$TimeoutSec = 120)

$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', $Port)
        Write-Host "API disponible sur :$Port"
        exit 0
    } catch {
        Start-Sleep -Milliseconds 500
    } finally {
        $client.Dispose()
    }
}
Write-Host "API toujours injoignable apres ${TimeoutSec}s : le front demarre quand meme."
exit 0
