#!/bin/bash
# Startup wrapper that runs diagnostics before starting the API server
# This helps diagnose connection issues before the app crashes

set -e

echo "========================================================================"
echo "PRE-STARTUP DIAGNOSTICS"
echo "========================================================================"
echo ""

# Run diagnostics
python /app/scripts/diagnose_db_connection.py

echo ""
echo "========================================================================"
echo "DIAGNOSTICS COMPLETE - Press Ctrl+C now if you need to fix configuration"
echo "Starting API server in 10 seconds..."
echo "========================================================================"
sleep 10

echo ""
echo "Starting API server..."
exec "$@"
