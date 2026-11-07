param([switch]$Build)
$ErrorActionPreference = 'Stop'
$dockerHelper = Join-Path $PSScriptRoot 'docker.ps1'
if ($Build) {
    & $dockerHelper compose up -d --build
} else {
    & $dockerHelper compose up -d --no-build
}
if ($LASTEXITCODE -ne 0) { throw 'Container-Start fehlgeschlagen.' }
Write-Host 'JoyBoyz TCG Radar: http://127.0.0.1:8000'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'Ubuntu/WSL wird aktiv gehalten. Dieses Terminal während der lokalen Nutzung offen lassen.'
    Write-Host 'Strg+C beendet den Vordergrundprozess; Container stoppen: scripts/docker.ps1 compose down'
    & wsl -d Ubuntu --exec sleep infinity
}
