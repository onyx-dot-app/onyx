#!/usr/bin/env bash
# Regenerate the host agent and guest daemon Python stubs from the Go
# module's protos.
#
# Usage: backend/onyx/microvm/generated/regenerate.sh [git-ref]
#   git-ref: a commit that has microvm/proto/{hostagent,sandboxd}/v1
#   (default HEAD).
#
# grpcio-tools 1.80.0 bundles protoc 31.1. Its Python gencode (protobuf 6.31)
# runs on the pinned protobuf 6.33 runtime; a newer protoc (for example the
# 36.x that the Go code uses) emits gencode that protobuf 6.x rejects.
set -euo pipefail

ref="${1:-HEAD}"
repo="$(git rev-parse --show-toplevel)"
commit="$(git -C "$repo" rev-parse --short=10 "$ref")"
out="$repo/backend"
services=(hostagent sandboxd)

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

uv venv -q -p 3.13 "$tmp/venv"
uv pip install -q -p "$tmp/venv/bin/python" grpcio-tools==1.80.0

for svc in "${services[@]}"; do
  src="microvm/proto/$svc/v1/$svc.proto"
  pkg="onyx/microvm/generated/$svc/v1"
  blob="$(git -C "$repo" rev-parse "$ref:$src")"
  mkdir -p "$tmp/proto/$pkg" "$out/$pkg"
  git -C "$repo" show "$ref:$src" >"$tmp/proto/$pkg/$svc.proto"

  # The proto is placed at its Python package path so that the generated
  # imports resolve as onyx.microvm.generated.<svc>.v1.
  "$tmp/venv/bin/python" -m grpc_tools.protoc -I "$tmp/proto" \
    --python_out="$out" --pyi_out="$out" --grpc_python_out="$out" \
    "$tmp/proto/$pkg/$svc.proto"

  touch "$out/onyx/microvm/generated/$svc/__init__.py" "$out/$pkg/__init__.py"
  for f in "$out/$pkg/${svc}_pb2.py" "$out/$pkg/${svc}_pb2.pyi" "$out/$pkg/${svc}_pb2_grpc.py"; do
    {
      printf '# Generated from %s (blob %s)\n' "$src" "$blob"
      printf '# at commit %s by backend/onyx/microvm/generated/regenerate.sh. Do not edit.\n' "$commit"
      cat "$f"
    } >"$f.tmp"
    mv "$f.tmp" "$f"
  done
  echo "regenerated $pkg from $commit"
done
