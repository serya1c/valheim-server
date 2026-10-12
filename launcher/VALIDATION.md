# Hearth Launcher — validation

## Version 1.1.0: automatic checks and installation

- Read-only startup, profile/website and Steam/manual-folder inspection. Server metadata remains visible if the client folder or inventory has an error; no folder, setup, update/repair, ready, vanilla and failed states are distinct. Inspections read actual managed-file SHA-256 values, preserve user configurations, do not download archives or change game files, and support cancellation.
- GUI checks verify automatic startup/folder selection, editable-site debounce, late replies after selection changes, failure clearing readiness, language switching and inspection cancellation before file operations. Real RU/EN previews use labelled demonstration data.
- Windows platform/service fixtures pass: 90 platform + 60 service checks. The new inspection scenarios use fake HTTP responses and disposable game directories; they do not run Steam, Proton or Valheim.
- Locked Release builds and self-contained Windows/Linux 1.1.0 artifacts pass. The launcher executable, Windows setup, Linux embedded installer and portable archive match their SHA-256 sidecars. The EXE and application resources contain the new Hearth icon; the portable Linux archive preserves executable mode 0755.
- Windows setup: 15 disposable-directory installation checks and 6 real WScript.Shell shortcut checks pass. Desktop/menu target and icon, foreign-shortcut rejection and rollback are exercised in test directories with application registration disabled. Both real installer language previews were rendered and visually inspected. No actual desktop, installed-app registration, Steam or game files are changed.
- Linux setup: real offline installation as UID 1000 in an Ubuntu runtime-dependencies container with network disabled. Desktop/menu entries and icon, standalone GUI smoke, reinstall, uninstall with profiles preserved, corrupt-payload cleanup and immediate retry, and foreign-shortcut rejection pass. The container has no .NET executable/SDK, Steam or Valheim.
- Linux service fixtures: 90 platform + 63 service checks pass offline, including three Linux path-alias cases. Python metadata/downloads, the actual four HTTP payloads/checksums, approved public API fields, localization, landing routes and backwards-compatible downloads pass. Six documentation files, 101 local links/anchors and 22 screenshot references are verified; launcher screenshots are updated to 1.1.0.
- The temporary landing was checked in Russian and English for setup/portable links, Proton instructions, reversible language switching and website-copy feedback. It never starts a game server or changes production settings.

Version 1.0.0 acceptance below applies to the previously published launcher. New installer/desktop integration and the 1.1.0 changes still need a maintainer check on actual desktop sessions.

## Previous version 1.0.0

Included in Hearth panel 1.8.0. The launcher has its own version, 1.0.0.

## Completed

- .NET 10.0.401 / Avalonia 12.1.4 locked restore, Release build and self-contained Windows x64 / Linux x64 publish: zero build warnings or errors.
- Windows: 90 platform checks and 46 synchronization/profile/transaction checks, using disposable fixtures and fake HTTP handlers. No Steam or Valheim execution. Play from a clean installation verifies automatic synchronization before the launch callback; repeated Play verifies without downloading again.
- Linux: the same 90 platform checks plus 49 synchronization/profile/transaction checks, as UID 1000 with external networking disabled. Three additional Linux checks cover case-alias folders/files and preserving existing files after rejection.
- Ready Windows EXE: headless RU/EN rendering and GUI assertions for language switching, literal paths, drafts, addresses, the single Steam/manual game selector, saving its selected folder, preserving it after a scan, and busy controls. Opening the UI performs no service calls. Mod checks and installation run through Play; the separate buttons and upper file-check summary are removed.
- Ready Linux TAR.GZ: headless GUI smoke and actual Skia rendering as UID 1000, with networking disabled, in an Ubuntu 24.04 runtime-dependencies container containing desktop libraries/fonts but no .NET executable, SDK, Steam or game. This verifies self-contained startup/rendering; it does not validate an interactive X11/Wayland session.
- ZIP/TAR contents, executable signatures, Linux executable mode 0755, SHA-256 sidecars and copied panel downloads verified against the final packaged files.
- Six Python launcher tests: missing/invalid artifacts and real unauthenticated HTTP metadata/downloads, checksum matching, management authentication, escaped server titles and inserted landing markup. Two localization tests include the new fragment; existing Node language tests and JavaScript syntax check pass.
- Browser check of the temporary landing: both downloads, checksum links, published website, copy feedback and RU/EN reversal. No production settings changed.
- README/player/admin documentation links and 22 real interface screenshots checked. The launcher screenshots use a labelled demo with fake game data.

Coverage includes intact-collection no-ops, verified archive caching, corrupt-cache repair, exact V+ packages plus overlay, generic BepInEx collections, vanilla launch plans, server changes before installation/launch, bad hashes and ZIP paths, unmanaged collisions, known V+ conflicts added after synchronization, interrupted transactions, rollback with complete inventory, private configurations and foreign plugins.

## Maintainer acceptance

On 2026-10-12, the project maintainer confirmed that the current launcher had been tested and approved merging and publishing the release. This is maintainer-reported acceptance; the automated checks above did not start Steam, Proton or Valheim.

## Manual regression scenarios

1. Windows: detect a real Steam library, install a server collection, launch Steam/Valheim and verify the connection handoff after character selection.
2. Linux desktop / Steam Proton, including Flatpak: configure `WINEDLLOVERRIDES`, repeat synchronization and launch, confirm BepInEx loads and the server accepts the client.
3. Switch between plus, modded and vanilla profiles; verify Doorstop 3/4 vanilla flags in the actual game and restore the prior collection.

The launcher never launches plugin DLLs during automated validation. Game updates remain Steam's responsibility; the local game version is reported as unknown. Profiles sharing one game folder share configurations. Downloads cache whole verified archives, not individual mod deltas. The first Windows build is unsigned.
