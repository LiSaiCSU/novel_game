#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${NOVEGAME_ENV_FILE:-/etc/novegame/novegame.env}"
BACKUP_ROOT="${NOVEGAME_BACKUP_DIR:-/var/backups/novegame}"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.prod.yaml")

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run the backup with sudo." >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Production configuration not found: $ENV_FILE" >&2
  exit 1
fi
BACKUP_ROOT="$(realpath -m "$BACKUP_ROOT")"
case "$BACKUP_ROOT" in
  / | /var | /home | /root | /opt | /usr | /etc)
    echo "Refusing to use unsafe backup root: $BACKUP_ROOT" >&2
    exit 1
    ;;
esac
if [[ -z "$("${COMPOSE[@]}" ps -q postgres 2>/dev/null)" ]]; then
  echo "PostgreSQL is not running; no backup was created." >&2
  exit 1
fi

STAMP="$(date -u +%Y%m%d-%H%M%S)"
TARGET="$BACKUP_ROOT/$STAMP"
install -d -m 700 "$TARGET"

echo "Creating PostgreSQL backup..."
"${COMPOSE[@]}" exec -T postgres sh -ec \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' >"$TARGET/postgres.dump"

echo "Creating object-storage backup..."
if ! docker volume inspect novegame-v2_object-data >/dev/null 2>&1; then
  echo "Object-storage volume novegame-v2_object-data was not found." >&2
  exit 1
fi
docker run --rm \
  --volume novegame-v2_object-data:/source:ro \
  --volume "$TARGET:/backup" \
  alpine:3.21 \
  tar -C /source -czf /backup/object-data.tar.gz .

install -m 600 "$ENV_FILE" "$TARGET/deployment-secrets.env"
sha256sum "$TARGET/postgres.dump" "$TARGET/object-data.tar.gz" >"$TARGET/SHA256SUMS"
chmod -R go-rwx "$TARGET"

find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +14 -print -exec rm -rf -- {} +
echo "Backup created: $TARGET"
