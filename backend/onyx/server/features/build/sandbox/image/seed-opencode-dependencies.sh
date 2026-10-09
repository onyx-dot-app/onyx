#!/bin/sh
# The caller holds the session seed lock until this script exits.
set -eu

session_path="${1:?Usage: seed-opencode-dependencies SESSION_PATH [TEMPLATE_PATH]}"
template="${2:-/workspace/templates/opencode}"
config_dir="$session_path/.opencode"

if [ ! -d "$template/node_modules" ] || [ -e "$config_dir/node_modules" ]; then
    exit 0
fi

mkdir -p "$config_dir"
staging="$(mktemp -d "$config_dir/.onyx-sdk.XXXXXX")"
trap 'rm -rf "$staging"' EXIT
trap 'exit 1' HUP INT TERM

cp -a "$template/node_modules" "$staging/"
for manifest in package.json package-lock.json; do
    if [ ! -e "$config_dir/$manifest" ]; then
        cp "$template/$manifest" "$staging/$manifest"
        mv "$staging/$manifest" "$config_dir/$manifest"
    fi
done
# Publish dependencies last, only after all copies completed.
mv "$staging/node_modules" "$config_dir/node_modules"
