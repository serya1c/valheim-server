#!/usr/bin/env bash
# Печатает версию Valheim по логу выделенного сервера: "Valheim version: 1.0.21".
# В серверной assembly_valheim.dll строки версии нет (тип Version вырезан),
# поэтому единственный надёжный источник — запуск сервера, как это делает панель.
# usage: probe.sh <каталог сервера> [таймаут, с]
set -euo pipefail

GAME_DIR=${1:?usage: probe.sh <каталог сервера> [таймаут]}
LIMIT=${2:-180}
PORT=${PROBE_PORT:-2466}
LOG=$(mktemp)
SAVES=$(mktemp -d)
PID=""

cleanup() {
    if [ -n "$PID" ]; then
        # Сервер запущен в собственной группе процессов: гасим всю группу.
        kill -- -"$PID" 2>/dev/null || true
    fi
    rm -rf "$LOG" "$SAVES"
}
trap cleanup EXIT

setsid bash -c '
    cd "$1" || exit 1
    exec env LD_LIBRARY_PATH=./linux64 SteamAppId=892970 \
        ./valheim_server.x86_64 -nographics -batchmode -name CIProbe -port "$2" \
        -world CIProbe -password ciprobe1 -savedir "$3" -public 0
' _ "$GAME_DIR" "$PORT" "$SAVES" >"$LOG" 2>&1 &
PID=$!

for _ in $(seq 1 "$LIMIT"); do
    version=$(grep -aoE 'Valheim version:[[:space:]]*([A-Za-z]-)?[0-9]+\.[0-9]+\.[0-9]+' "$LOG" 2>/dev/null \
        | tail -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+$' || true)
    if [ -n "$version" ]; then
        echo "$version"
        exit 0
    fi
    if ! kill -0 "$PID" 2>/dev/null; then
        break
    fi
    sleep 1
done

echo "сервер не сообщил версию за ${LIMIT} с" >&2
tail -40 "$LOG" >&2 || true
exit 1
