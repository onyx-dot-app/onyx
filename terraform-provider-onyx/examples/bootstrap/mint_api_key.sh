#!/usr/bin/env bash
# Mints an Onyx API key in the seeded "Admin" group and prints it.
#
# This is the scripted form of what the admin panel does under
# Settings -> Service Accounts. Use it for CI or a scripted first setup. A
# person setting up by hand can create the key in the panel instead.
#
# A key's access comes from its groups, so a key with no group is refused by
# every admin route. Listing groups needs the same Enterprise Edition route
# the admin panel uses.
#
# Usage:
#   ONYX_SERVER_URL=http://localhost:8080 \
#   ONYX_ADMIN_EMAIL=admin@example.com \
#   ONYX_ADMIN_PASSWORD='...' \
#   ./mint_api_key.sh
set -euo pipefail

server_url="${ONYX_SERVER_URL:-http://localhost:8080}"
email="${ONYX_ADMIN_EMAIL:-admin_user@example.com}"
password="${ONYX_ADMIN_PASSWORD:-TestPassword123!}"
key_name="${ONYX_API_KEY_NAME:-terraform}"

base="${server_url%/}"
if [ -n "${ONYX_API_PREFIX:-}" ]; then
  base="${base}/${ONYX_API_PREFIX#/}"
fi

for tool in curl jq; do
  command -v "$tool" > /dev/null 2>&1 || {
    echo "$tool is required" >&2
    exit 1
  }
done

cookie_jar="$(mktemp)"
trap 'rm -f "$cookie_jar"' EXIT

# Register. The first user on an empty deployment becomes admin. An existing
# account fails here, which is fine: the login below is the real gate.
curl -fsS -X POST "${base}/auth/register" \
  -H 'Content-Type: application/json' \
  -d "$(jq -cn --arg e "$email" --arg p "$password" \
    '{email: $e, username: $e, password: $p}')" \
  > /dev/null 2>&1 || true

if ! curl -fsS -X POST "${base}/auth/login" \
  -c "$cookie_jar" \
  --data-urlencode "username=${email}" \
  --data-urlencode "password=${password}" \
  > /dev/null; then
  echo "login as ${email} failed at ${base}" >&2
  exit 1
fi

# The seeded "Admin" group is hidden from the default listing.
admin_group_id="$(curl -fsS -b "$cookie_jar" \
  "${base}/manage/admin/user-group?include_default=true" \
  | jq -r '[.[] | select(.name == "Admin")][0].id // empty')"

if [ -z "$admin_group_id" ]; then
  echo "no seeded \"Admin\" group found at ${base}" >&2
  echo "the group listing route needs Enterprise Edition, same as the admin panel" >&2
  exit 1
fi

api_key="$(curl -fsS -X POST "${base}/admin/api-key" \
  -b "$cookie_jar" \
  -H 'Content-Type: application/json' \
  -d "$(jq -cn --arg n "$key_name" --argjson g "[$admin_group_id]" \
    '{name: $n, group_ids: $g}')" \
  | jq -r '.api_key // empty')"

if [ -z "$api_key" ]; then
  echo "API key creation did not return key material" >&2
  exit 1
fi

echo "$api_key"
