#!/usr/bin/env bash
# Offline per-user installation. Generated distribution appends a verified TAR payload.
set -euo pipefail
mode=${1:---install}
case "$mode" in --install|--uninstall) ;; *) printf 'Usage: bash %s [--install|--uninstall]\n' "$0" >&2; exit 2 ;; esac
[[ $# -le 1 ]] || { printf 'Unexpected arguments.\n' >&2; exit 2; }
[[ $(id -u) -ne 0 ]] || { printf 'Run as your desktop user, without sudo. / Запустите без sudo.\n' >&2; exit 1; }
[[ $(uname -m) == x86_64 ]] || { printf 'This launcher requires Linux x86_64.\n' >&2; exit 1; }
for command in sha256sum tar mktemp readlink sed awk chmod mv cp mkdir rmdir rm base64 head grep od tr date; do
    command -v "$command" >/dev/null || { printf 'Missing system command: %s\n' "$command" >&2; exit 1; }
done
data=${XDG_DATA_HOME:-"${HOME:?}/.local/share"}
target="$data/HearthLauncher"
menu="$data/applications"
desktop="${HOME:?}/Desktop"
if command -v xdg-user-dir >/dev/null; then
    detected_desktop=$(xdg-user-dir DESKTOP 2>/dev/null || true)
    [[ -z "$detected_desktop" ]] || desktop="$detected_desktop"
fi
marker='.hearth-launcher-install'
signature='HEARTH_LAUNCHER_INSTALL_1'
stage=''
previous=''
lock=''
payload=''
shortcut_file=''
shortcut_backups=()
written_shortcuts=()
swapped=0
committed=0

fail() { printf '%s\n' "$*" >&2; exit 1; }
no_links() {
    local cursor="$1"
    [[ "$cursor" == /* && "$cursor" != *$'\n'* && "$cursor" != *$'\r'* ]] || fail "Invalid absolute path: $cursor"
    [[ "$cursor" != *'/../'* && "$cursor" != */.. && "$cursor" != *'/./'* ]] || fail "Ambiguous path: $cursor"
    while [[ "$cursor" != / ]]; do
        [[ ! -L "$cursor" ]] || fail "Linked paths are not supported: $cursor"
        cursor=${cursor%/*}; [[ -n "$cursor" ]] || cursor=/
    done
}
contents() {
    local directory="$1" item name
    no_links "$directory"
    for item in "$directory"/* "$directory"/.[!.]* "$directory"/..?*; do
        [[ -e "$item" || -L "$item" ]] || continue
        no_links "$item"; [[ -f "$item" ]] || fail "Unexpected directory: $item"
        name=${item##*/}
        case "$name" in Hearth-Launcher|hearth.png|README.md|uninstall.sh|.hearth-launcher-install) ;; *) fail "Move unrecognized file before reinstalling: $item" ;; esac
    done
}
owned() {
    local directory="$1"
    contents "$directory"
    [[ -f "$directory/$marker" && $(head -n 1 "$directory/$marker") == "$signature" && -f "$directory/Hearth-Launcher" ]] || fail "Not a Hearth Launcher installation: $directory"
}
remove_owned() {
    local directory="$1" item
    contents "$directory"
    for item in "$directory"/* "$directory"/.[!.]* "$directory"/..?*; do
        [[ -e "$item" ]] || continue
        rm -- "$item"
    done
    rmdir -- "$directory"
}
closed() {
    local process executable
    for process in /proc/[0-9]*/exe; do
        executable=$(readlink -- "$process" 2>/dev/null || true)
        [[ "$executable" != "$target/Hearth-Launcher" && "$executable" != "$target/Hearth-Launcher (deleted)" ]] || fail 'Close Hearth Launcher first. / Сначала закройте Hearth Launcher.'
    done
}
check_shortcut() {
    local shortcut="$1"
    no_links "$shortcut"
    if [[ -e "$shortcut" ]]; then
        [[ -f "$shortcut" ]] && grep -Fxq "X-Hearth-Launcher-Directory-SHA256=$target_digest" "$shortcut" || fail "Existing shortcut belongs to another application: $shortcut"
    fi
}
cleanup() {
    local result=$?
    trap - EXIT
    set +e
    if [[ $swapped == 1 && $committed == 0 ]]; then
        [[ ! -d "$target" ]] || (remove_owned "$target") || printf 'Rollback cleanup failed: %s\n' "$target" >&2
        [[ -z "$previous" || ! -d "$previous" ]] || mv -- "$previous" "$target" || printf 'Previous installation remains at %s\n' "$previous" >&2
    fi
    if [[ $committed == 0 ]]; then
        for index in "${!written_shortcuts[@]}"; do
            shortcut=${written_shortcuts[$index]}
            backup=${shortcut_backups[$index]}
            (no_links "$shortcut") || continue
            if [[ -n "$backup" ]]; then cp -- "$backup" "$shortcut"; else [[ ! -e "$shortcut" ]] || rm -- "$shortcut"; fi
        done
    fi
    [[ -z "$stage" || ! -d "$stage" ]] || (remove_owned "$stage")
    if [[ -n "$lock" && -d "$lock" ]]; then
        for item in "$payload" "$shortcut_file" "${shortcut_backups[@]}"; do
            [[ -z "$item" || ! -e "$item" ]] || rm -- "$item"
        done
        rmdir -- "$lock"
    fi
    exit "$result"
}
trap cleanup EXIT
for location in "$data" "$target" "$menu" "$desktop"; do no_links "$location"; done
data=$(readlink -m -- "$data")
target=$(readlink -m -- "$target")
menu=$(readlink -m -- "$menu")
desktop=$(readlink -m -- "$desktop")
[[ "$target" != *'='* ]] || fail 'The launcher installation path must not contain = (desktop-entry executable restriction).'
target_digest=$(printf '%s' "$target" | sha256sum); target_digest=${target_digest%% *}
mkdir -p -- "$data"
candidate_lock="$data/.hearth-launcher-install.lock"
mkdir -- "$candidate_lock" || fail 'Another installation is running, or a stale installation lock needs removal.'
lock="$candidate_lock"
if [[ "$mode" == --uninstall ]]; then
    owned "$target"; closed
    for shortcut in "$menu/hearth-launcher.desktop" "$desktop/Hearth Launcher.desktop"; do
        no_links "$shortcut"
        if [[ -f "$shortcut" ]] && grep -Fxq "X-Hearth-Launcher-Directory-SHA256=$target_digest" "$shortcut"; then rm -- "$shortcut"; fi
    done
    remove_owned "$target"
    command -v update-desktop-database >/dev/null && update-desktop-database "$menu" >/dev/null 2>&1 || true
    printf 'Hearth Launcher removed. Profiles, game files and mods preserved. / Лаунчер удалён, профили сохранены.\n'
    exit 0
fi
if [[ -e "$target" ]]; then owned "$target"; closed; fi
check_shortcut "$menu/hearth-launcher.desktop"
check_shortcut "$desktop/Hearth Launcher.desktop"
stage=$(mktemp -d "$data/.hearth-stage-XXXXXXXX")
payload=$(mktemp "$lock/payload-XXXXXXXX.tar.gz")
awk 'found { print } /^__HEARTH_PAYLOAD__$/ { found=1 }' "$0" | base64 --decode > "$payload"
printf '%s  %s\n' '@PAYLOAD_SHA256@' "$payload" | sha256sum -c - >/dev/null || fail 'The installer is damaged: SHA-256 mismatch.'
listing=$(tar -tzf "$payload")
[[ "$listing" == $'Hearth-Launcher\nhearth.png\nREADME.md' ]] || fail 'Unexpected archive contents.'
tar -xzf "$payload" -C "$stage" --no-same-owner --no-same-permissions
rm -- "$payload"
contents "$stage"
[[ -s "$stage/Hearth-Launcher" && -s "$stage/hearth.png" && -s "$stage/README.md" ]] || fail 'Incomplete payload.'
[[ $(head -c 4 "$stage/Hearth-Launcher" | od -An -tx1 | tr -d ' \n') == 7f454c46 ]] || fail 'Missing Linux executable.'
chmod 755 "$stage/Hearth-Launcher"
chmod 644 "$stage/hearth.png" "$stage/README.md"
printf '%s\n%s\n' "$signature" '1.1.0' > "$stage/$marker"
# Keep only the script header; the installed uninstaller never needs the 40 MB payload.
awk '/^__HEARTH_PAYLOAD__$/ {exit} {print}' "$0" | sed 's/^mode=${1:---install}$/mode=--uninstall/' > "$stage/uninstall.sh"
chmod 755 "$stage/uninstall.sh"
previous="$data/.hearth-previous-$(date +%s)-$$"
no_links "$previous"; [[ ! -e "$previous" ]] || fail 'Temporary backup already exists.'
if [[ -d "$target" ]]; then owned "$target"; mv -- "$target" "$previous"; fi
swapped=1
mv -- "$stage" "$target"; stage=''
mkdir -p -- "$menu" "$desktop"
# Exec has two unescaping layers: command quoting, then desktop string escapes.
escaped_executable=$(printf '%s' "$target/Hearth-Launcher" | sed 's/\\/\\\\/g; s/"/\\"/g; s/`/\\`/g; s/\$/\\$/g; s/%/%%/g' | sed 's/\\/\\\\/g; s/\t/\\t/g')
escaped_icon=$(printf '%s' "$target/hearth.png" | sed 's/\\/\\\\/g; s/\t/\\t/g')
shortcut_file=$(mktemp "$lock/shortcut-XXXXXXXX")
cat > "$shortcut_file" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=Hearth Launcher
Comment=Play Valheim with the server's mod collection
Comment[ru]=Valheim с модами выбранного сервера
Exec="$escaped_executable"
Icon=$escaped_icon
Terminal=false
Categories=Game;
StartupWMClass=HearthLauncher
X-Hearth-Launcher-Directory-SHA256=$target_digest
EOF
for shortcut in "$menu/hearth-launcher.desktop" "$desktop/Hearth Launcher.desktop"; do
    check_shortcut "$shortcut"
    backup=''
    if [[ -f "$shortcut" ]]; then
        backup=$(mktemp "$lock/shortcut-backup-XXXXXXXX")
        cp -- "$shortcut" "$backup"
    fi
    written_shortcuts+=("$shortcut"); shortcut_backups+=("$backup")
    cp -- "$shortcut_file" "$shortcut"
    chmod 755 "$shortcut"
done
rm -- "$shortcut_file"
command -v gio >/dev/null && gio set "$desktop/Hearth Launcher.desktop" metadata::trusted true >/dev/null 2>&1 || true
command -v update-desktop-database >/dev/null && update-desktop-database "$menu" >/dev/null 2>&1 || true
committed=1
[[ ! -d "$previous" ]] || remove_owned "$previous"
printf 'Hearth Launcher 1.1.0 installed: %s\nDesktop and application-menu shortcuts created.\nУстановка завершена. Ярлыки созданы.\n' "$target"
printf 'If your desktop asks, choose Allow Launching. / Если нужно, разрешите запуск ярлыка.\n'
printf 'Uninstall: bash "%s/uninstall.sh"\n' "$target"
exit 0
__HEARTH_PAYLOAD__
