#!/usr/bin/env bash
# Builds the files the docs do not commit: SVGs rendered from web/lib/opal
# and the public OpenAPI spec. Run before `mint dev`, `mint validate`, or a publish.
# Usage: documentation/scripts/generate.sh [--check]
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
DOCS="$ROOT/documentation"
PYTHON="${PYTHON:-python}"

cd "$ROOT/web"
if [[ ! -f lib/opal/dist/root.css ]]; then
  bun run --cwd lib/shared build:tokens
  bun lib/opal/scripts/bundle-css.mjs
fi
bun lib/opal/scripts/export-svgs.tsx "$DOCS/scripts/generated_assets.json" "$DOCS" "$@"

[[ "${1:-}" == "--check" ]] && exit 0
cd "$ROOT/backend"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
PYTHONPATH=. "$PYTHON" scripts/onyx_openapi_schema.py --filename "$tmp/openapi.json" --tagged-for-docs "$tmp/tagged.json"
"$PYTHON" scripts/transform_openapi_for_docs.py -i "$tmp/tagged.json" -o "$DOCS/developers/api_reference/openapi.json"
