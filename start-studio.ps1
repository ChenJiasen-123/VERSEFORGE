param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$studioRoot = $PSScriptRoot
$studioUrl = 'http://127.0.0.1:8765'
$health = $null
try { $health = Invoke-RestMethod -Uri "$studioUrl/health" -TimeoutSec 2 } catch { }
if ($health) {
    if ($health.application -ne 'VERSEFORGE') { throw 'Port 8765 is occupied by another application.' }
    if (-not $NoBrowser) { Start-Process $studioUrl }
    Write-Output $studioUrl
    exit 0
}
$python = (Get-Command python -ErrorAction Stop).Source
$logDirectory = Join-Path $studioRoot 'var'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$server = Join-Path $studioRoot 'web_server.py'
$process = Start-Process -FilePath $python -ArgumentList @('-u', ('"' + $server + '"')) -WorkingDirectory $studioRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'studio.log') -RedirectStandardError (Join-Path $logDirectory 'studio-error.log') -PassThru
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 250
    if ($process.HasExited) { throw 'Studio exited. Check var/studio-error.log.' }
    try {
        $health = Invoke-RestMethod -Uri "$studioUrl/health" -TimeoutSec 1
        if ($health.application -eq 'VERSEFORGE') {
            if (-not $NoBrowser) { Start-Process $studioUrl }
            Write-Output $studioUrl
            exit 0
        }
    } catch { }
}
throw 'Studio has not started. Check var/studio-error.log.'
