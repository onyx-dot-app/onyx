#!/usr/bin/env bash
set -euo pipefail

echo "=== Building FOSS mirror ==="
mkdir -p /tmp/foss
git clone --mirror . /tmp/foss/.git
cd /tmp/foss

echo "=== Removing enterprise directory from history ==="
git filter-repo --path ee --invert-paths --force

echo "=== Checking out working tree ==="
git clone . ../foss_repo
cd ../foss_repo

echo "=== Applying MIT license ==="
cp ../LICENSE.mit LICENSE

echo "=== Done building FOSS repo ==="
