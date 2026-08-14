#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${NOVEGAME_ENV_FILE:-/etc/novegame/novegame.env}"
EMAIL="${1:-}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this command with sudo." >&2
  exit 1
fi
if [[ -z "$EMAIL" ]]; then
  echo "Usage: sudo bash scripts/promote-admin.sh your@email.com" >&2
  exit 1
fi

COMPOSE=(docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/compose.prod.yaml")
ADMIN_ID="$(cat /proc/sys/kernel/random/uuid)"
REVIEWER_ID="$(cat /proc/sys/kernel/random/uuid)"

"${COMPOSE[@]}" exec -T postgres psql -U narrative -d narrative \
  -v email="$EMAIL" -v admin_id="$ADMIN_ID" -v reviewer_id="$REVIEWER_ID" <<'SQL'
\set ON_ERROR_STOP on

SELECT EXISTS (
  SELECT 1 FROM users WHERE email = :'email' AND email_verified_at IS NOT NULL
) AS verified_user
\gset

\if :verified_user
\else
  \echo 'Verified user not found. Register and verify the email before granting admin access.'
  \quit 3
\endif

INSERT INTO user_roles (id, user_id, role, created_at)
SELECT :'admin_id', id, 'admin', now() FROM users WHERE email = :'email'
ON CONFLICT (user_id, role) DO NOTHING;

INSERT INTO user_roles (id, user_id, role, created_at)
SELECT :'reviewer_id', id, 'reviewer', now() FROM users WHERE email = :'email'
ON CONFLICT (user_id, role) DO NOTHING;

SELECT u.email, string_agg(r.role, ', ' ORDER BY r.role) AS roles
FROM users u JOIN user_roles r ON r.user_id = u.id
WHERE u.email = :'email'
GROUP BY u.email;
SQL

echo "Administrator access granted. Sign in again and enroll MFA before using admin actions."
