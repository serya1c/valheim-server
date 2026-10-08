param(
    [string]$ValheimDir = 'C:\Program Files (x86)\Steam\steamapps\common\Valheim',
    [string]$ManagedDir = '',
    [string]$BepInExCore = ''
)
$ErrorActionPreference = 'Stop'
$taskArgs = @('build', (Join-Path $PSScriptRoot 'ValheimAdminRu.csproj'), '-c', 'Release', '--nologo', "-p:ValheimDir=$ValheimDir")
if ($ManagedDir) { $taskArgs += "-p:ManagedDir=$ManagedDir" }
if ($BepInExCore) { $taskArgs += "-p:BepInExCore=$BepInExCore" }
& dotnet @taskArgs
if ($LASTEXITCODE -ne 0) { throw 'Сборка не удалась.' }
$taskRelease = Join-Path $PSScriptRoot 'BepInEx\plugins\ValheimAdminRu'
New-Item -ItemType Directory -Path $taskRelease -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'bin\Release\net48\ValheimAdminRu.dll') -Destination $taskRelease -Force
Write-Host "Готово: $taskRelease\ValheimAdminRu.dll"
