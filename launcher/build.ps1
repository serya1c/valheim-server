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
$setupTestsProject = Join-Path $launcherDirectory 'setup-tests/Setup.Tests.csproj'
Invoke-Dotnet -Arguments @('restore', $setupTestsProject, '--configfile', (Join-Path $launcherDirectory 'NuGet.Config'))
Invoke-Dotnet -Arguments @('run', '--project', $setupTestsProject, '-c', 'Release', '--no-restore')
foreach ($runtime in @('win-x64', 'linux-x64')) {
    Invoke-Dotnet -Arguments @('publish', $projectPath, '-c', 'Release', '-r', $runtime, '--self-contained', 'true', '--no-restore',
        '-o', (Join-Path $buildDirectory "publish/$runtime"))
}
& $Python (Join-Path $launcherDirectory 'package.py') --prepare-setup
if ($LASTEXITCODE -ne 0) { throw "Setup payload preparation failed with exit code $LASTEXITCODE" }
$setupProject = Join-Path $launcherDirectory 'setup/HearthLauncherSetup.csproj'
Invoke-Dotnet -Arguments @('restore', $setupProject, '--configfile', (Join-Path $launcherDirectory 'NuGet.Config'), '--locked-mode')
Invoke-Dotnet -Arguments @('publish', $setupProject, '-c', 'Release', '--no-restore', '-o', (Join-Path $buildDirectory 'publish/setup-win-x64'))
if ($env:OS -eq 'Windows_NT') {
    $setupExecutable = Join-Path $buildDirectory 'publish/setup-win-x64/Hearth-Launcher-Setup.exe'
    $setupSmoke = Start-Process -FilePath $setupExecutable -ArgumentList @('--smoke-test') -WindowStyle Hidden -Wait -PassThru
    if ($setupSmoke.ExitCode -ne 0) { throw "Setup UI smoke check failed" }
    $shortcutSmokeDirectory = Join-Path $buildDirectory 'shortcut-smoke'
    $shortcutSmoke = Start-Process -FilePath $setupExecutable -ArgumentList @('--shortcut-smoke', ('"' + $shortcutSmokeDirectory + '"')) -WindowStyle Hidden -Wait -PassThru
    if ($shortcutSmoke.ExitCode -ne 0) { throw "Windows shortcut smoke check failed" }
}
& $Python (Join-Path $launcherDirectory 'package.py')
if ($LASTEXITCODE -ne 0) { throw "Packaging failed with exit code $LASTEXITCODE" }
Write-Host "Launcher assets: $buildDirectory/assets"
