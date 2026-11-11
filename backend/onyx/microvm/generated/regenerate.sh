#!/usr/bin/env bash
# Regenerate the host agent and guest daemon Python stubs from the Go
# module's protos.
#
# Usage: backend/onyx/microvm/generated/regenerate.sh [git-ref]
#   git-ref: a commit that has microvm/proto/{hostagent,sandboxd}/v1
#   (default HEAD).
#        backend/onyx/microvm/generated/regenerate.sh --check
#   Generate from the working-tree protos into a temporary directory and fail
#   if the committed stubs differ (the "at commit" header line is ignored).
#
# grpcio-tools 1.80.0 bundles protoc 31.1. Its Python gencode (protobuf 6.31)
# runs on the pinned protobuf 6.33 runtime; a newer protoc (for example the
# 36.x that the Go code uses) emits gencode that protobuf 6.x rejects.
set -euo pipefail

grpc_tools_version=1.80.0
check=0
if [[ "${1:-}" == "--check" ]]; then
  check=1
  shift
fi
ref="${1:-HEAD}"
repo="$(git rev-parse --show-toplevel)"
services=(hostagent sandboxd)

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

if ((check)); then
  commit="working-tree"
  out="$tmp/out"
else
  commit="$(git -C "$repo" rev-parse --short=10 "$ref")"
  out="$repo/backend"
fi

# The pre-commit hook runs in a venv that already has the pinned grpcio-tools.
if python3 -c "import importlib.metadata as m, sys; sys.exit(m.version('grpcio-tools') != '$grpc_tools_version')" 2>/dev/null; then
  py="python3"
else
  uv venv -q -p 3.13 "$tmp/venv"
  uv pip install -q -p "$tmp/venv/bin/python" "grpcio-tools==$grpc_tools_version"
  py="$tmp/venv/bin/python"
fi

for svc in "${services[@]}"; do
  src="microvm/proto/$svc/v1/$svc.proto"
  pkg="onyx/microvm/generated/$svc/v1"
  mkdir -p "$tmp/proto/$pkg" "$out/$pkg"
  if ((check)); then
    blob="$(git -C "$repo" hash-object "$repo/$src")"
    cp "$repo/$src" "$tmp/proto/$pkg/$svc.proto"
  else
    blob="$(git -C "$repo" rev-parse "$ref:$src")"
    git -C "$repo" show "$ref:$src" >"$tmp/proto/$pkg/$svc.proto"
  fi

  # The proto is placed at its Python package path so that the generated
  # imports resolve as onyx.microvm.generated.<svc>.v1.
  "$py" -m grpc_tools.protoc -I "$tmp/proto" \
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
  if ((!check)); then
    echo "regenerated $pkg from $commit"
  fi
done

if ((check)); then
  stale=0
  for svc in "${services[@]}"; do
    pkg="onyx/microvm/generated/$svc/v1"
    for name in "${svc}_pb2.py" "${svc}_pb2.pyi" "${svc}_pb2_grpc.py"; do
      committed="$repo/backend/$pkg/$name"
      if [[ ! -f "$committed" ]] || ! diff -q <(sed 2d "$out/$pkg/$name") <(sed 2d "$committed") >/dev/null; then
        echo "stale: backend/$pkg/$name" >&2
        stale=1
      fi
    done
  done
  if ((stale)); then
    echo "The Python stubs differ from microvm/proto. Commit the proto change, then run backend/onyx/microvm/generated/regenerate.sh." >&2
    exit 1
  fi
fi
