#!/bin/sh
# Seed disposable SDK files without replacing session-owned dependencies.
set -eu

session_path="${1:?Usage: seed-opencode-dependencies SESSION_PATH}"
template=/workspace/templates/opencode
config_dir="$session_path/.opencode"

if [ ! -d "$template/node_modules" ] || [ -e "$config_dir/node_modules" ]; then
    exit 0
fi

mkdir -p "$config_dir"
cp -a "$template/node_modules" "$config_dir/"
for manifest in package.json package-lock.json; do
    if [ ! -e "$config_dir/$manifest" ]; then
        cp "$template/$manifest" "$config_dir/"
    fi
done
