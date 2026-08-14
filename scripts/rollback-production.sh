#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${NOVEGAME_ENV_FILE:-/etc/novegame/novegame.env}"
COMPOSE_FILE="$ROOT_DIR/compose.prod.yaml"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run rollback with sudo." >&2
  exit 1
fi

read_env_value() {
  local key="$1"
  local value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)"
  value="${value#\'}"
  value="${value%\'}"
  printf "%s" "$value"
}

set_env_value() {
  local key="$1"
  local value="$2"
  local temp
  temp="$(mktemp)"
  awk -v key="$key" -v value="$value" '
    BEGIN { found = 0 }
    $0 ~ "^" key "=" { print key "=\x27" value "\x27"; found = 1; next }
    { print }
    END { if (!found) print key "=\x27" value "\x27" }
  ' "$ENV_FILE" >"$temp"
  install -m 600 "$temp" "$ENV_FILE"
  rm -f "$temp"
}

CURRENT_TAG="$(read_env_value IMAGE_TAG)"
PREVIOUS_TAG="$(read_env_value PREVIOUS_IMAGE_TAG)"
if [[ -z "$PREVIOUS_TAG" ]]; then
  echo "No previous application image is recorded." >&2
  exit 1
fi
if ! docker image inspect "novegame-api:$PREVIOUS_TAG" >/dev/null 2>&1 || \
  ! docker image inspect "novegame-web:$PREVIOUS_TAG" >/dev/null 2>&1; then
  echo "Previous images are no longer available on this server." >&2
  exit 1
fi

set_env_value IMAGE_TAG "$PREVIOUS_TAG"
set_env_value PREVIOUS_IMAGE_TAG "$CURRENT_TAG"
COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
"${COMPOSE[@]}" up -d --no-deps api worker web

echo "Application images rolled back to $PREVIOUS_TAG."
echo "Database migrations were not reversed. Restore a matching backup if the old code is not schema-compatible."
