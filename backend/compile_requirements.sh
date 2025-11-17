#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

echo "Locking dependencies from pyproject.toml..."
uv lock

echo ""
echo "Exporting requirements files from uv.lock..."
uv export --no-hashes --extra backend -o requirements/default.txt
uv export --no-hashes --extra backend --extra dev -o requirements/dev.txt
uv export --no-hashes --extra backend --extra ee -o requirements/ee.txt
uv export --no-hashes --extra model_server -o requirements/model_server.txt
uv export --no-hashes --all-extras -o requirements/combined.txt

echo ""
echo "✓ All files updated successfully!"
echo ""
echo "To install:"
echo "  uv sync --extra backend       # shared + backend"
echo "  uv sync --extra model_server  # shared + model_server (no backend deps!)"
echo "  uv sync --extra backend --extra dev  # backend + dev tools"

