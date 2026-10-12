$ErrorActionPreference = 'Stop'
$installPath = [IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs/HearthLauncher'))
function Assert-NoLinks([string]$Path) {
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked path: $cursor" }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}
Assert-NoLinks $installPath
$marker = Join-Path $installPath '.hearth-launcher-install.json'
Assert-NoLinks $marker
if ((Get-Item -LiteralPath $marker -Force).Length -gt 4096 -or (Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json).product -ne 'HearthLauncher') { throw 'Invalid installation marker.' }
$owned = @('Hearth-Launcher.exe', 'hearth.ico', 'README.md', 'uninstall.ps1', '.hearth-launcher-install.json')
$entries = @(Get-ChildItem -LiteralPath $installPath -Force)
foreach ($item in $entries) {
    Assert-NoLinks $item.FullName
    if ($item.PSIsContainer -or $item.Name -cnotin $owned) { throw "Unrecognized file: $($item.FullName). Move it first." }
}
Add-Type -AssemblyName System.Windows.Forms
$answer = [Windows.Forms.MessageBox]::Show('Remove Hearth Launcher? Server profiles, game files and mods will be preserved. / Удалить лаунчер? Профили, игра и моды сохранятся.', 'Hearth Launcher', 'YesNo', 'Question')
if ($answer -ne 'Yes') { exit }
$launcherPath = Join-Path $installPath 'Hearth-Launcher.exe'
$handle = [IO.File]::Open($launcherPath, 'Open', 'ReadWrite', 'None')
$handle.Dispose()
$shell = New-Object -ComObject WScript.Shell
foreach ($location in @([Environment]::GetFolderPath('DesktopDirectory'), [Environment]::GetFolderPath('Programs'))) {
    $link = Join-Path $location 'Hearth Launcher.lnk'
    Assert-NoLinks $link
    if (Test-Path -LiteralPath $link) {
        if ($shell.CreateShortcut($link).TargetPath -eq $launcherPath) { Remove-Item -LiteralPath $link }
    }
}
foreach ($item in $entries) { Remove-Item -LiteralPath $item.FullName }
Remove-Item -LiteralPath $installPath
Remove-Item -LiteralPath 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Uninstall/HearthLauncher' -ErrorAction SilentlyContinue
[Windows.Forms.MessageBox]::Show('Hearth Launcher removed. Profiles preserved. / Лаунчер удалён. Профили сохранены.', 'Hearth Launcher') | Out-Null
