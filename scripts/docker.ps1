# Keep native Docker switches (including -d/-p) out of PowerShell parameter binding.
$DockerArgs = @($args)
$ErrorActionPreference = 'Stop'
$radarRoot = Split-Path $PSScriptRoot -Parent
if (-not $DockerArgs) { $DockerArgs = @('compose', 'ps') }
$nativeDocker = Get-Command docker -ErrorAction SilentlyContinue
# Continue an existing Ubuntu project after Docker Desktop is installed later.
# Keep the user's global Docker context unchanged and touch only this project.
if ($nativeDocker -and (Get-Command wsl -ErrorAction SilentlyContinue)) {
    $nativeProject = @(& $nativeDocker.Source ps -aq --filter 'label=com.docker.compose.project=joyboyz-tcg-radar' 2>$null)
    if (-not ($nativeProject | Where-Object { $_ -match '^[a-f0-9]{12,64}$' })) {
        $ubuntuProject = @(& wsl -d Ubuntu -u root --exec docker ps -aq --filter 'label=com.docker.compose.project=joyboyz-tcg-radar' 2>$null)
        if ($LASTEXITCODE -eq 0 -and ($ubuntuProject | Where-Object { $_ -match '^[a-f0-9]{12,64}$' })) {
            $nativeDocker = $null
        }
    }
}
$env:JOYBOYZ_DOCKER_RUNTIME_SELECTED = if ($nativeDocker) { 'native' } else { 'wsl' }
Push-Location $radarRoot
try {
    if ($nativeDocker) {
        & $nativeDocker.Source @DockerArgs
    } else {
        $wslRoot = (& wsl -d Ubuntu --exec wslpath -a -u $radarRoot).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $wslRoot.StartsWith('/')) {
            throw 'Docker ist unter Windows nicht erreichbar; Ubuntu/WSL konnte den Projektpfad nicht auflösen.'
        }
        # Use the existing WSL administrator for Docker; do not alter group membership.
        & wsl -d Ubuntu -u root --cd $wslRoot --exec docker @DockerArgs
    }
    $dockerExitCode = $LASTEXITCODE
} finally { Pop-Location }
exit $dockerExitCode
