param([string]$Dotnet = 'dotnet', [string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$launcherDirectory = $PSScriptRoot
$projectPath = Join-Path $launcherDirectory 'HearthLauncher.csproj'
$buildDirectory = Join-Path $launcherDirectory '.build'
$env:DOTNET_CLI_HOME = Join-Path $buildDirectory 'dotnet-home'
$env:NUGET_PACKAGES = Join-Path $launcherDirectory '.packages'
$env:DOTNET_CLI_TELEMETRY_OPTOUT = '1'
$env:DOTNET_GENERATE_ASPNET_CERTIFICATE = 'false'

function Invoke-Dotnet([string[]]$Arguments) {
    & $Dotnet @Arguments
    if ($LASTEXITCODE -ne 0) { throw "dotnet failed with exit code $LASTEXITCODE" }
}

Invoke-Dotnet -Arguments @('restore', $projectPath, '--configfile', (Join-Path $launcherDirectory 'NuGet.Config'), '--locked-mode', '-p:SelfContained=true')
Invoke-Dotnet -Arguments @('build', $projectPath, '-c', 'Release', '--no-restore')
$dllPath = Join-Path $launcherDirectory 'bin/Release/net10.0/HearthLauncher.dll'
Invoke-Dotnet -Arguments @($dllPath, '--smoke-test')
foreach ($runtime in @('win-x64', 'linux-x64')) {
    Invoke-Dotnet -Arguments @('publish', $projectPath, '-c', 'Release', '-r', $runtime, '--self-contained', 'true', '--no-restore',
        '-o', (Join-Path $buildDirectory "publish/$runtime"))
}
& $Python (Join-Path $launcherDirectory 'package.py')
if ($LASTEXITCODE -ne 0) { throw "Packaging failed with exit code $LASTEXITCODE" }
Write-Host "Launcher assets: $buildDirectory/assets"
