#!/usr/bin/env bash
#
# Seed IndexAttemptError records for local testing of the Index Attempt Errors Modal.
#
# Usage:
#   ./seed_index_attempt_errors.sh [--cc-pair-id <ID>] [--count <N>] [--clean]
#
# Options:
#   --cc-pair-id <ID>   Use an existing CC pair (skips connector creation)
#   --count <N>         Number of unresolved errors to insert (default: 7)
#   --clean             Remove ALL test-seeded errors (those with failure_message LIKE 'SEED:%') and exit
#
# Without --cc-pair-id, the script creates a file connector via the API
# and prints its CC pair ID so you can navigate to /admin/connector/<ID>.
#
# Prerequisites:
#   - Onyx services running (docker compose up)
#   - curl and jq installed

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:3000}"
ADMIN_EMAIL="${ADMIN_EMAIL:-admin_user@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-TestPassword123!}"
DB_CONTAINER="${DB_CONTAINER:-onyx-relational_db-1}"
CC_PAIR_ID=""
ERROR_COUNT=7
CLEAN=false

# --- Parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cc-pair-id) CC_PAIR_ID="$2"; shift 2 ;;
    --count)      ERROR_COUNT="$2"; shift 2 ;;
    --clean)      CLEAN=true; shift ;;
    *)            echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# --- Helper: run psql ---
psql_exec() {
  docker exec "$DB_CONTAINER" psql -U postgres -qtAX -c "$1"
}

# --- Clean mode ---
if $CLEAN; then
  deleted=$(psql_exec "DELETE FROM index_attempt_errors WHERE failure_message LIKE 'SEED:%' RETURNING id;" | wc -l)
  echo "Deleted $deleted seeded error(s)."
  exit 0
fi

# --- Authenticate and get session cookie ---
COOKIE_JAR=$(mktemp)
trap 'rm -f "$COOKIE_JAR"' EXIT

echo "Authenticating as $ADMIN_EMAIL..."
login_resp=$(curl -s -o /dev/null -w "%{http_code}" \
  -c "$COOKIE_JAR" \
  -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=${ADMIN_EMAIL}&password=${ADMIN_PASSWORD}")

if [[ "$login_resp" != "200" && "$login_resp" != "204" && "$login_resp" != "302" ]]; then
  echo "Login failed (HTTP $login_resp). Check credentials." >&2
  # Try the simpler a@example.com / a creds as fallback
  echo "Retrying with a@example.com / a..."
  ADMIN_EMAIL="a@example.com"
  ADMIN_PASSWORD="a"
  login_resp=$(curl -s -o /dev/null -w "%{http_code}" \
    -c "$COOKIE_JAR" \
    -X POST "$BASE_URL/api/auth/login" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "username=${ADMIN_EMAIL}&password=${ADMIN_PASSWORD}")
  if [[ "$login_resp" != "200" && "$login_resp" != "204" && "$login_resp" != "302" ]]; then
    echo "Login failed again (HTTP $login_resp)." >&2
    exit 1
  fi
fi
echo "Authenticated."

# --- Create a file connector if no CC pair specified ---
if [[ -z "$CC_PAIR_ID" ]]; then
  echo "Creating file connector..."
  create_resp=$(curl -s -b "$COOKIE_JAR" \
    -X POST "$BASE_URL/api/manage/admin/connector-with-mock-credential" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "Seed Errors Test Connector",
      "source": "file",
      "input_type": "load_state",
      "connector_specific_config": {"file_locations": []},
      "refresh_freq": null,
      "prune_freq": null,
      "indexing_start": null,
      "access_type": "public",
      "groups": []
    }')

  CC_PAIR_ID=$(echo "$create_resp" | jq -r '.data // empty')
  if [[ -z "$CC_PAIR_ID" ]]; then
    echo "Failed to create connector: $create_resp" >&2
    exit 1
  fi
  echo "Created CC pair ID: $CC_PAIR_ID"
else
  echo "Using existing CC pair ID: $CC_PAIR_ID"
fi

# --- Find or create an index attempt for this CC pair ---
ATTEMPT_ID=$(psql_exec "
  SELECT id FROM index_attempt
  WHERE connector_credential_pair_id = $CC_PAIR_ID
  ORDER BY id DESC LIMIT 1;
")

if [[ -z "$ATTEMPT_ID" ]]; then
  echo "No index attempt found. Creating one..."
  SEARCH_SETTINGS_ID=$(psql_exec "SELECT id FROM search_settings ORDER BY id DESC LIMIT 1;")
  if [[ -z "$SEARCH_SETTINGS_ID" ]]; then
    echo "No search_settings found in DB." >&2
    exit 1
  fi
  ATTEMPT_ID=$(psql_exec "
    INSERT INTO index_attempt (connector_credential_pair_id, search_settings_id, from_beginning, status, new_docs_indexed, total_docs_indexed, docs_removed_from_index, time_updated, completed_batches, total_chunks)
    VALUES ($CC_PAIR_ID, $SEARCH_SETTINGS_ID, true, 'completed_with_errors', 5, 10, 0, now(), 0, 0)
    RETURNING id;
  ")
  echo "Created index attempt ID: $ATTEMPT_ID"
else
  echo "Using existing index attempt ID: $ATTEMPT_ID"
fi

# --- Insert the curated test errors ---
echo "Inserting test errors..."

# Error 1: Document with link (hyperlinked doc ID)
psql_exec "
INSERT INTO index_attempt_errors (index_attempt_id, connector_credential_pair_id, document_id, document_link, entity_id, failure_message, is_resolved)
VALUES ($ATTEMPT_ID, $CC_PAIR_ID, 'doc-001', 'https://example.com/doc-001', NULL, 'SEED: Timeout while fetching document content from remote server', false);
"

# Error 2: Document without link (plain text doc ID)
psql_exec "
INSERT INTO index_attempt_errors (index_attempt_id, connector_credential_pair_id, document_id, document_link, entity_id, failure_message, is_resolved)
VALUES ($ATTEMPT_ID, $CC_PAIR_ID, 'doc-no-link', NULL, NULL, 'SEED: Permission denied accessing resource - authentication token expired', false);
"

# Error 3: Entity ID only (no document_id, no link)
psql_exec "
INSERT INTO index_attempt_errors (index_attempt_id, connector_credential_pair_id, document_id, document_link, entity_id, failure_message, is_resolved)
VALUES ($ATTEMPT_ID, $CC_PAIR_ID, NULL, NULL, 'entity-abc', 'SEED: Entity sync failed due to upstream rate limiting', false);
"

# Error 4: Entity ID with link (hyperlinked entity)
psql_exec "
INSERT INTO index_attempt_errors (index_attempt_id, connector_credential_pair_id, document_id, document_link, entity_id, failure_message, is_resolved)
VALUES ($ATTEMPT_ID, $CC_PAIR_ID, NULL, 'https://example.com/entity', 'entity-link-test', 'SEED: Connection reset by peer during entity fetch', false);
"

# Error 5: Neither document_id nor entity_id (renders "Unknown")
psql_exec "
INSERT INTO index_attempt_errors (index_attempt_id, connector_credential_pair_id, document_id, document_link, entity_id, failure_message, is_resolved)
VALUES ($ATTEMPT_ID, $CC_PAIR_ID, NULL, NULL, NULL, 'SEED: Unknown document failed with a catastrophic internal error that produced a very long error message designed to test the scrollable cell behavior in the modal UI. This message continues for quite a while to ensure the 60px height overflow-y-auto container is properly exercised during manual testing.', false);
"

# Error 6: XSS test (special HTML characters)
psql_exec "
INSERT INTO index_attempt_errors (index_attempt_id, connector_credential_pair_id, document_id, document_link, entity_id, failure_message, is_resolved)
VALUES ($ATTEMPT_ID, $CC_PAIR_ID, 'doc-xss', NULL, NULL, 'SEED: <script>alert(''xss'')</script>', false);
"

# Error 7: Single-character error message
psql_exec "
INSERT INTO index_attempt_errors (index_attempt_id, connector_credential_pair_id, document_id, document_link, entity_id, failure_message, is_resolved)
VALUES ($ATTEMPT_ID, $CC_PAIR_ID, 'doc-short', NULL, NULL, 'SEED: X', false);
"

# Insert additional generic errors if --count > 7
if (( ERROR_COUNT > 7 )); then
  extra=$(( ERROR_COUNT - 7 ))
  echo "Inserting $extra additional generic errors..."
  for i in $(seq 1 "$extra"); do
    psql_exec "
    INSERT INTO index_attempt_errors (index_attempt_id, connector_credential_pair_id, document_id, document_link, entity_id, failure_message, is_resolved)
    VALUES ($ATTEMPT_ID, $CC_PAIR_ID, 'doc-extra-$i', NULL, NULL, 'SEED: Generic error #$i for pagination testing', false);
    "
  done
fi

# Error: One resolved error (to test filtering)
psql_exec "
INSERT INTO index_attempt_errors (index_attempt_id, connector_credential_pair_id, document_id, document_link, entity_id, failure_message, is_resolved)
VALUES ($ATTEMPT_ID, $CC_PAIR_ID, 'doc-resolved', NULL, NULL, 'SEED: This error was already resolved', true);
"

# --- Verify ---
total=$(psql_exec "SELECT count(*) FROM index_attempt_errors WHERE connector_credential_pair_id = $CC_PAIR_ID AND failure_message LIKE 'SEED:%';")
unresolved=$(psql_exec "SELECT count(*) FROM index_attempt_errors WHERE connector_credential_pair_id = $CC_PAIR_ID AND failure_message LIKE 'SEED:%' AND is_resolved = false;")

echo ""
echo "=== Done ==="
echo "CC Pair ID:        $CC_PAIR_ID"
echo "Index Attempt ID:  $ATTEMPT_ID"
echo "Seeded errors:     $total ($unresolved unresolved, $(( total - unresolved )) resolved)"
echo ""
echo "View in browser:   $BASE_URL/admin/connector/$CC_PAIR_ID"
echo "API check:         curl -b <cookies> '$BASE_URL/api/manage/admin/cc-pair/$CC_PAIR_ID/errors'"
echo ""
echo "To clean up:       $0 --clean"
echo "To delete connector: curl -b <cookies> -X DELETE '$BASE_URL/api/manage/admin/cc-pair/$CC_PAIR_ID'"
