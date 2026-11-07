# Keep native Docker switches (including -d/-p) out of PowerShell parameter binding.
$DockerArgs = @($args)
$ErrorActionPreference = 'Stop'
$radarRoot = Split-Path $PSScriptRoot -Parent
if (-not $DockerArgs) { $DockerArgs = @('compose', 'ps') }
$nativeDocker = Get-Command docker -ErrorAction SilentlyContinue
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
