$ErrorActionPreference = 'Stop'
$project = Join-Path $PSScriptRoot 'LokiInstaller.csproj'
$publish = Join-Path $PSScriptRoot 'bin/publish'
$downloads = Join-Path $PSScriptRoot '../app/downloads'
dotnet publish $project -c Release -o $publish --nologo
if ($LASTEXITCODE -ne 0) { throw 'Сборка не завершена' }
New-Item -ItemType Directory -Force -Path $downloads | Out-Null
$exe = Join-Path $downloads 'Loki-Mod-Installer.exe'
Copy-Item -LiteralPath (Join-Path $publish 'Loki-Mod-Installer.exe') -Destination $exe
$digest = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
Set-Content -LiteralPath "$exe.sha256" -Encoding ascii -Value "$digest  Loki-Mod-Installer.exe"
Write-Host "Готово: $exe"
