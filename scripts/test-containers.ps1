$ErrorActionPreference = 'Stop'
$dockerHelper = Join-Path $PSScriptRoot 'docker.ps1'
$composeArgs = @('compose', '-f', 'compose.yaml', '-f', 'compose.test.yaml', '-p', 'joyboyz-radar-acceptance', '--profile', 'test')
try {
    & $dockerHelper @composeArgs run --rm tests
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL-Containertests fehlgeschlagen.' }
} finally {
    & $dockerHelper @composeArgs down --remove-orphans
}
