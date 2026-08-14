#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${NOVEGAME_ENV_FILE:-/etc/novegame/novegame.env}"
SITE_NAME="novegame-v2"
AVAILABLE="/etc/nginx/sites-available/$SITE_NAME"
ENABLED="/etc/nginx/sites-enabled/$SITE_NAME"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run the Nginx configurator with sudo." >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Production configuration not found: $ENV_FILE" >&2
  exit 1
fi
for command_name in nginx certbot curl; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "$command_name is required for host Nginx mode." >&2
    exit 1
  }
done

read_env_value() {
  local key="$1"
  local value
  value="$(sed -n "s/^${key}=//p" "$ENV_FILE" | tail -n 1)"
  value="${value#\'}"
  value="${value%\'}"
  printf "%s" "$value"
}

DOMAIN="$(read_env_value DOMAIN)"
ACME_EMAIL="$(read_env_value ACME_EMAIL)"
WEB_HOST_PORT="$(read_env_value WEB_HOST_PORT)"
WEB_HOST_PORT="${WEB_HOST_PORT:-3100}"
API_HOST_PORT="$(read_env_value API_HOST_PORT)"
API_HOST_PORT="${API_HOST_PORT:-8100}"

if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+$ ]]; then
  echo "Invalid DOMAIN in $ENV_FILE." >&2
  exit 1
fi
if [[ -z "$ACME_EMAIL" ]]; then
  echo "ACME_EMAIL is required." >&2
  exit 1
fi
if [[ ! "$WEB_HOST_PORT" =~ ^[0-9]+$ ]] || (( WEB_HOST_PORT < 1024 || WEB_HOST_PORT > 65535 )); then
  echo "Invalid WEB_HOST_PORT in $ENV_FILE." >&2
  exit 1
fi
if [[ ! "$API_HOST_PORT" =~ ^[0-9]+$ ]] || (( API_HOST_PORT < 1024 || API_HOST_PORT > 65535 )); then
  echo "Invalid API_HOST_PORT in $ENV_FILE." >&2
  exit 1
fi
if [[ "$API_HOST_PORT" == "$WEB_HOST_PORT" ]]; then
  echo "API_HOST_PORT and WEB_HOST_PORT must be different." >&2
  exit 1
fi
if ! curl -fsS --max-time 5 "http://127.0.0.1:$WEB_HOST_PORT" >/dev/null; then
  echo "The web application is not reachable on 127.0.0.1:$WEB_HOST_PORT." >&2
  exit 1
fi
if ! curl -fsS --max-time 5 "http://127.0.0.1:$API_HOST_PORT/api/ready" >/dev/null; then
  echo "The API is not reachable on 127.0.0.1:$API_HOST_PORT." >&2
  exit 1
fi

TEMP_HTTP="$(mktemp)"
TEMP_HTTPS="$(mktemp)"
cleanup() {
  rm -f "$TEMP_HTTP" "$TEMP_HTTPS"
}
trap cleanup EXIT

cat >"$TEMP_HTTP" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;

    access_log off;
    client_max_body_size 16m;

    location ^~ /api/ {
        proxy_pass http://127.0.0.1:$API_HOST_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_cache off;
        gzip off;
        add_header X-Accel-Buffering no always;
        proxy_read_timeout 3600s;
    }

    location ^~ /media/ {
        proxy_pass http://127.0.0.1:$API_HOST_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    location / {
        proxy_pass http://127.0.0.1:$WEB_HOST_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }
}
EOF

install -m 644 "$TEMP_HTTP" "$AVAILABLE"
ln -sfn "$AVAILABLE" "$ENABLED"
nginx -t
systemctl reload nginx

certbot certonly --nginx \
  --non-interactive \
  --agree-tos \
  --keep-until-expiring \
  --email "$ACME_EMAIL" \
  --domain "$DOMAIN"

cat >"$TEMP_HTTPS" <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name $DOMAIN;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name $DOMAIN;

    ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    access_log off;
    client_max_body_size 16m;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location ^~ /api/ {
        proxy_pass http://127.0.0.1:$API_HOST_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_cache off;
        gzip off;
        add_header X-Accel-Buffering no always;
        proxy_read_timeout 3600s;
    }

    location ^~ /media/ {
        proxy_pass http://127.0.0.1:$API_HOST_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }

    location / {
        proxy_pass http://127.0.0.1:$WEB_HOST_PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }
}
EOF

install -m 644 "$TEMP_HTTPS" "$AVAILABLE"
nginx -t
systemctl reload nginx
echo "Nginx is serving https://$DOMAIN from web :$WEB_HOST_PORT and streaming API :$API_HOST_PORT."
