#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${1:-${NOVEGAME_ENV_FILE:-/etc/novegame/novegame.env}}"

if [[ -e "$ENV_FILE" ]]; then
  echo "Production configuration already exists: $ENV_FILE"
  exit 0
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this initializer with sudo so the configuration remains root-owned." >&2
  exit 1
fi

command -v openssl >/dev/null 2>&1 || {
  echo "openssl is required to generate deployment secrets." >&2
  exit 1
}

prompt_value() {
  local variable="$1"
  local label="$2"
  local default_value="${3:-}"
  local secret="${4:-false}"
  local required="${5:-true}"
  local current=""

  if [[ -v "$variable" ]]; then
    current="${!variable}"
  fi

  if [[ -z "$current" && -t 0 ]]; then
    if [[ "$secret" == "true" ]]; then
      read -r -s -p "$label: " current
      echo
    elif [[ -n "$default_value" ]]; then
      read -r -p "$label [$default_value]: " current
      current="${current:-$default_value}"
    else
      read -r -p "$label: " current
    fi
  fi
  current="${current:-$default_value}"
  if [[ "$required" == "true" && -z "$current" ]]; then
    echo "$label is required." >&2
    exit 1
  fi
  printf -v "$variable" "%s" "$current"
}

write_value() {
  local key="$1"
  local value="$2"
  if [[ "$value" == *$'\n'* || "$value" == *$'\r'* ]]; then
    echo "$key cannot contain line breaks." >&2
    exit 1
  fi
  value="${value//\\/\\\\}"
  value="${value//\'/\\\'}"
  printf "%s='%s'\n" "$key" "$value" >>"$ENV_FILE"
}

DOMAIN="${DOMAIN:-novelgame.online}"
ACME_EMAIL="${ACME_EMAIL:-}"
REVERSE_PROXY_MODE="${REVERSE_PROXY_MODE:-caddy}"
WEB_HOST_PORT="${WEB_HOST_PORT:-3100}"
API_HOST_PORT="${API_HOST_PORT:-8100}"
SENTRY_DSN="${SENTRY_DSN:-}"
SMTP_HOST="${SMTP_HOST:-}"
SMTP_PORT="${SMTP_PORT:-587}"
SMTP_USERNAME="${SMTP_USERNAME:-}"
SMTP_PASSWORD="${SMTP_PASSWORD:-}"
SMTP_FROM="${SMTP_FROM:-}"
SMTP_SECURITY="${SMTP_SECURITY:-starttls}"
LLM_PROVIDER="${LLM_PROVIDER:-null}"
LLM_API_KEY="${LLM_API_KEY:-}"
LLM_BASE_URL="${LLM_BASE_URL:-}"
LLM_MODEL="${LLM_MODEL:-}"
LLM_EXTRA_BODY="${LLM_EXTRA_BODY:-}"
LLM_REASONING_EXTRA_BODY="${LLM_REASONING_EXTRA_BODY:-}"

prompt_value DOMAIN "Public domain" "novelgame.online"
if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "DOMAIN must be a hostname without a protocol or path." >&2
  exit 1
fi
prompt_value ACME_EMAIL "Email for HTTPS certificate notices"
prompt_value REVERSE_PROXY_MODE "Reverse proxy mode (caddy/nginx)" "caddy"
case "$REVERSE_PROXY_MODE" in
  caddy | nginx) ;;
  *)
    echo "REVERSE_PROXY_MODE must be caddy or nginx." >&2
    exit 1
    ;;
esac
prompt_value WEB_HOST_PORT "Loopback port used by the web container" "3100"
if [[ ! "$WEB_HOST_PORT" =~ ^[0-9]+$ ]] || (( WEB_HOST_PORT < 1024 || WEB_HOST_PORT > 65535 )); then
  echo "WEB_HOST_PORT must be an integer from 1024 to 65535." >&2
  exit 1
fi
prompt_value API_HOST_PORT "Loopback port used by the API container" "8100"
if [[ ! "$API_HOST_PORT" =~ ^[0-9]+$ ]] || (( API_HOST_PORT < 1024 || API_HOST_PORT > 65535 )); then
  echo "API_HOST_PORT must be an integer from 1024 to 65535." >&2
  exit 1
fi
if [[ "$API_HOST_PORT" == "$WEB_HOST_PORT" ]]; then
  echo "API_HOST_PORT and WEB_HOST_PORT must be different." >&2
  exit 1
fi
prompt_value SENTRY_DSN "Sentry DSN"
prompt_value SMTP_HOST "SMTP host"
prompt_value SMTP_PORT "SMTP port" "587"
prompt_value SMTP_USERNAME "SMTP username (leave blank if unused)" "" false false
prompt_value SMTP_PASSWORD "SMTP password (leave blank if unused)" "" true false
prompt_value SMTP_FROM "Sender address" "noreply@$DOMAIN"
prompt_value SMTP_SECURITY "SMTP security (starttls/ssl/plain)" "starttls"
case "$SMTP_SECURITY" in
  starttls)
    SMTP_SSL="false"
    SMTP_STARTTLS="true"
    ;;
  ssl)
    SMTP_SSL="true"
    SMTP_STARTTLS="false"
    ;;
  plain)
    SMTP_SSL="false"
    SMTP_STARTTLS="false"
    ;;
  *)
    echo "SMTP_SECURITY must be starttls, ssl or plain." >&2
    exit 1
    ;;
esac

if [[ -t 0 && -z "${LLM_PROVIDER_INPUT:-}" ]]; then
  read -r -p "Platform LLM provider (null/openai/anthropic/compatible) [$LLM_PROVIDER]: " LLM_PROVIDER_INPUT
  LLM_PROVIDER="${LLM_PROVIDER_INPUT:-$LLM_PROVIDER}"
fi
case "$LLM_PROVIDER" in
  null) ;;
  openai | anthropic)
    prompt_value LLM_API_KEY "Platform LLM API key" "" true
    prompt_value LLM_MODEL "Platform model name"
    prompt_value LLM_BASE_URL "Custom API base URL (leave blank for provider default)" "" false false
    ;;
  compatible)
    prompt_value LLM_BASE_URL "OpenAI-compatible API base URL"
    prompt_value LLM_MODEL "Platform model name"
    prompt_value LLM_API_KEY "API key (leave blank if the endpoint does not require one)" "" true false
    ;;
  *)
    echo "Unsupported LLM_PROVIDER: $LLM_PROVIDER" >&2
    exit 1
    ;;
esac

if [[ "$LLM_BASE_URL" == "https://api.deepseek.com" && -z "$LLM_EXTRA_BODY" ]]; then
  LLM_EXTRA_BODY='{"thinking":{"type":"disabled"}}'
fi

install -d -m 700 "$(dirname "$ENV_FILE")"
umask 077
: >"$ENV_FILE"

write_value COMPOSE_PROJECT_NAME "novegame-v2"
write_value DOMAIN "$DOMAIN"
write_value ACME_EMAIL "$ACME_EMAIL"
write_value REVERSE_PROXY_MODE "$REVERSE_PROXY_MODE"
write_value WEB_HOST_PORT "$WEB_HOST_PORT"
write_value API_HOST_PORT "$API_HOST_PORT"
write_value IMAGE_TAG "bootstrap"
write_value PREVIOUS_IMAGE_TAG ""
write_value POSTGRES_DB "narrative"
write_value POSTGRES_USER "narrative"
write_value POSTGRES_OWNER_PASSWORD "$(openssl rand -hex 32)"
write_value POSTGRES_APP_PASSWORD "$(openssl rand -hex 32)"
write_value REDIS_PASSWORD "$(openssl rand -hex 32)"
write_value MINIO_ROOT_USER "novegame"
write_value MINIO_ROOT_PASSWORD "$(openssl rand -hex 32)"
write_value S3_BUCKET "narrative-assets"
write_value S3_REGION "us-east-1"
write_value AUTH_PEPPER "$(openssl rand -hex 48)"
write_value CREDENTIAL_ENCRYPTION_KEY "$(openssl rand -hex 48)"
write_value ADMIN_MFA_REQUIRED "false"
write_value METRICS_TOKEN "$(openssl rand -hex 32)"
write_value SENTRY_DSN "$SENTRY_DSN"
write_value SENTRY_TRACES_SAMPLE_RATE "0.1"
write_value SMTP_HOST "$SMTP_HOST"
write_value SMTP_PORT "$SMTP_PORT"
write_value SMTP_USERNAME "$SMTP_USERNAME"
write_value SMTP_PASSWORD "$SMTP_PASSWORD"
write_value SMTP_FROM "$SMTP_FROM"
write_value SMTP_SSL "$SMTP_SSL"
write_value SMTP_STARTTLS "$SMTP_STARTTLS"
write_value LLM_PROVIDER "$LLM_PROVIDER"
write_value LLM_API_KEY "$LLM_API_KEY"
write_value LLM_API_KEYS ""
write_value LLM_BASE_URL "$LLM_BASE_URL"
write_value LLM_MODEL "$LLM_MODEL"
write_value LLM_EXTRA_BODY "$LLM_EXTRA_BODY"
write_value LLM_REASONING_EXTRA_BODY "$LLM_REASONING_EXTRA_BODY"
write_value LLM_OUTPUT_BUDGET_SCALE "1.0"
write_value LLM_TRUNCATION_RETRIES "2"
write_value LLM_TURN_TOKEN_LIMIT "120000"
write_value LLM_DAILY_TOKEN_LIMIT "2000000"
write_value LLM_MONTHLY_TOKEN_LIMIT "100000000"
write_value LLM_PRICE_TABLE "{}"
write_value LLM_DAILY_COST_ALERT_MICROUNITS "0"
write_value LOG_LEVEL "INFO"

chmod 600 "$ENV_FILE"
echo "Created root-only production configuration: $ENV_FILE"
