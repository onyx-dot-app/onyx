#!/usr/bin/env bash
#
# Verify crds/cnpg-crds.yaml is in sync with the CNPG subchart.
#
# The CNPG subchart ships CRDs in templates/crds/ (not Helm's crds/), which
# breaks build-phase validation for our Cluster CR. We copy them into our
# chart's crds/ directory so Helm pre-installs them. This script detects
# drift after a subchart version bump.
#
# Run from repo root or chart directory. Exits non-zero if out of sync.

set -euo pipefail

CHART_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CRDS_FILE="$CHART_DIR/crds/cnpg-crds.yaml"
SUBCHART_TARBALL="$(find "$CHART_DIR/charts" -maxdepth 1 -name 'cloudnative-pg-*.tgz' -print -quit 2>/dev/null)"

if [[ -z "$SUBCHART_TARBALL" ]]; then
  echo "CNPG subchart tarball not found in $CHART_DIR/charts/. Run 'helm dependency update' first." >&2
  exit 1
fi

EXPECTED=$(tar -xzOf "$SUBCHART_TARBALL" cloudnative-pg/templates/crds/crds.yaml | sed -e '1{/^{{/d;}' -e '${/^{{/d;}')

if [[ ! -f "$CRDS_FILE" ]]; then
  echo "crds/cnpg-crds.yaml does not exist. Copy it:" >&2
  echo "  tar -xzOf $SUBCHART_TARBALL cloudnative-pg/templates/crds/crds.yaml | sed '1{/^{{-/d}; \$d' > $CRDS_FILE" >&2
  exit 1
fi

ACTUAL=$(cat "$CRDS_FILE")

if [[ "$EXPECTED" != "$ACTUAL" ]]; then
  echo "crds/cnpg-crds.yaml is out of sync with $(basename "$SUBCHART_TARBALL")." >&2
  echo "Re-copy:" >&2
  echo "  tar -xzOf $SUBCHART_TARBALL cloudnative-pg/templates/crds/crds.yaml | sed '1{/^{{-/d}; \$d' > $CRDS_FILE" >&2
  exit 1
fi

echo "crds/cnpg-crds.yaml is in sync with $(basename "$SUBCHART_TARBALL")."
