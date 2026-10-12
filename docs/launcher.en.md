# Hearth Launcher — prepare and enter your world

[Русский](launcher.ru.md) · [Back to Hearth](../README.en.md)

The launcher saves your servers, checks installed mods, and starts Valheim through Steam. It uses the collection published by the selected Hearth server. When an administrator changes the collection, players press **Play** again.

## First launch

1. Install Valheim in Steam. On Linux, use the **Windows game through Proton**.
2. Download the launcher from your server's landing page. On Windows, open `Hearth-Launcher.exe`. On Linux, extract `Hearth-Launcher-Linux.tar.gz` and run `Hearth-Launcher` from the extracted directory.
3. Select Valheim in **Found in Steam**. **Detect** repeats the search; **Browse…** lets you add a directory manually. The directory must contain `valheim.exe` and `valheim_Data`.
4. Add the **HTTPS address of your Hearth website**, such as `https://loki.ach-play.ru`, and save the profile. Use the website root without an extra path, on the standard HTTPS port 443.
5. Close Valheim and press **Play**. The launcher automatically checks and, if needed, installs or updates the mods, then starts the game through Steam.

Published builds include .NET and the launcher interface; no separate SDK, Python, or .NET installation is required. Windows x64 and desktop Linux x64 with Steam or Steam Flatpak are supported. Linux needs its normal desktop graphics libraries; Wayland uses XWayland.

## Linux and Proton

In Steam, open **Valheim → Properties → Compatibility** and enable Proton once. For a modded server, add the following under **General → Launch Options**:

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

Keep existing options. Add `winhttp=n,b` to an existing `WINEDLLOVERRIDES` value with a semicolon, and keep `%command%` exactly once. For example:

```text
WINEDLLOVERRIDES="winhttp=n,b" gamemoderun %command%
```

Steam Flatpak needs the same setting. The launcher explains and copies the option; you save Steam's settings. A supported Doorstop loader is disabled by a launch argument when playing vanilla.

## What Play does

The launcher reads the selected server's mode, versions, and client collection. V+ uses that server's installed Grantapher version; BepInEx uses the client package published by the server. Server-only mods are excluded from that client collection.

When the collection and file hashes match, downloading and installing are skipped. A changed collection downloads its ZIP, and verified archives are cached. Missing or damaged files are repaired from a verified archive; only changed files are replaced. This caches complete archives rather than downloading individual mods from catalogs.

Files are backed up before replacement. The launcher checks the server again before applying changes: if the administrator changes the collection during the download, installation is cancelled. An installation error triggers a rollback attempt. Existing files in `BepInEx/config` are preserved.

Steam then starts Valheim. With **Connect to the selected server** enabled, the published `host:port` is passed to the game; the profile can override it. Character selection and passwords remain in the game. The launcher does not require the game password, and the API does not publish it. If the game does not proceed to the server, copy its address from the launcher and use **Join Game → Join IP**.

Steam updates the game itself. **Server game** shows the required version. **Your game** currently shows **Unknown** because a reliable automatic check of the local Valheim version is not provided. If the game reports a version mismatch, check Steam updates and ask the administrator which game version the server uses.

## Multiple servers and vanilla

A profile saves a name, website, the game directory selected in the list, and an optional connection address. After changing the selection, press **Save profile** to keep it for the next launch. Domains are not tied to Loki: any Hearth server with a public HTTPS website can be added.

Profiles using the same game directory switch the managed mod collection and share configurations. A profile is not a separate copy of Valheim. Foreign DLLs outside the launcher's inventory are preserved and included in compatibility notes.

Vanilla servers require no mod download or installation. Supported Doorstop 3/4 is disabled for that launch, leaving mod files intact. An unknown loader is not disabled by guesswork. Other native modifications need separate checking.

## Restore and settings

**Restore backup** cancels the latest launcher installation in that directory and restores its previous collection inventory. Files changed after installation are not overwritten automatically; an error identifies the file to inspect. Backups from the earlier Loki installers are stored separately.

Profiles, language, and cached archives live in the local HearthLauncher directory. The installed inventory and game-file backups live in the game's `.hearth-launcher` directory. **RU / EN** switches immediately, preserves input, and saves the selection. Website and community links come from the selected server.

Real Steam/Proton launch and connection require in-game verification. Automated checks use temporary files, demonstration collections, and launch plans without executing game DLLs.
