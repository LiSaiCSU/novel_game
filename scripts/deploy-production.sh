#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${NOVEGAME_ENV_FILE:-/etc/novegame/novegame.env}"
COMPOSE_FILE="$ROOT_DIR/compose.prod.yaml"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run deployment with sudo: sudo bash scripts/deploy-production.sh" >&2
  exit 1
fi
command -v docker >/dev/null 2>&1 || {
  echo "Docker is not installed." >&2
  exit 1
}
docker compose version >/dev/null 2>&1 || {
  echo "Docker Compose Plugin is not installed." >&2
  exit 1
}

if [[ ! -f "$ENV_FILE" ]]; then
  bash "$ROOT_DIR/scripts/init-production-env.sh" "$ENV_FILE"
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
if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  NEW_TAG="$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD)"
else
  NEW_TAG="$(date -u +%Y%m%d%H%M%S)"
fi

COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
if [[ -n "$("${COMPOSE[@]}" ps -q postgres 2>/dev/null)" ]]; then
  bash "$ROOT_DIR/scripts/backup-production.sh"
fi

if [[ -n "$CURRENT_TAG" && "$CURRENT_TAG" != "bootstrap" && "$CURRENT_TAG" != "$NEW_TAG" ]]; then
  set_env_value PREVIOUS_IMAGE_TAG "$CURRENT_TAG"
fi
set_env_value IMAGE_TAG "$NEW_TAG"

COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
echo "Validating production configuration..."
"${COMPOSE[@]}" config --quiet

echo "Building application images..."
"${COMPOSE[@]}" build --pull api web

echo "Starting stateful services..."
"${COMPOSE[@]}" up -d --wait postgres redis minio clamav

echo "Provisioning the restricted database role and object bucket..."
"${COMPOSE[@]}" run --rm postgres-role
"${COMPOSE[@]}" run --rm minio-init

echo "Running database migrations..."
"${COMPOSE[@]}" run --rm --no-deps migrate

echo "Starting API, worker and player application..."
"${COMPOSE[@]}" up -d --no-deps api worker

API_READY=false
for _ in $(seq 1 45); do
  if "${COMPOSE[@]}" exec -T api python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=4)" \
    >/dev/null 2>&1; then
    API_READY=true
    break
  fi
  sleep 4
done
if [[ "$API_READY" != "true" ]]; then
  "${COMPOSE[@]}" logs --tail=120 api
  echo "API readiness check failed. The previous image tag is preserved for rollback." >&2
  exit 1
fi

"${COMPOSE[@]}" up -d --no-deps web
WEB_READY=false
for _ in $(seq 1 30); do
  if "${COMPOSE[@]}" exec -T web node -e \
    "fetch('http://127.0.0.1:3000').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))" \
    >/dev/null 2>&1; then
    WEB_READY=true
    break
  fi
  sleep 3
done
if [[ "$WEB_READY" != "true" ]]; then
  "${COMPOSE[@]}" logs --tail=120 web
  echo "Web readiness check failed." >&2
  exit 1
fi

"${COMPOSE[@]}" up -d --no-deps caddy
DOMAIN="$(read_env_value DOMAIN)"

PUBLIC_READY=false
for _ in $(seq 1 30); do
  if curl -fsS --max-time 10 "https://$DOMAIN/api/ready" >/dev/null 2>&1; then
    PUBLIC_READY=true
    break
  fi
  sleep 4
done

"${COMPOSE[@]}" ps
if [[ "$PUBLIC_READY" == "true" ]]; then
  echo "Deployment succeeded: https://$DOMAIN"
else
  echo "Containers are healthy, but public HTTPS is not reachable yet. Check DNS and Caddy logs:" >&2
  echo "  docker compose --env-file $ENV_FILE -f $COMPOSE_FILE logs caddy" >&2
  exit 2
fi
