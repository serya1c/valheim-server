#!/usr/bin/env bash
# Деплой панели Valheim (Hearth) из /tmp/valheim-incoming в /data/valheim-server.
# Устанавливается как /usr/local/bin/deploy-valheim (root:root, 0755) на HASTRII.
# Ставится из репозитория (scripts/deploy-valheim.sh) на HASTRII.
# Разрешается в sudoers только для пользователя раннера GitHub Actions.
#
# Что делает: бэкап исходников -> сборка образа -> пересоздание контейнера ->
# ожидание /health -> откат на предыдущий образ, если health не поднялся.
# Том game (мир, настройки, моды) не трогается. down -v не используется.
#
# Флаг --force: продолжить, если старый контейнер уже нездоров.
set -euo pipefail

SRC=/tmp/valheim-incoming
DST=/data/valheim-server
PROJECT=valheim-server
SERVICE=valheim
IMAGE=$PROJECT-$SERVICE
BACKUP_DIR=/var/backups/valheim
STAMP=$(date +%Y%m%d-%H%M%S)
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

log() { echo "[deploy-valheim $(date +%H:%M:%S)] $*"; }

[ "$(id -u)" = 0 ] || { echo "нужен root" >&2; exit 1; }
[ -d "$SRC" ] || { echo "staging $SRC missing" >&2; exit 2; }
[ -f "$SRC/compose.yaml" ] || { echo "staging: нет compose.yaml — отказ" >&2; exit 3; }
[ -f "$SRC/app/server.py" ] || { echo "staging: нет app/server.py — отказ" >&2; exit 4; }
[ -d "$DST" ] || { echo "$DST missing" >&2; exit 5; }

old_health=$(docker inspect -f '{{.State.Health.Status}}' "$PROJECT-$SERVICE-1" 2>/dev/null || echo "none")
log "текущий health: $old_health"
if [ "$old_health" != "healthy" ] && [ "$FORCE" != 1 ]; then
    echo "контейнер не healthy ($old_health). Перезапуск игрового сервера без --force запрещён." >&2
    exit 6
fi

mkdir -p "$BACKUP_DIR"
log "бэкап исходников -> $BACKUP_DIR/source-$STAMP.tgz"
tar czf "$BACKUP_DIR/source-$STAMP.tgz" \
    -C "$(dirname "$DST")" --exclude='.git' "$(basename "$DST")"
ls -1t "$BACKUP_DIR"/source-*.tgz | tail -n +11 | xargs -r rm -f

prev_image=""
if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    prev_image="$IMAGE:rollback-$STAMP"
    docker tag "$IMAGE" "$prev_image"
    log "предыдущий образ сохранён как $prev_image"
fi

log "раскладка исходников"
rsync -a --delete \
    --exclude='.git' \
    --exclude='.env' \
    --exclude='.env.*' \
    --exclude='valheim-plus.cfg' \
    "$SRC"/ "$DST"/
chown -R root:root "$DST"

cd "$DST"
log "сборка образа"
docker compose -p "$PROJECT" -f compose.yaml build

log "пересоздание контейнера (игровой сервер перезапустится)"
docker compose -p "$PROJECT" -f compose.yaml up -d --remove-orphans

log "ожидание health (до 180 с)"
for _ in $(seq 1 36); do
    if curl -fsS --max-time 5 http://127.0.0.1:8080/health >/dev/null 2>&1; then
        log "deployed OK, health отвечает"
        ls -1t "$BACKUP_DIR"/source-*.tgz | tail -n +4 | xargs -r rm -f
        exit 0
    fi
    sleep 5
done

log "health не поднялся — откат"
docker logs --tail 80 "$PROJECT-$SERVICE-1" 2>&1 || true
if [ -n "$prev_image" ]; then
    docker tag "$prev_image" "$IMAGE"
    docker compose -p "$PROJECT" -f compose.yaml up -d --force-recreate
    tar xzf "$BACKUP_DIR/source-$STAMP.tgz" -C "$(dirname "$DST")"
    log "откатился на $prev_image"
fi
rm -rf "${SRC:?}"/*
exit 7
