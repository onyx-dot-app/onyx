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
# The account credentials are required, deliberately. On a deployment with no
# users the register call below succeeds and the first user becomes an admin,
# so a default password here would quietly create a known-password
# administrator on any reachable deployment.
#
# Usage:
#   ONYX_SERVER_URL=http://localhost:8080 \
#   ONYX_ADMIN_EMAIL=admin@example.com \
#   ONYX_ADMIN_PASSWORD='...' \
#   ./mint_api_key.sh
set -euo pipefail

server_url="${ONYX_SERVER_URL:-http://localhost:8080}"
email="${ONYX_ADMIN_EMAIL:-}"
password="${ONYX_ADMIN_PASSWORD:-}"
key_name="${ONYX_API_KEY_NAME:-terraform}"

if [ -z "$email" ] || [ -z "$password" ]; then
  echo "set ONYX_ADMIN_EMAIL and ONYX_ADMIN_PASSWORD" >&2
  echo "they are required rather than defaulted: on a deployment with no users this script registers the account, and the first user becomes an admin" >&2
  exit 1
fi

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
register_body="$(mktemp)"
trap 'rm -f "$cookie_jar" "$register_body"' EXIT

# Register. The first user on an empty deployment becomes admin. An account that
# already exists answers 400 and is fine -- the login below is the real gate.
# Any other status is reported rather than swallowed, so a deployment problem
# does not resurface later as a confusing login failure.
register_code="$(curl -sS -o "$register_body" -w '%{http_code}' \
  -X POST "${base}/auth/register" \
  -H 'Content-Type: application/json' \
  -d "$(jq -cn --arg e "$email" --arg p "$password" \
    '{email: $e, username: $e, password: $p}')" 2> /dev/null || echo 000)"

case "$register_code" in
  2*| 400) ;;
  *)
    echo "warning: registering ${email} answered HTTP ${register_code}" >&2
    head -c 500 "$register_body" >&2
    echo >&2
    ;;
esac

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
