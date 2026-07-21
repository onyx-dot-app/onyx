#!/bin/sh
# Reads the rotating RDS credential JSON file mounted by the Secrets Store CSI driver,
# exports POSTGRES_* env vars, then execs the original command.
# Falls back gracefully if the file is absent (local dev without the CSI driver).
DB_CREDS_FILE="${DB_CREDS_FILE:-/mnt/secrets-store/db-creds.json}"
if [ -f "$DB_CREDS_FILE" ]; then
    export POSTGRES_HOST=$(python3 -c "import json; d=json.load(open('$DB_CREDS_FILE')); print(d['host'])")
    export POSTGRES_USER=$(python3 -c "import json; d=json.load(open('$DB_CREDS_FILE')); print(d['username'])")
    export POSTGRES_PASSWORD=$(python3 -c "import json; d=json.load(open('$DB_CREDS_FILE')); print(d['password'])")
    export POSTGRES_PORT=$(python3 -c "import json; d=json.load(open('$DB_CREDS_FILE')); print(str(d['port']))")
    export POSTGRES_DB=$(python3 -c "import json; d=json.load(open('$DB_CREDS_FILE')); print(d['dbname'])")
fi

DB_READONLY_CREDS_FILE="${DB_READONLY_CREDS_FILE:-/mnt/secrets-store/db-readonly-creds.json}"
if [ -f "$DB_READONLY_CREDS_FILE" ]; then
    export DB_READONLY_USER=$(python3 -c "import json; d=json.load(open('$DB_READONLY_CREDS_FILE')); print(d['username'])")
    export DB_READONLY_PASSWORD=$(python3 -c "import json; d=json.load(open('$DB_READONLY_CREDS_FILE')); print(d['password'])")
fi
exec "$@"
