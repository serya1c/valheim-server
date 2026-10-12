# Hearth Launcher 1.0.0

Native Windows x64 and Linux x64 desktop launcher for Steam Valheim and Hearth servers. The interface switches immediately between Russian and English. Server profiles contain the HTTPS Hearth website, Steam game folder, and an optional game address override.

Opening the launcher reads local profiles and detects Steam folders. It does not contact a server, install mods, or launch Valheim. **Check collection** reads the selected server and checks client mod files. **Install / update mods** downloads and installs the published client collection with a backup. **Play** checks and, if needed, synchronizes mods before asking Steam to launch Valheim. The launcher does not update the game; Steam does. An unknown local game version is displayed as unknown.

The connection checkbox requests Steam's `+connect` launch argument; character selection and a server password can still require interaction in Valheim. **Copy game address** provides the profile override or the game address published by the landing page, for manual Join by IP. Restore returns files from the latest launcher installation backup, not world or character saves. Unmanaged mods are retained and may affect compatibility. Profiles using the same game directory share mod files and configurations.

The launcher blocks conflicting actions and window closing during an operation. Cancel requests cancellation; the window remains open until the operation and any rollback finish. Abrupt termination or a power failure can still interrupt the program; an interrupted installation is detected and requires Restore.

## Running

On Windows, run `Hearth-Launcher.exe` as your normal user. This first version is unsigned. On Linux, extract `Hearth-Launcher-Linux.tar.gz` and run `./Hearth-Launcher` as your normal desktop user, without `sudo`. The executable is self-contained: users do not need the .NET SDK or a separately installed .NET runtime. Linux still requires system desktop libraries and fonts; see the [Avalonia Linux deployment requirements](https://docs.avaloniaui.net/docs/deployment/linux) and [.NET Linux dependencies](https://learn.microsoft.com/en-us/dotnet/core/install/linux).

Install Steam and its **Windows Valheim client**. On Linux, select Proton under Valheim Properties → Compatibility. For modded servers, set Steam Launch Options once:

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

Preserve your existing launch options and keep exactly one `%command%`. The launcher does not change Steam configuration automatically. A vanilla launch disables a recognized Doorstop loader for that launch without deleting mods; an unknown loader is rejected. Steam handles authentication and game updates. Multiple Steam copies of Valheim need resolving in Steam because launching by AppID cannot choose a different folder.

Profiles are stored under `%LOCALAPPDATA%/HearthLauncher` on Windows, or `$XDG_STATE_HOME/HearthLauncher` on Linux (default `~/.local/state/HearthLauncher`). A valid server website uses HTTPS on port 443 without a path or query. The default Loki profile is only a preset; additional Hearth servers can be saved.

## Building from source

Developers need the .NET 10 SDK and Python 3.9+ for packaging. The initial build used SDK 10.0.401 and the official NuGet registry. Avalonia, Desktop, Fluent, and Headless are pinned to **12.1.4**; `packages.lock.json` is committed. Build scripts use a local NuGet cache and CLI home, perform a locked restore, compile, run the headless GUI smoke check, and cross-publish both self-contained x64 targets. Run from any directory:

```powershell
powershell -ExecutionPolicy Bypass -File launcher/build.ps1
```

```bash
bash launcher/build.sh
```

PowerShell parameters `-Dotnet` and `-Python`, or Bash environment variables `DOTNET` and `PYTHON`, can select tool executables. Restore needs access to `https://api.nuget.org/v3/index.json`. Outputs are confined to `launcher/bin`, `launcher/obj`, `launcher/.packages`, and `launcher/.build`; no Steam files are modified by building.

Assets appear under `launcher/.build/assets/`: `Hearth-Launcher.exe`, `Hearth-Launcher-Windows-x64.zip`, `Hearth-Launcher-Linux.tar.gz`, and `SHA256SUMS.txt`. The Linux archive explicitly preserves executable mode 0755, including when packaged on Windows. Publish uses a compressed single executable and extracts bundled native libraries to .NET's temporary cache at run time; that cache needs to be writable. Code signing and distribution are separate release steps.

## Offline GUI checks

After building, these commands construct the real Avalonia window using a fake report and the Skia headless renderer. They do not access a server or start Steam:

```text
dotnet launcher/bin/Release/net10.0/HearthLauncher.dll --smoke-test
dotnet launcher/bin/Release/net10.0/HearthLauncher.dll --render-preview launcher/.build/preview-ru.png ru
dotnet launcher/bin/Release/net10.0/HearthLauncher.dll --render-preview launcher/.build/preview-en.png en
```

Smoke checks cover reversible RU/EN text, matching format placeholders, literal path preservation, unsaved profile drafts, connection address selection, busy controls, and absence of service calls during window construction. PNG previews show demonstration data, not a production server. They do not prove Steam connectivity, actual `+connect` behavior, or a native Linux desktop launch. Core/platform tests are separate under `launcher/tests`.
