#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ] || [ "$(uname -s)" != Linux ] || [ "$(id -u)" -ne 0 ]; then
  echo "Usage: sudo bash deployment/craft-runtime/check-rootfs.sh IMAGE [OUTPUT_DIR] (Linux, root)" >&2
  exit 2
fi
for tool in docker go openssl python3 mkfs.ext4 e2fsck debugfs sha256sum file tar; do
  command -v "$tool" >/dev/null
done
repo="$(cd "$(dirname "$0")/../.." && pwd)"
image="$1"
# The converter needs the daemon image store and loopback registry.
export BUILDX_BUILDER=default
checked_id="$(docker image inspect --format '{{.Id}}' "$image")"
work="$(mktemp -d)"
registry="" local_ref=""
cleanup() {
  result=$?
  if [ "$result" -ne 0 ]; then
    df -h "$work" >&2 || true
    df -i "$work" >&2 || true
    if [ -f "$work/rootfs/rootfs.ext4" ]; then
      debugfs -R stats "$work/rootfs/rootfs.ext4" >&2 || true
    fi
  fi
  if [ -n "$local_ref" ]; then docker image rm "$local_ref" >/dev/null 2>&1 || true; fi
  if [ -n "$registry" ]; then docker rm -fv "$registry" >/dev/null 2>&1 || true; fi
  rm -rf "$work"
  exit "$result"
}
trap cleanup EXIT

(
  cd "$repo/microvm"
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -buildvcs=false -trimpath -o "$work/guest-daemon" ./cmd/guest-daemon
  CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -buildvcs=false -trimpath -o "$work/egress-relay" ./cmd/egress-relay
)
old_umask="$(umask)"
umask 077
openssl req -x509 -newkey rsa:2048 -nodes -days 1 \
  -subj /CN=craft-runtime-rootfs-check \
  -addext basicConstraints=critical,CA:TRUE \
  -keyout "$work/ca.key" -out "$work/ca.crt" >/dev/null 2>&1
umask "$old_umask"
chmod 0644 "$work/ca.crt"

# The production builder requires a pulled image digest. Keep this check local.
registry="$(docker run --rm -d -p 127.0.0.1::5000 \
  "${BASE_IMAGE_REGISTRY:-docker.io}/library/registry:2")"
address="$(docker port "$registry" 5000/tcp)"
for attempt in {1..30}; do
  if docker exec "$registry" wget -q -O /dev/null http://127.0.0.1:5000/v2/; then break; fi
  if [ "$attempt" -eq 30 ]; then
    echo "Local registry did not become ready" >&2
    exit 1
  fi
  sleep 1
done
local_ref="${address}/craft-runtime:check"
docker tag "$checked_id" "$local_ref"
docker push "$local_ref" >/dev/null
bash "$repo/deployment/craft-fc/rootfs/build-rootfs.sh" \
  --image "$local_ref" --ca "$work/ca.crt" \
  --daemon-bin "$work/guest-daemon" --relay-bin "$work/egress-relay" \
  --out "$work/rootfs"

pinned="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["source_image"]["pinned"])' "$work/rootfs/manifest.json")"
if [ "$(docker image inspect --format '{{.Id}}' "$pinned")" != "$checked_id" ]; then
  echo "Rootfs source differs from the checked runtime image" >&2
  exit 1
fi
for name in guest-daemon egress-relay; do
  debugfs -R "dump /craft-fc/bin/$name $work/$name.extracted" "$work/rootfs/rootfs.ext4" >/dev/null 2>&1
  cmp "$work/$name" "$work/$name.extracted"
done
for item in usr/sbin/craft-init craft-fc/lib/attach craft-fc/etc/init.conf craft-fc/etc/guest.env; do
  destination="$work/$(basename "$item").extracted"
  debugfs -R "dump /$item $destination" "$work/rootfs/rootfs.ext4" >/dev/null 2>&1
  test -s "$destination"
done
cmp "$repo/deployment/craft-fc/rootfs/craft-init" "$work/craft-init.extracted"
cmp "$repo/deployment/craft-fc/rootfs/attach.sh" "$work/attach.extracted"
cmp "$repo/deployment/craft-fc/rootfs/init.conf" "$work/init.conf.extracted"

docker image inspect --format '{{json .Config.Env}}' "$checked_id" > "$work/source-env.json"
python3 - "$work/rootfs" "$local_ref" "$work/guest.env.extracted" "$work/source-env.json" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

environment = dict(line.split("=", 1) for line in Path(sys.argv[3]).read_text().splitlines()
                   if line and not line.startswith("#"))
source_environment = dict(entry.split("=", 1) for entry in json.loads(Path(sys.argv[4]).read_text()))
for name in ("PATH", "NODE_PATH", "AGENT_BROWSER_EXECUTABLE_PATH"):
    assert environment[name] == source_environment[name]
assert environment["HTTP_PROXY"] == "http://127.0.0.1:3128"
assert environment["HTTPS_PROXY"] == "http://127.0.0.1:3128"
assert environment["NODE_USE_ENV_PROXY"] == "1"
assert environment["NODE_EXTRA_CA_CERTS"] == "/etc/ssl/sandbox/ca-bundle.crt"
output = Path(sys.argv[1])
manifest = json.loads((output / "manifest.json").read_text())
assert manifest["schema"] == 1
assert manifest["kind"] == "craft-fc-rootfs"
source = manifest["source_image"]
assert source["ref"] == sys.argv[2]
assert source["pinned"].startswith(sys.argv[2].split(":check")[0] + "@sha256:")
assert source["digest"] == source["pinned"].split("@", 1)[1]
assert source["platform"] == "linux/amd64"
rootfs = output / "rootfs.ext4"
with rootfs.open("rb") as stream:
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(1 << 20), b""):
        digest.update(block)
assert manifest["output"]["file"] == rootfs.name
assert manifest["output"]["sha256"] == digest.hexdigest()
assert manifest["output"]["size_bytes"] == rootfs.stat().st_size
assert manifest["output"]["fs"] == "ext4"
guest = manifest["guest"]
assert guest["init"] == "/sbin/craft-init"
assert "init=/sbin/craft-init" in guest["boot_args"].split()
assert guest["template_boot_args_extra"] == "craft.scratch=defer"
assert guest["daemon"]["path"] == "/craft-fc/bin/guest-daemon"
assert guest["daemon"]["vsock_port"] == 52
assert guest["egress_relay"]["kind"] == "go"
assert guest["egress_relay"]["path"] == "/craft-fc/bin/egress-relay"
assert guest["egress"]["guest_proxy"] == "http://127.0.0.1:3128"
assert guest["egress"]["host_vsock_port"] == 3128
assert guest["drives"] == [
    {"drive_id": "rootfs", "guest_dev": "/dev/vda", "is_root_device": True, "is_read_only": True},
    {"drive_id": "scratch", "guest_dev": "/dev/vdb", "is_read_only": False, "fs": "ext4", "mount": "/mnt/scratch"},
    {"drive_id": "managed", "guest_dev": "/dev/vdc", "is_read_only": True, "fs": "ext4", "mount": "/workspace/managed"},
]
assert guest["managed_slots"] == {"a": "/dev/vdc", "b": "/dev/vdf"}
print("Rootfs integration check passed:", source["pinned"], digest.hexdigest())
PY

if [ "$#" -eq 2 ]; then
  mkdir -p "$2"
  cp --sparse=always "$work/rootfs/rootfs.ext4" "$work/rootfs/manifest.json" "$2/"
  cp "$work/egress-relay" "$2/egress-relay"
fi
