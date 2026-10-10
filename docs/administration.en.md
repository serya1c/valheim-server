# Hearth administration guide

[Project overview and quick start](../README.en.md) · [Русское руководство](administration.ru.md)

Hearth runs a vanilla Valheim server, Grantapher's Valheim Plus, or a custom BepInEx mod collection. The browser interface covers setup, configuration, backups, world transfers, updates, moderation, and maintenance. Players get a public website with connection instructions and client installers.

Use Docker Compose on Linux x86-64, or Docker Desktop with Linux containers. A practical starting allocation is 4 CPU cores, 8 GB RAM, and 30 GB of SSD space. Large worlds, backup archives, and the separate update test process require more memory and disk space.

- [First launch and public access](#first-launch-and-public-access)
- [Settings](#settings)
- [Server modes and additional mods](#server-modes-and-additional-mods)
- [Client installers](#client-installers)
- [Worlds and backups](#worlds-and-backups)
- [Players and statistics](#players-and-statistics)
- [Server health](#server-health)
- [Game updates and rollback](#game-updates-and-rollback)
- [Maintenance and Discord](#maintenance-and-discord)
- [Panel updates and migration](#panel-updates-and-migration)
- [Second instance](#second-instance)
- [Interface language](#interface-language)
- [Troubleshooting](#troubleshooting)
- [Developer reference](#developer-reference)

## First launch and public access

Run this in the project directory:

```bash
docker compose up -d --build
```

Open **http://localhost:8080**. There are no environment files to copy or fill in. The game is not downloaded or started until you complete the setup wizard.

The wizard has four steps:

1. **Access:** set an administrator password of 16–256 characters, the server name, and a separate game password of 5–128 characters.
2. **World:** choose Valheim Plus, BepInEx, or vanilla; select the save name, rules preset, autosave settings, and public listing.
3. **Website:** enter the title, website URL, world description, connection address, and community link. You can keep the site local and add public addresses later.
4. **Launch:** configure the backup interval and number of scheduled archives to retain. Select **Create server**, then sign in with your administrator password.

Settings live in the Docker data volume and survive container restarts and recreation. The administrator password is stored as a scrypt hash with a unique salt. Initial setup cannot be reopened after completion. If Steam or GitHub is temporarily unavailable, retry installation in **Updates**; there is no need to repeat the wizard. The initial download usually takes several minutes. Follow progress in the overview and journal.

### Remote access and HTTPS

On a remote host, open **http://SERVER_IP:8080** or a domain routed through your reverse proxy. The wizard works remotely and through a proxy; no SSH tunnel is required. The default Compose file publishes web port 8080 on all host interfaces. Allow it through the host firewall if using direct access.

Open or forward UDP **2456–2457** on the game host. Players connect to `SERVER_IP:2456`.

After setup, the public website is at `/` and the panel at `/admin`. To publish the website, configure an HTTPS reverse proxy to `127.0.0.1:8080`. It must also forward `/api/` and `/downloads/`. Enter the external website URL under **Settings → Website**. Once HTTPS and the proxy work, you can enable HTTPS-only sign-in under **Settings → Panel**. The wizard does not create DNS records, certificates, firewall rules, or port forwarding.

For access only through a proxy on the same host, change the Compose web port mapping to `127.0.0.1:8080:8080`. If port 8080 is already in use, change the published host port and use that port in your browser.

### Website, server listing, and search engines

The configured website URL supplies canonical and Open Graph metadata, `robots.txt`, `sitemap.xml`, links, and installer instructions. It is not inferred from the request's `Host` header. Use an HTTP(S) domain or IPv4 address with an optional port, without a path or query. The community link is optional. World descriptions are edited separately and are not overwritten when the server mode changes.

**Add website to the server listing name** appends the URL to the public game name on the next game start. URLs longer than 70 characters are omitted to stay within the name limit. Steam listing requires reachable UDP ports and Steam connectivity; a permanent place in search results cannot be guaranteed. When public listing is disabled, the website offers direct connection instructions. Crossplay is not enabled.

The website follows the **installed** mode. Selecting a different mode for the next installation does not immediately change the instructions for the current release. Vanilla hides mod installers and explains how to join with an ordinary Steam client.

The public `/api/public` exposes the website title and descriptions, addresses, installed mode and versions, public-listing flag, game-process state, and a fresh player count when available. It also includes the current or pending maintenance task and client mod package metadata: download URL, SHA-256, size, revision, package names/versions, and package kind. Passwords, access settings, player names, journal, moderation records, and backup archives require administrator sign-in.

The admin page and API responses carry `noindex`. To request indexing of the public site, submit `/sitemap.xml` to Google Search Console or Yandex Webmaster. Search engines determine whether and when to index it and where it ranks.

## Settings

Each tab is saved separately:

| Tab | Controls |
|---|---|
| Server | Name, game password, next-install mode, listing visibility, website in listing name, autosave, and Valheim's built-in backups |
| World | Save name, separate rule profiles, difficulty, resources, raids, portals, and additional flags |
| Valheim Plus | Settings from the installed CFG, descriptions, types, declared ranges, search, and comment preservation |
| Website | Domain, title, world descriptions, connection address, and Discord, Telegram, or another community link |
| Panel | Scheduled archive interval and retention, HTTPS cookies, and administrator password changes with current-password verification |

Server, world, and V+ changes are saved after a graceful game stop and backup. Website and panel settings apply without stopping the game. Stale forms are rejected to avoid overwriting another administrator's changes. Changing the administrator password invalidates existing sessions; sign in again.

World presets apply only while rule management is enabled. Turning management off does not reset rules already stored in the world. To reset them, select **Normal**, remove overrides and flags, and apply. The panel does not edit an existing world's seed, map, or boss progress. A new save name creates a different world; it does not rename the previous one.

V+ ranges come from the CFG metadata. If the author has not declared a range, the panel says so; a field's technical input limit is not a safe gameplay range. Enable the relevant V+ section for its settings to take effect. Some settings are client-side and depend on the mod's synchronization. The editor is available when Valheim Plus is selected in settings and its CFG exists. In BepInEx or vanilla mode the editor is unavailable, but its configuration is retained for a later switch back.

## Server modes and additional mods

| Mode | Server installation | Player requirements |
|---|---|---|
| Vanilla (`vanilla`) | Valheim without BepInEx or V+ | Ordinary Steam Valheim client |
| Valheim Plus (`plus`) | Valheim and Grantapher's V+, with optional extra plugins | Matching V+ and any selected client mods |
| BepInEx (`modded`) | Valheim, BepInEx 5.4, and your plugins | The server's client collection, including the loader |

Under **Settings → Server**, select **BepInEx — custom mod collection**, **Valheim Plus**, or vanilla. Save, then apply the choice through a game update. BepInEx mode (`modded`) installs the latest available BepInExPack_Valheim 5.4 without V+. Vanilla does not load additional plugins; the saved collection remains in the data volume.

The **Mods** section supports:

- **Thunderstore installation:** enter a Valheim package page URL or `Author-Package`. Omitting the version selects the latest available release; `Author-Package-1.2.3` selects that exact release.
- **Hexium installation:** a `https://valheim.hexium.gg/mods/Author/Package` link always installs from Hexium. For a bare `Author-Package` and for dependencies Thunderstore is checked first; Hexium is used when the package or the pinned version is missing on Thunderstore, or when it is deprecated there and Hexium has a live copy. Packages from Hexium update from Hexium. The BepInEx loader always comes from Thunderstore. The Hexium package list is downloaded whole and cached for 10 minutes.
- **Dependency management:** exact dependencies are resolved automatically. View versions and sources, update a selected package, enable, disable, or remove it. A dependency used by an enabled package cannot be disabled or removed. Conflicting version requirements are rejected.
- **Manual ZIP upload:** upload up to 128 MiB. Uploading a ZIP with the same name replaces that local package. Local packages cannot be updated through Thunderstore; upload a new archive. Supported content is BepInEx 5.4 plugin DLLs and resources under `BepInEx/plugins`, `plugins`, or the archive root. The loader and V+ are managed through game updates. Packages requiring separate patchers, their own runtime, or native components need another installation method.
- **Scope:** choose **Server only**, **Clients only**, or **Server and clients** according to the author's instructions. Hearth does not infer a mod's requirements. Dependencies receive the scope required by the package.

Hearth downloads and validates a candidate separately, then stops the running game, creates a `pre-mods` backup of worlds, configuration, and the mod collection, and applies the change. A previously running game is restarted and checked for readiness. If startup fails, Hearth attempts to restore the previous mods, world, and configuration. Restarting the container after an interrupted change also triggers recovery. Check logs and gameplay for later failures or incompatible mechanics; restore the backup manually if needed.

Additional mods live in `/data/mods` and survive container recreation and game updates. New full backups include them. Restoring an older backup without `mods` preserves the current collection. A world export transfers the world, its rules, and V+ configuration; install extra plugins separately on the destination, or use a full backup with a suitable game release.

Enabled client packages are published on the website with exact versions. The Windows and Linux/Proton installers download this collection from the selected server and verify SHA-256. For V+, the package supplements the matching official Windows client archive; for BepInEx mode, it includes the loader and plugins. Players should rerun the installer after the collection changes. Obsolete, unchanged files previously installed under `HearthMods` are removed with a backup; user-modified files are not removed automatically.

The public ZIP excludes server configuration, mod configuration files, worlds, passwords, and player access lists. Mods create client settings when the game starts. Install packages you trust: plugins execute inside the game process.

For manual uploads through nginx, allow `client_max_body_size 128m;` and `proxy_read_timeout 300s;`. Keep a larger limit if already configured for world imports.

### Package limits and compatibility

Archive validation checks paths, links, duplicate entries, case conflicts, manifests, and declared sizes. Limits are:

| Item | Limit |
|---|---|
| One mod ZIP | 128 MiB compressed, 256 MiB extracted |
| One extracted file | 64 MiB |
| Entries per mod ZIP | 4,096 |
| Packages in a collection | 64 |
| Total stored package content | 512 MiB |
| Public client package | 128 MiB compressed, 512 MiB extracted, 5,000 entries |

Installers also limit one operation to 5,000 file changes. This includes the V+ base and removal of obsolete files from the previous collection, so a ZIP near its entry limit may still be rejected. Installation is cancelled before changing game files; reduce the collection or install the required mods another way.

Dependencies specify exact versions. Updating a package may also update its dependencies; if another enabled package requires the old version, the entire change is rejected. Only `denikson`'s BepInExPack 5.4 is supported, managed separately by the panel. A dependency on Valheim Plus must exactly match the installed V+ version. These requirements are checked again before mode changes and game updates.

Archive validation restricts where files can be installed; it does not prove a DLL is safe or compatible with gameplay. Check the author's requirements for clients, game versions, and other mods.

## Client installers

### Windows

On Windows 10/11 x64, download `Loki-Mod-Installer.exe` from the server website. Enter its HTTPS URL, check the reported versions, and select the detected Steam game directory or browse to it manually. Close Valheim before installation. The executable is self-contained and currently has no publisher signature.

### Linux with Steam Proton

Use Linux x86-64 and Python 3.9 or newer. In Steam, enable Proton for Valheim and wait for Steam to download the Windows game build. Close the game, then run:

```bash
bash Loki-Mod-Installer-Linux.sh --server https://your-server.example
```

Run as your own user, without `sudo`. Both regular Steam and Steam Flatpak installations are supported. Add this to the game's Steam launch options:

```text
WINEDLLOVERRIDES="winhttp=n,b" %command%
```

Keep existing options and include `%command%` only once. If `WINEDLLOVERRIDES` is already present, append `winhttp=n,b` to its value using `;`. The installer does not edit Steam settings.

To undo the last installation:

```bash
bash Loki-Mod-Installer-Linux.sh --restore
```

If restoration removes BepInEx, remove the added `winhttp` override from the launch options.

### Version checks and client packages

Both installers read the actual installed versions from the selected server's `/api/public`. In V+ mode they download the matching official `WindowsClient.zip` and any additional client overlay. In BepInEx mode they download the server's full loader-and-plugin package. They verify SHA-256 and archive paths, and back up replaced files.

The website must use HTTPS on port 443. API and client-package redirects cannot move to another origin. An unavailable API, vanilla mode, or a version/collection change during download cancels installation; the installers do not fall back to an unrelated latest version. Steam updates the game itself. To play vanilla after using mods, use a clean installation or a separate profile without BepInEx and mods.

## Worlds and backups

### Full game backups

By default, scheduled backups run at a six-hour interval and retain 12 archives. Change both values under **Settings → Panel**; an interval of zero disables this schedule. Scheduled backups wait for an empty server and are postponed if the player count is unknown. A manual backup interrupts play, stops and saves the world gracefully, then restarts the game if it was running.

Stopping sends SIGINT and waits up to 120 seconds. A stuck game process is not forcibly killed to manufacture a supposedly consistent backup. A failed stop or restore is reported as an error. Before restoration, the current world is backed up separately. Manual archives and archives made before updates, settings changes, or restoration are not automatically pruned.

A full game archive contains `saves/`, `config/`, `mods/`, and `manifest.json`, including the game password in configuration. It does not contain game release binaries. **The administrator password and panel settings (`panel.json`) are excluded and are not changed by a world rollback.** Maintenance and webhook settings (`operations.json`), moderation notes and reasons (`moderation.json`), and the statistics database (`panel.sqlite`) are also outside game archives.

For recovery from a host failure, back up the entire data volume to another device. A Docker volume on the same host is not an external backup. Restoring a historical archive without `mods/` leaves the current mod collection in place.

Ordinary restoration accepts an archive from the **currently active game release**. To return to a previous release after an update, use full rollback. Its release files must still exist under `/data/releases`; a game backup archive alone does not contain them.

### Export a world

Under **World and backups → Move your world to another server**, select **Prepare world export**. Hearth stops the game gracefully, packs the selected world and its rules, then restores the previous running/stopped state. It supports both the complete chunk-format directory (`.db2`, `.fwl2`, `.chunks`, `.ok`, and `.chunk` files) and the classic `.db`/`.fwl` pair.

A V+ world's ZIP must include the server mod configuration with its comments. Export excludes panel and game passwords, website settings, player history, and game/mod executables. The mod configuration is copied in full; review custom values before sharing it. Additional mod plugins are not included.

### Import a world

Install the **same mode and Valheim/V+ versions** on the destination. Select the export and choose **Upload and check**. Upload and validation do not change the world or stop the running game. The panel displays the name and versions from the archive. Validation lasts one hour and is repeated during import; upload again after a panel restart.

**Import checked world** stops the game and creates a full `pre-import` backup. It replaces the selected world's entire chunk directory or classic file pair, without mixing old and new chunks. Files of another world format with the same name are removed after backup. The rule profile and, for V+, the mod configuration are also replaced.

Other worlds, the game password, domain, selected installation mode, and web administrator access remain those of the destination. The imported world becomes selected but **does not start automatically**. Check settings and select **Start**. The V+ configuration is shared by all worlds on that server; players still need the matching client mod. Use normal backup restoration to return to `pre-import` if needed.

Only Hearth export format 1 (classic pair) and format 2 (world directory) are accepted. Format 2 requires an updated destination panel. Limits are:

| Item | Limit |
|---|---|
| Uploaded ZIP | 1 GiB |
| Extracted files | 2 GiB |
| V+ configuration | 2 MiB |
| Files in the world directory | 10,000 |

File contents are checked against the manifest and SHA-256 hashes; unsafe paths, links, duplicates, and unexpected files are rejected. Checksums detect damage, not the archive's author: import from a trusted source. Valheim itself checks the game-file format when starting. Full `.tar.gz` backups and arbitrary ZIP archives cannot be imported here.

For nginx, set `client_max_body_size 1g;` and `proxy_read_timeout 300s;` in the site configuration. Allow up to 3 GiB for upload/extraction validation, plus space for the full backup before import. Exports remain in `/data/exports` until removed; incomplete uploads are under `/data/incoming`. World archives require administrator sign-in to download.

## Players and statistics

### Statistics

The online count comes from A2S. Without a fresh reply, it is shown as unknown rather than zero. Connection history counts character names found in the game log; these are not SteamIDs. Playtime is an approximate estimate based on names visible through A2S. World days, map progress, kills, skills, and boss progress are not extracted.

### Access by SteamID

Under **Players → Player access by SteamID64**, ban or unban an account, grant or revoke game administrator rights, or request a disconnect. Enter a 17-digit SteamID64 or `Steam_<SteamID64>`. Character names are not used for access control; identical names in statistics cannot reliably identify an account.

Hearth edits Valheim's native `saves/adminlist.txt` and `saves/bannedlist.txt`, which the game reloads without restarting. See the [official dedicated server guide](https://www.valheimgame.com/support/a-guide-to-dedicated-servers/) for identifier formats. Older numeric SteamID64 entries are also recognized. Other entries, comments, and `permittedlist.txt` are preserved. You can ban or grant rights to an offline player. Game administrator rights do not grant web-panel access; players must reconnect after a rights change.

Disconnect works in vanilla, BepInEx, and V+ modes through a 30-second temporary ban, without requiring a client mod. Valheim periodically applies access lists, usually within about 15 seconds; dropping the connection can take another second. Once the panel removes the temporary entry, Valheim must reload the list before the player can rejoin. The button is unavailable while the game is stopped. An API success confirms a list change, not a confirmed disconnect of a particular client.

A permanently banned SteamID cannot receive a disconnect ban and will not be automatically unbanned. To make a temporary restriction permanent, apply **Ban** to the same ID with no duration. Expiry is stored in a managed `//` comment in the native list and survives panel restarts and comment reordering by the game. Temporary disconnect entries are cleaned before a game stop/start and full backup. Active timed bans remain in the game list and backups; expired entries are removed before a restored server starts. Cleanup also continues while an update downloads. Save failures appear in the panel and journal; fix permissions or free disk space, then retry.

Bans accept a reason of up to 300 characters and a duration, entered in hours, from one minute to 365 days. An empty duration means permanent. A timed ban cannot replace an existing permanent ban; explicitly unban first. Hearth removes its expiring entry on the next check after expiry, then Valheim needs time to reload. A separate permanent entry added by another administrator is preserved. Expiry uses the server clock, so keep the host's time correct.

### Player profiles and moderation history

In **Player profiles by SteamID**, assign a manual alias of up to 80 characters and a note of up to 2,000. These do not change character names or automatically associate logged names with a SteamID. Clearing both fields deletes the profile.

Up to 200 profiles, reasons for active bans, and the latest 200 moderation actions are stored in `/data/moderation.json`, outside full game backups and world exports. Active ban expiry is in the game access list; reasons and notes are not automatically transferred between servers.

SteamID lists and actions require panel sign-in and are not published on the website. Changes are recorded in the journal.

<a id="hearth-admin"></a>
### Hearth Admin: browser tools and the F8 menu

Under **Mods**, install the bundled **Hearth Admin (ValheimAdminRu)**. It uses the existing backup and restart workflow and installs on both the server and the client collection. Players must rerun the website installer and restart Valheim after the collection changes. If it was installed manually before, back up and remove the old DLL on both the server and every client first. Client installers do not automatically remove manual copies; leaving one creates a duplicate plugin.

The mod requires BepInEx 5.4 or Valheim Plus. It is unavailable in vanilla mode. Server and clients must use matching mod versions. The mod targets Valheim **1.0.16 and 1.0.17**; DLL 0.4.0 was built against 1.0.17 libraries. The project maintainer confirmed in-game testing before Hearth 1.6.0. After changing the game version or mod collection, try the actions on a world copy first.

- **In the game:** press **F8** to open the RU / EN menu. Native server administrators are Owners; additional Moderator and Builder roles are stored by the mod. Roles control the commands available in F8.
- **In the browser:** a signed-in Hearth administrator can use **Game tools** and select an online executor by SteamID. Its compatible client performs self actions, spawning, terrain changes, building, and hammer operations. Assistance and travel to another player use a separate target SteamID. The executor does not need an F8 role and does not gain one by executing a browser command.
- **Saved points:** browser tools list and use points from the executor's client for the current world. Create and delete points in F8. Return uses that client's current teleport history.

World-changing commands require confirmation. The panel waits for the matching client acknowledgement and does not automatically repeat a command after a timeout or session change. If the result is unknown, inspect the game before trying again. An acknowledgement is not a guarantee that every gameplay effect completed as expected. Use **Players** for web bans, unbans, and disconnects; those remain available independently of the mod.

Server mod roles, audit, and state are stored under `BepInEx/config/ValheimAdminRu/` (`roles.xml`, `audit.xml`, `state.xml`). Hearth maps that directory to `/data/config/ValheimAdminRu/`, so it survives game-release changes and is included in full game backups and restoration. Client points stay on each player's computer. A world export does not transfer these mod XML files or the plugin; install the matching plugin and move any required private data separately.

The filesystem bridge under `/data/admin-bridge` is private to the running server and panel. It adds no public game-control listener and is excluded from game backups and client downloads. Pending commands are discarded when a new game process starts. Do not copy bridge request files between installations or worlds. Public client packages contain the plugin, not server roles, audit, state, or bridge files.

## Server health

**Server health** separates a running game process from a fresh A2S reply received within the last 30 seconds. A2S confirms the statistics query responds; test an actual client connection separately. During startup, the world is given time to load before missing replies are shown as a problem, with suggested actions and a link to the journal.

Metrics are sampled approximately every ten seconds: game-process CPU, its resident memory, container memory usage and Docker limit, and free/total space on the data filesystem. CPU at 100% means one core; values above 100% are possible. These are process/container measurements, not statistics for the entire remote host. Unavailable metrics are not replaced with zero. Linux measurements use `/proc` and cgroup v1/v2. Recommendations appear below 1 GiB or 5% free disk space, and at 90% or more of the memory limit.

The save time comes from changes to the selected world's classic `.db`/`.fwl` files or chunk directory. Other worlds and the game's automatic backups are excluded. It is a file modification time, not a check of world integrity or gameplay progress.

The last successful backup is based on a completed panel operation and the presence of its final archive. Temporary and unrelated files do not count; the entire TAR is not verified by this monitor. Health diagnostics require sign-in.

## Game updates and rollback

1. Select **Install latest versions**. There are no version numbers to enter.
2. Hearth downloads the current Steam public-branch server for the selected mode. V+ additionally resolves Grantapher's latest stable release, verifies the official `UnixServer.zip` SHA-256, and installs BepInEx. Custom BepInEx mode installs its loader without V+.
3. The candidate runs on a separate temporary world. Hearth checks its version, readiness, and loading errors; V+ also requires the expected mod version and BepInEx 5.
4. If only the game's version differs from the mod author's declaration, a one-time approval becomes available for that exact pair and archive hash for 30 minutes. Approval downloads and validates the files again. It does not bypass a wrong checksum or startup errors.
5. The live game stops gracefully, world/configuration/mods are backed up, and the active release switches. Hearth waits up to 180 seconds for the main world to become ready, followed by five seconds of startup observation.
6. On failure, Hearth attempts to restore the previous release, world, and configuration. Restarting the container with an unfinished trial also triggers rollback. A failed first installation has no previous release to restore; its game process is stopped.

Selecting `plus`, `modded`, or `vanilla` in settings does not replace the installed release by itself; apply it through an update. Older releases without a mode field are treated as V+. Rollback restores the previous installed mode; the selected next-install mode may still differ. Additional mods are retained across game updates.

Process readiness does not guarantee every gameplay mechanic or client connection works. Later problems require manual rollback. Approving a version pair does not mean the mod author officially supports it.

## Maintenance and Discord

### One-time maintenance

In **Maintenance**, schedule one restart, stop, backup, or game/mod update up to 30 days ahead, using the browser's time zone. Optionally wait for an empty server. This requires a fresh A2S reply and one minute without players; an unknown count is not considered zero. A stopped server does not need to wait for players.

Player count is checked again immediately before changing the server, including after downloading and validating an update candidate. Returning players or a failed A2S query at this final check cancel the operation without stopping the running game. This checks current state; it does not prevent new connections.

A pending task can be cancelled and survives panel restarts. A task that already started and was interrupted by a restart is not automatically repeated: inspect the journal and schedule another. Tasks use settings current at execution time. Scheduled updates do not approve V+ version mismatches; use the normal update flow with manual approval. The website displays pending or current maintenance. No in-game messages are sent.

### Recurring maintenance

Under **Maintenance → Recurring maintenance**, create up to 20 daily or weekly schedules. Choose an action, local time, IANA time zone such as `Asia/Krasnoyarsk`, and weekdays. Edit, pause, resume, or delete schedules. The table shows the next seven days in each schedule's own time zone; history retains the latest 50 outcomes.

Recurring tasks always wait for a fresh A2S reply and one empty minute. The waiting window is 2–1,440 minutes from the scheduled time, including queue time and update-candidate validation. If it expires before the server change starts, that occurrence is skipped without forcing players offline; the next occurrence remains scheduled. Tasks execute sequentially.

Occurrences missed while the panel is off are not caught up, and interrupted operations are not replayed. At daylight-saving transitions, a nonexistent local time is skipped and a repeated local time runs once. Automatic V+ compatibility approval is not supported.

Recurring backups use **Settings → Panel → Scheduled backups to keep**. The older interval-based backup schedule remains independent; disable it if recurring schedules now cover all backups. Manual and pre-update archives remain separate from this retention limit.

### Discord notifications

Under **Maintenance → Discord notifications**, enter a webhook for an ordinary Discord text channel and choose events: server availability, updates/rollback, backups, maintenance, operation errors, or moderation. Leaving the field blank preserves the current address; use the separate removal option to delete it. Save before sending a test message. The first availability notification follows an A2S reply and does not guarantee a game client can connect.

The webhook URL is not returned by the API. It is stored in `/data/operations.json` with maintenance tasks, outside game backups and world exports. Notifications include the server name and a short message, without passwords, moderator notes, or raw game-error text. Moderation notifications include SteamID, ban reason and duration, and ban removal/expiry; profile aliases are excluded. Mass mentions are disabled.

Delivery uses a background queue of up to 20 messages; identical events are suppressed for one minute. Network failures, Discord rate limits, or webhook rejection produce a delivery error without interrupting the game operation. Retries and queue persistence across restarts are not implemented. Removing the webhook blocks new notifications; a message already being sent may still arrive.

## Panel updates and migration

### Update the panel

**Updates → Panel version** shows the version of the running build. Checking for updates queries the latest stable GitHub release, at most once per minute, and provides a link to release notes. The panel offers the rebuild command for the main or second server described here.

First download the release and replace the project files in the **existing directory**, then run the suggested command with the **same Compose project name, `-p`/`-f` options, and data volume**. The panel has no Docker socket access and cannot rebuild itself. Updating the panel does not automatically update the game. Development versions use a `-dev` suffix; release preparation updates `app/PANEL_VERSION`.

### Migrate an older installation

1. Create and download a game backup from the old panel.
2. Update the code in the existing project directory, keeping the same Compose project name and data volume.
3. Run `docker compose up -d --build`, with the same `-p` and `-f` arguments used previously.
4. If the wizard appears, set an administrator password and check the recovered game settings. When an existing release is found, setup backs it up before changes, preserves worlds and release files, and starts it.

An old panel password supplied only through the environment was not stored in the game volume. The new Compose file does not read it; assign a new password in the wizard. Game settings previously saved through the panel are recovered automatically. A blank game password retains the saved value. If settings previously existed only in external configuration, check the world name, password, addresses, and mode; available saves appear in the world selector. Saves are not deleted.

Older Compose files still passing legacy variables support a one-time panel-password migration into protected storage. New installations do not need them. Once `panel.json` exists, saved panel settings take precedence. Setup does not reappear on every update.

**Do not run `docker compose down -v` for a world you want to keep:** `-v` deletes the data volume.

## Second instance

The included second Compose file also needs no environment files:

```bash
docker compose -f compose.second.yaml -p valheim-second up -d --build
```

Open **http://localhost:8081** and complete its separate wizard. You can choose vanilla there. This instance uses UDP **2466–2467**, a separate Compose project name, and its own `game` volume. On a remote host, use `http://SERVER_IP:8081` or the second site's reverse-proxy domain. Its game connection port is 2466.

Keep using `-f compose.second.yaml -p valheim-second` when managing that instance. The two project names must differ. Never attach the same data volume to two game processes.

The panel cannot change published Docker ports. For a third instance or a custom network, choose another free UDP port pair and web port in a separate Compose file. The game's internal ports must match the mapping; the query port is the game port plus one. The wizard's website and connection addresses describe where players connect; they do not configure host networking.

## Interface language

**RU / EN** is available on the website, sign-in page, panel, and setup wizard. Switching is immediate, without reloading or clearing drafts, selected files, or open dialogs. The preference is stored in the browser, shared by pages at the same origin, and synchronized between tabs. A first visit uses Russian for a Russian-language browser and English otherwise. Without browser storage, switching still works for the current page session.

Server, world, and player names, addresses, commands, CFG values, and raw console output are not translated. The English V+ editor uses English labels and the author's original descriptions, with translated value constraints. **Settings → Website** has separate Russian and English world descriptions; if the English field is empty, the Russian text is displayed. Custom text is not automatically translated. Panel dates follow the selected language. This switch does not change installer language.

## Troubleshooting

### Check the container and its log

From the current installation's directory:

```bash
docker compose ps
docker compose logs --tail=100 valheim
```

For a second or custom instance, include the same `-f` and `-p` options used to start it. Docker's `healthy` status confirms the web panel responds. Check **Server health** and the journal for game readiness and online status.

### Setup appears again after an update

Check the project directory, Compose project name, selected Compose file, and attached volume first. A different directory or missing `-p` can select a new, empty volume. Keep the old volume. For an older installation, follow [migration](#migrate-an-older-installation).

### The website works, but players cannot connect

The web port and game UDP ports are independent. Check DNS and the connection address, firewall rules, forwarding for UDP 2456–2457 (2466–2467 for the second instance), game startup logs, and matching client versions. An HTTP reverse proxy does not publish game UDP ports. An A2S reply or server-list entry is not a substitute for testing a real client connection.

### nginx rejects a ZIP upload

Allow `client_max_body_size 1g;` for world imports or `128m` for mod uploads, and use `proxy_read_timeout 300s;`. Keep enough free disk space for validation and the pre-change backup. Check the active site's proxy configuration, not only Hearth's settings.

### An operation failed

Read the journal before retrying. Unknown player count is not treated as an empty server, and a stuck process cannot produce a consistent backup. After an unsuccessful update, check the rollback result. After importing a world, the game intentionally remains stopped until you review settings and start it manually.

## Developer reference

Persistent data is under `/data`:

| Path | Purpose |
|---|---|
| `releases/` | Installed game releases |
| `saves/` | Worlds and native access lists |
| `config/` | Game and V+ configuration |
| `mods/` | Additional mod collection and loader data |
| `backups/` | Full game backup archives |
| `exports/`, `incoming/` | World exports and incoming transfers |
| `logs/` | Game logs |
| `state.json` | Active release and operation recovery state |
| `panel.sqlite` | Player statistics and journal |
| `panel.json` | Panel settings and administrator password hash |
| `operations.json` | Maintenance schedules and Discord webhook settings |
| `moderation.json` | Player profiles, ban reasons, and moderation history |
| `client-mods.zip`, `client-mods.json` | Published client package and its metadata |

The panel and game run as UID 10001, without root, privileged mode, or Docker socket access. Settings writes are atomic and game operations are serialized. Panel access uses a password, HttpOnly/SameSite cookies, CSRF protection, and sign-in rate limiting.

Development checks:

```bash
python -m unittest discover -s tests -q
node --check app/static/app.js
node --check app/static/settings.js
node --check app/static/setup.js
node --check app/static/landing.js
node tests/test_i18n.cjs
```

Build the Windows installer from PowerShell with `./installer/build.ps1`, and the Linux installer with `python installer-linux/build.py`. Published installers and their SHA-256 files are under `app/downloads/`. The game-server version and Hearth panel version are independent.

Source directories: [panel](../app/), [Windows installer](../installer/), [Linux installer](../installer-linux/), and [tests](../tests/). Run development checks from the repository root with application dependencies installed; they are not required for ordinary server operation.
