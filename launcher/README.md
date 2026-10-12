# Hearth Launcher 1.1.0

Native Windows x64 and Linux x64 desktop launcher for Steam Valheim and Hearth servers. The interface switches immediately between Russian and English. Server profiles contain the HTTPS Hearth website, Steam game folder, and an optional game address override.

Opening the launcher reads local profiles, detects Steam folders, and automatically refreshes the server's information. Selecting a game directory also checks its client collection. These checks inspect metadata and files; mod installation happens when you press **Play**. Select the game in **Found in Steam**; **Detect** repeats the search, and **Browse…** adds a directory manually. Save the profile to keep the selected directory for the next launch.

Press **Play** to automatically check and, if needed, synchronize the selected server's mods before asking Steam to launch Valheim. Changed files are backed up; verified archives are cached, and an unchanged collection is left in place. The launcher does not update the game; Steam does. Reliable automatic comparison of the local game version is not provided in this version.

The connection checkbox requests Steam's `+connect` launch argument; character selection and a server password can still require interaction in Valheim. **Copy game address** provides the profile override or the game address published by the landing page, for manual Join by IP. Restore returns files from the latest launcher installation backup, not world or character saves. Unmanaged mods are retained and may affect compatibility. Profiles using the same game directory share mod files and configurations.

The launcher blocks conflicting actions and window closing during an operation. Cancel requests cancellation; the window remains open until the operation and any rollback finish. Abrupt termination or a power failure can still interrupt the program; an interrupted installation is detected and requires Restore.

## Running

On Windows, open **`Hearth-Launcher-Setup.exe`**. It installs for the current user under `%LOCALAPPDATA%/Programs/HearthLauncher`, adds desktop and Start menu shortcuts, and can open the launcher immediately. No administrator account is required. Reinstall with a newer setup to update; close the launcher first. Remove it through Windows Settings → Apps. Server profiles and all game/mod files remain. The launcher and setup are currently unsigned.

On Linux, run **`bash Hearth-Launcher-Install-Linux.sh`** as your normal desktop user, without `sudo`. The offline installer includes the launcher and icon, verifies its embedded archive, installs under `$XDG_DATA_HOME/HearthLauncher` (default `~/.local/share/HearthLauncher`), and adds desktop and application-menu shortcuts. If the desktop asks, choose **Allow Launching**. Re-run a newer installer to update with the launcher closed. To uninstall, run `bash ~/.local/share/HearthLauncher/uninstall.sh` (adjust the directory if using `XDG_DATA_HOME`). Profiles, Steam, Valheim and mods remain.

Portable editions remain available: run `Hearth-Launcher.exe` on Windows, or extract `Hearth-Launcher-Linux.tar.gz` and run `./Hearth-Launcher` on Linux. Both setup distributions are self-contained and include their launcher; installation does not require network access, Python, the .NET SDK or a separately installed .NET runtime. Linux still requires system desktop libraries and fonts; see the [Avalonia Linux deployment requirements](https://docs.avaloniaui.net/docs/deployment/linux) and [.NET Linux dependencies](https://learn.microsoft.com/en-us/dotnet/core/install/linux).

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

Assets appear under `launcher/.build/assets/`: `Hearth-Launcher-Setup.exe`, `Hearth-Launcher-Install-Linux.sh`, `Hearth-Launcher.exe`, `Hearth-Launcher-Windows-x64.zip`, `Hearth-Launcher-Linux.tar.gz`, their SHA-256 sidecars, `Hearth-Launcher.version`, and `SHA256SUMS.txt`. The Linux archive explicitly preserves executable mode 0755, including when packaged on Windows. Setup source lives under `launcher/setup`; isolated installation checks under `launcher/setup-tests` never change your actual desktop or registry. The standard-library-only `launcher/Assets/generate_icon.py` reproduces the committed SVG, PNG and six-size ICO. Publish uses a compressed single executable and extracts bundled native libraries to .NET's temporary cache at run time; that cache needs to be writable. Code signing and distribution are separate release steps.

## Offline GUI checks

After building, these commands construct the real Avalonia window using a fake report and the Skia headless renderer. They do not access a server or start Steam:

```text
dotnet launcher/bin/Release/net10.0/HearthLauncher.dll --smoke-test
dotnet launcher/bin/Release/net10.0/HearthLauncher.dll --render-preview launcher/.build/preview-ru.png ru
dotnet launcher/bin/Release/net10.0/HearthLauncher.dll --render-preview launcher/.build/preview-en.png en
```

Smoke checks cover reversible RU/EN text, matching format placeholders, literal path preservation, unsaved profile drafts, connection address selection, busy controls, and absence of service calls during window construction. PNG previews show demonstration data, not a production server. They do not prove Steam connectivity, actual `+connect` behavior, or a native Linux desktop launch. Core/platform tests are separate under `launcher/tests`.
