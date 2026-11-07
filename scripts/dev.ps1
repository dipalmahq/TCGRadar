param([switch]$Worker, [switch]$Build, [switch]$EnableNotifications)
$ErrorActionPreference = 'Stop'
$radarRoot = Split-Path $PSScriptRoot -Parent
Push-Location $radarRoot
$savedRadarEnvironment = @{}
$localSettings = @{
    RADAR_DATABASE_URL = 'sqlite:///./data/radar.db'
    RADAR_ENVIRONMENT = 'development'
    RADAR_API_KEY = ''
    RADAR_NOTIFICATIONS_ENABLED = $(if ($EnableNotifications) { 'true' } else { 'false' })
}
try {
    foreach ($name in $localSettings.Keys) {
        $savedRadarEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $localSettings[$name], 'Process')
    }
    $pythonPath = Join-Path $radarRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw 'Bitte zuerst eine Python-3.12-Umgebung anlegen und das Backend installieren (siehe README).'
    }
    New-Item -ItemType Directory -Path (Join-Path $radarRoot 'data') -Force | Out-Null
    if ($Build) {
        Push-Location (Join-Path $radarRoot 'frontend')
        try {
            & node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
            if ($LASTEXITCODE -ne 0) { throw 'TypeScript-Prüfung fehlgeschlagen.' }
            & node node_modules/vite/bin/vite.js build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend-Build fehlgeschlagen.' }
        } finally { Pop-Location }
    }
    & $pythonPath -m app.manage init
    if ($LASTEXITCODE -ne 0) { throw 'Datenbank-Initialisierung fehlgeschlagen.' }
    if ($Worker) {
        & $pythonPath -m app.worker
    } else {
        Write-Host 'JoyBoyz Radar: http://127.0.0.1:8000 (zweites Terminal: scripts/dev.ps1 -Worker)'
        & $pythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    }
} finally {
    foreach ($name in $savedRadarEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $savedRadarEnvironment[$name], 'Process')
    }
    Pop-Location
}
