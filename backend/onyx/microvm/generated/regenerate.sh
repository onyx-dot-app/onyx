#!/usr/bin/env bash
# Regenerate the host agent Python stubs from the Go module's proto.
#
# Usage: backend/onyx/microvm/generated/regenerate.sh [git-ref]
#   git-ref: a commit that has microvm/proto/hostagent/v1/hostagent.proto
#   (default HEAD).
#
# grpcio-tools 1.80.0 bundles protoc 31.1. Its Python gencode (protobuf 6.31)
# runs on the pinned protobuf 6.33 runtime; a newer protoc (for example the
# 36.x that the Go code uses) emits gencode that protobuf 6.x rejects.
set -euo pipefail

ref="${1:-HEAD}"
repo="$(git rev-parse --show-toplevel)"
commit="$(git -C "$repo" rev-parse --short=10 "$ref")"
blob="$(git -C "$repo" rev-parse "$ref:microvm/proto/hostagent/v1/hostagent.proto")"
out="$repo/backend"
pkg="onyx/microvm/generated/hostagent/v1"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/proto/$pkg"
git -C "$repo" show "$ref:microvm/proto/hostagent/v1/hostagent.proto" >"$tmp/proto/$pkg/hostagent.proto"

uv venv -q -p 3.13 "$tmp/venv"
uv pip install -q -p "$tmp/venv/bin/python" grpcio-tools==1.80.0

# The proto is placed at its Python package path so that the generated
# imports resolve as onyx.microvm.generated.hostagent.v1.
"$tmp/venv/bin/python" -m grpc_tools.protoc -I "$tmp/proto" \
  --python_out="$out" --pyi_out="$out" --grpc_python_out="$out" \
  "$tmp/proto/$pkg/hostagent.proto"

for f in "$out/$pkg"/hostagent_pb2.py "$out/$pkg"/hostagent_pb2.pyi "$out/$pkg"/hostagent_pb2_grpc.py; do
  {
    printf '# Generated from microvm/proto/hostagent/v1/hostagent.proto (blob %s)\n' "$blob"
    printf '# at commit %s by backend/onyx/microvm/generated/regenerate.sh. Do not edit.\n' "$commit"
    cat "$f"
  } >"$f.tmp"
  mv "$f.tmp" "$f"
done
echo "regenerated $pkg from $commit"
