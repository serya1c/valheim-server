# Hearth Launcher 1.0.0 — validation

Implementation branch: `feat/hearth-launcher`, based on Hearth panel 1.7.0.

## Completed

- .NET 10.0.401 / Avalonia 12.1.4 locked restore, Release build and self-contained Windows x64 / Linux x64 publish: zero build warnings or errors.
- Windows: 90 platform checks and 44 synchronization/profile/transaction checks, using disposable fixtures and fake HTTP handlers. No Steam or Valheim execution.
- Linux: the same 90 platform checks plus 47 synchronization/profile/transaction checks, as UID 1000 with external networking disabled. Three additional Linux checks cover case-alias folders/files and preserving existing files after rejection.
- Ready Windows EXE: headless RU/EN rendering and GUI assertions for language switching, literal paths, drafts, addresses and busy controls. Opening the UI performs no service calls.
- Ready Linux TAR.GZ: headless GUI smoke and actual Skia rendering as UID 1000, with networking disabled, in an Ubuntu 24.04 runtime-dependencies container containing desktop libraries/fonts but no .NET executable, SDK, Steam or game. This verifies self-contained startup/rendering; it does not validate an interactive X11/Wayland session.
- ZIP/TAR contents, executable signatures, Linux executable mode 0755, SHA-256 sidecars and copied panel downloads verified against the final packaged files.
- Six Python launcher tests: missing/invalid artifacts and real unauthenticated HTTP metadata/downloads, checksum matching, management authentication, escaped server titles and inserted landing markup. Two localization tests include the new fragment; existing Node language tests and JavaScript syntax check pass.
- Browser check of the temporary landing: both downloads, checksum links, published website, copy feedback and RU/EN reversal. No production settings changed.
- README/player/admin documentation links and 22 real interface screenshots checked. The launcher screenshots use a labelled demo with fake game data.

Coverage includes intact-collection no-ops, verified archive caching, corrupt-cache repair, exact V+ packages plus overlay, generic BepInEx collections, vanilla launch plans, server changes before installation/launch, bad hashes and ZIP paths, unmanaged collisions, known V+ conflicts added after synchronization, interrupted transactions, rollback with complete inventory, private configurations and foreign plugins.

## Remaining in-game validation

1. Windows: detect a real Steam library, install a server collection, launch Steam/Valheim and verify the connection handoff after character selection.
2. Linux desktop / Steam Proton, including Flatpak: configure `WINEDLLOVERRIDES`, repeat synchronization and launch, confirm BepInEx loads and the server accepts the client.
3. Switch between plus, modded and vanilla profiles; verify Doorstop 3/4 vanilla flags in the actual game and restore the prior collection.

These steps have not been claimed as passed. The launcher never launches plugin DLLs during validation. Game updates remain Steam's responsibility; the local game version is reported as unknown. Profiles sharing one game folder share configurations. Downloads cache whole verified archives, not individual mod deltas. The first Windows build is unsigned.
