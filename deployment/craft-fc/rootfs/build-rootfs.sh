#!/usr/bin/env bash
# Converts the Craft sandbox image into a read-only ext4 root drive for
# Firecracker VMs, and writes manifest.json next to it.
#
# Usage (Linux, as root, with Docker):
#   build-rootfs.sh --image onyxdotapp/craft-runtime:v5.2.0 [--ca egress-ca.crt] \
#     --daemon-bin guest-daemon --relay-bin egress-relay [--daemon-cmd "<argv>"] \
#     [--registry PREFIX] [--out DIR]
#
#   --image       Sandbox image tag or digest. The build pins it to its digest.
#   --registry    Pull the image through this registry prefix (for example an
#                 ECR pull-through cache, <account>.dkr.ecr.<region>.amazonaws.com/docker-hub).
#   --ca          Optional. PEM certificate of the egress proxy CA (public
#                 certificate only). It goes into the trust stores. Without
#                 it, the drive has no CA and fits every deployment: the guest
#                 daemon installs the deployment CA at Init (ENG-4648).
#   --daemon-bin  Static guest daemon, installed at the --daemon-cmd program
#                 path. Required.
#   --daemon-cmd  Command line that craft-init supervises. Default:
#                 /craft-fc/bin/guest-daemon. The program must be /craft-fc/bin/<name>.
#   --relay-bin   Static egress relay (microvm/cmd/egress-relay), installed as
#                 /craft-fc/bin/egress-relay. Required, unless --python-relay.
#   --python-relay  Fallback: install egress-relay.py from this directory
#                 instead. Its interpreter is under the writable /usr overlay.
#   --out         Output directory. Default: ./out
#
# Host tools: Docker, GNU tar, e2fsprogs, OpenSSL, Python 3.9 or later.
#
# The sandbox image itself does not change. The pod runtime keeps using it.
# The build fetches zstd and xvfb with apt (network at build time only).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
image="" registry="" ca="" daemon_bin="" daemon_cmd="" relay_bin="" python_relay="" out="./out"
while [ $# -gt 0 ]; do
  case "$1" in
    --image) image=$2 ;;
    --registry) registry=${2%/} ;;
    --ca) ca=$2 ;;
    --daemon-bin) daemon_bin=$2 ;;
    --daemon-cmd) daemon_cmd=$2 ;;
    --relay-bin) relay_bin=$2 ;;
    --python-relay)
      python_relay=1
      shift
      continue
      ;;
    --out) out=$2 ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift 2
done
[ -n "${image}" ] && [ -n "${daemon_bin}" ] || {
  echo "usage: build-rootfs.sh --image IMAGE [--ca CA.pem] --daemon-bin F (--relay-bin F | --python-relay) [--daemon-cmd CMD] [--registry PREFIX] [--out DIR]" >&2
  exit 2
}
[ "$(id -u)" = 0 ] || {
  echo "run as root: the root tree keeps its owners" >&2
  exit 1
}
for tool in docker tar mkfs.ext4 e2fsck python3 openssl sha256sum file; do
  command -v "${tool}" >/dev/null || {
    echo "missing tool: ${tool}" >&2
    exit 1
  }
done

if [ -n "${relay_bin}" ] && [ -n "${python_relay}" ]; then
  echo "use --relay-bin or --python-relay, not both" >&2
  exit 2
fi
# Programs that init runs as root come from the read-only root with no
# interpreter and no shared library (those are under the /usr overlay).
require_static() {
  local info
  info=$(file -b "$1")
  case "${info}" in
    *x86-64*"statically linked"*) ;;
    *)
      echo "$1 is not a static x86-64 executable: ${info}" >&2
      exit 1
      ;;
  esac
}
require_static "${daemon_bin}"
# init.conf is sourced by bash and busybox sh: no quoting or expansion characters.
case "${daemon_cmd}" in
  *[\"\$\`\\\']* | *$'\n'*)
    echo "--daemon-cmd must not contain quotes, \$, \`, \\ or a newline" >&2
    exit 2
    ;;
esac
# The supervised program must be on the read-only root, outside every overlay.
# --daemon-bin is installed at this path.
daemon_path=${daemon_cmd%% *}
daemon_path=${daemon_path:-/craft-fc/bin/guest-daemon}
case "${daemon_path}" in
  /craft-fc/bin/busybox | /craft-fc/bin/egress-relay)
    echo "--daemon-cmd: ${daemon_path} is taken" >&2
    exit 2
    ;;
  /craft-fc/bin/ | /craft-fc/bin/. | /craft-fc/bin/.. | /craft-fc/bin/*[!A-Za-z0-9._-]*) ;;
  /craft-fc/bin/*) daemon_name_ok=1 ;;
esac
[ -n "${daemon_name_ok:-}" ] || {
  echo "--daemon-cmd: ${daemon_path} must be /craft-fc/bin/<name>" >&2
  exit 2
}
if [ -n "${relay_bin}" ]; then
  relay_kind=go
  require_static "${relay_bin}"
elif [ -n "${python_relay}" ]; then
  relay_kind=python
  relay_bin="${here}/egress-relay.py"
else
  echo "pass --relay-bin (the static egress relay) or --python-relay" >&2
  exit 2
fi

log() { echo "== $(date -u +%T) $*"; }

# The CA input must be one public certificate. Never a key.
ca_fingerprint="" ca_subject="" ca_not_after="" ca_install=runtime
if [ -n "${ca}" ]; then
  ca_install=build
  if grep -q 'PRIVATE KEY' "${ca}"; then
    echo "${ca} has a private key. Pass the public CA certificate only." >&2
    exit 1
  fi
  [ "$(grep -c 'BEGIN CERTIFICATE' "${ca}")" = 1 ] || {
    echo "${ca} must have exactly one certificate" >&2
    exit 1
  }
  # Capture first: grep -q can end the pipe early, and pipefail then fails it.
  ca_text=$(openssl x509 -in "${ca}" -noout -text)
  grep -q 'CA:TRUE' <<<"${ca_text}" || {
    echo "${ca} is not a CA certificate" >&2
    exit 1
  }
  ca_fingerprint=$(openssl x509 -in "${ca}" -noout -fingerprint -sha256 | cut -d= -f2)
  ca_subject=$(openssl x509 -in "${ca}" -noout -subject -nameopt RFC2253 | sed 's/^subject=//')
  ca_not_after=$(openssl x509 -in "${ca}" -noout -enddate | cut -d= -f2)
fi

mkdir -p "${out}"
out="$(cd "${out}" && pwd)"
work="$(mktemp -d)"
cid="" iid=""
cleanup() {
  [ -n "${cid}" ] && docker rm -f "${cid}" >/dev/null 2>&1
  [ -n "${iid}" ] && docker image rm "${iid}" >/dev/null 2>&1
  rm -rf "${work}"
}
trap cleanup EXIT

pull_ref=${image}
[ -n "${registry}" ] && pull_ref="${registry}/${image}"
log "pull ${pull_ref}"
docker pull --quiet --platform linux/amd64 "${pull_ref}" >/dev/null
pinned=$(docker image inspect --format '{{index .RepoDigests 0}}' "${pull_ref}")
digest=${pinned#*@}
log "pinned ${pinned}"

# guest.env: the image's ENV (docker export drops it) plus the proxy settings.
ctx="${work}/ctx"
mkdir -p "${ctx}"
bundle=/etc/ssl/sandbox/ca-bundle.crt
proxy=http://127.0.0.1:3128
no_proxy=localhost,127.0.0.1,::1
{
  echo "# Generated by build-rootfs.sh. craft-init passes these to the guest daemon."
  docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "${pinned}" |
    grep -v -E '^(HOME|HOSTNAME)=' | grep -v '^$'
  for k in HTTP_PROXY HTTPS_PROXY http_proxy https_proxy; do echo "${k}=${proxy}"; done
  echo "NO_PROXY=${no_proxy}"
  echo "no_proxy=${no_proxy}"
  echo "NODE_USE_ENV_PROXY=1"
  for k in SSL_CERT_FILE REQUESTS_CA_BUNDLE CURL_CA_BUNDLE PIP_CERT NODE_EXTRA_CA_CERTS GIT_SSL_CAINFO; do
    echo "${k}=${bundle}"
  done
} >"${ctx}/guest.env"

cp "${here}/craft-init" "${here}/attach.sh" "${here}/init.conf" "${ctx}/"
cp "${relay_bin}" "${ctx}/egress-relay"
# With --ca the CA goes into the stores now. Without it, the guest daemon adds
# the deployment CA at Init: the drive only gets the bundle link and an empty
# NSS database that the sandbox user owns.
if [ -n "${ca}" ]; then
  cp "${ca}" "${ctx}/egress-ca.crt"
  ca_steps='COPY egress-ca.crt /usr/local/share/ca-certificates/craft-egress-ca.crt
RUN update-ca-certificates'
  # shellcheck disable=SC2016 # ${db} is for the shell of the Dockerfile RUN.
  nss_add='&& certutil -d "sql:${db}" -A -t "C,," -n craft-egress-ca -i /usr/local/share/ca-certificates/craft-egress-ca.crt'
else
  ca_steps='# No egress CA: the guest daemon installs it at Init.'
  nss_add=''
fi
[ -n "${daemon_cmd}" ] && printf '\n# Set by build-rootfs.sh --daemon-cmd.\nDAEMON_CMD="%s"\n' "${daemon_cmd}" >>"${ctx}/init.conf"
cp "${daemon_bin}" "${ctx}/guest-daemon"

cat >"${ctx}/Dockerfile" <<EOF
FROM ${pinned}
USER root
SHELL ["/bin/bash", "-euo", "pipefail", "-c"]
# Pod-only parts: the iptables lockdown, its init script, the sidecar, gosu.
# busybox-static gives /craft-fc/bin/busybox: the static tools that init and
# attach run after the overlays exist. The package itself is removed again.
RUN apt-get update \\
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends zstd xvfb busybox-static \\
 && install -D -m 0755 -o root -g root /bin/busybox /craft-fc/bin/busybox \\
 && DEBIAN_FRONTEND=noninteractive apt-get purge -y --auto-remove iptables gosu busybox-static \\
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb \\
 && rm -f /workspace/firewall-init.sh /workspace/sidecar-entrypoint.sh
${ca_steps}
RUN install -d -m 0755 /etc/ssl/sandbox \\
 && ln -sf /etc/ssl/certs/ca-certificates.crt ${bundle} \\
 && db=/home/sandbox/.pki/nssdb && mkdir -p "\${db}" \\
 && { [ -f "\${db}/cert9.db" ] || certutil -d "sql:\${db}" -N --empty-password; } ${nss_add} \\
 && chown -R sandbox:sandbox /home/sandbox/.pki
COPY craft-init /sbin/craft-init
# /craft-fc: everything init starts. A top-level directory on the read-only
# root, outside every overlay (/sbin is a link into the /usr overlay here).
COPY attach.sh /craft-fc/lib/attach
COPY egress-relay /craft-fc/bin/egress-relay
COPY init.conf guest.env /craft-fc/etc/
COPY guest-daemon ${daemon_path}
RUN chown -R root:root /craft-fc \\
 && chmod 0755 /craft-fc /craft-fc/bin /craft-fc/lib /craft-fc/etc /sbin/craft-init /craft-fc/lib/attach /craft-fc/bin/egress-relay ${daemon_path} \\
 && chmod 0644 /craft-fc/etc/init.conf /craft-fc/etc/guest.env \\
 && printf 'Acquire::http::Proxy "${proxy}";\nAcquire::https::Proxy "${proxy}";\n' >/etc/apt/apt.conf.d/80craft-egress-proxy \\
 && printf 'while IFS= read -r l; do case "\$l" in ""|"#"*) ;; *=*) export "\$l" ;; esac; done < /craft-fc/etc/guest.env\n' >/etc/profile.d/craft-guest-env.sh \\
 && install -d -m 0755 -o root -g root /workspace/managed /mnt/scratch \\
 && dpkg-query -W libreoffice-writer zstd xvfb \\
 && for p in iptables gosu; do if dpkg -s "\$p" >/dev/null 2>&1; then echo "\$p is still installed"; exit 1; fi; done \\
 && [ ! -e /workspace/firewall-init.sh ] && [ ! -e /workspace/sidecar-entrypoint.sh ]
EOF

log "convert"
# No tag: two builds on one Docker host must not share an image name. Export,
# check and remove this build's own image ID.
docker build --quiet --platform linux/amd64 --iidfile "${work}/iid" "${ctx}" >/dev/null
iid=$(cat "${work}/iid")

log "export"
tree="${work}/tree"
mkdir -p "${tree}"
cid=$(docker create --platform linux/amd64 "${iid}")
docker export "${cid}" | tar -x -p --numeric-owner --xattrs --xattrs-include='*' -C "${tree}"
docker rm "${cid}" >/dev/null
cid=""

# Every program that init runs after attach must be static and in /craft-fc.
require_static "${tree}/craft-fc/bin/busybox"
[ -f "${tree}${daemon_path}" ] && [ -x "${tree}${daemon_path}" ] || {
  echo "--daemon-cmd: ${daemon_path} is not an executable file in the root tree" >&2
  exit 1
}
require_static "${tree}${daemon_path}"
# craft-init and attach run these busybox applets (nsenter and setpriv drop
# the relay's privileges). Without one, a service or attach fails at boot.
applets=$("${tree}/craft-fc/bin/busybox" --list)
for applet in nsenter setpriv env mv cp sleep stat mount blockdev cat grep rm mkdir chown chmod tr; do
  grep -qx "${applet}" <<<"${applets}" || {
    echo "${tree}/craft-fc/bin/busybox has no ${applet} applet; craft-init and attach need it" >&2
    exit 1
  }
done

# Docker fills these at run time. The VM has no DNS: all traffic goes through the proxy.
rm -f "${tree}/.dockerenv"
printf '127.0.0.1\tlocalhost sandbox\n::1\tlocalhost ip6-localhost ip6-loopback\n' >"${tree}/etc/hosts"
echo sandbox >"${tree}/etc/hostname"
echo "# No DNS in the VM. Programs use HTTP(S)_PROXY." >"${tree}/etc/resolv.conf"

# A PEM key block starts a line. Package caches and venvs hold upstream docs
# and test fixtures, not deployment secrets.
log "check for keys"
keys=$(grep -rlI --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=.bun --exclude-dir=.npm --exclude-dir=.cache \
  -e '^-----BEGIN [A-Z ]*PRIVATE KEY-----$' \
  "${tree}/etc" "${tree}/root" "${tree}/home" "${tree}/workspace" "${tree}/craft-fc" \
  "${tree}/usr/local/share/ca-certificates" 2>/dev/null || true)
if [ -n "${keys}" ]; then
  echo "private keys in the root tree:" >&2
  echo "${keys}" >&2
  exit 1
fi

log "ext4"
rootfs="${out}/rootfs.ext4"
size_mib=$(($(du -sm "${tree}" | cut -f1) * 115 / 100 + 256))
rm -f "${rootfs}"
truncate -s "${size_mib}M" "${rootfs}"
# No journal: the drive is always read-only.
mkfs.ext4 -q -F -L craft-root -O ^has_journal -m 0 -d "${tree}" "${rootfs}"
e2fsck -fn "${rootfs}" >/dev/null

log "manifest"
# shellcheck disable=SC2016 # dpkg-query expands the format, not the shell.
pkgs() { docker run --rm --platform linux/amd64 --entrypoint dpkg-query "$1" -W -f '${Package}=${Version}\n'; }
pkgs "${pinned}" | sort >"${work}/pkgs-before"
pkgs "${iid}" | sort >"${work}/pkgs-after"
docker image rm "${iid}" >/dev/null
iid=""

onyx_commit=$(git -C "${here}" rev-parse HEAD 2>/dev/null || echo unknown)
export MF_IMAGE="${image}" MF_PULL_REF="${pull_ref}" MF_PINNED="${pinned}" MF_DIGEST="${digest}" MF_ROOTFS="${rootfs}" \
  MF_CA_FP="${ca_fingerprint}" MF_CA_SUBJECT="${ca_subject}" MF_CA_NOT_AFTER="${ca_not_after}" MF_CA_INSTALL="${ca_install}" \
  MF_DAEMON_CMD="${daemon_cmd:-/craft-fc/bin/guest-daemon}" MF_DAEMON_PATH="${daemon_path}" MF_HERE="${here}" MF_WORK="${work}" \
  MF_TREE="${tree}" MF_COMMIT="${onyx_commit}" MF_BUNDLE="${bundle}" MF_PROXY="${proxy}" \
  MF_RELAY_KIND="${relay_kind}"
python3 - "${out}/manifest.json" <<'PY'
from __future__ import annotations  # Python 3.9 (AL2023 python3)

import datetime
import hashlib
import json
import os
import subprocess
import sys

e = os.environ


def sha256(path: str) -> str | None:
    if not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def pkgs(name: str) -> dict[str, str]:
    with open(os.path.join(e["MF_WORK"], name)) as f:
        return dict(line.strip().split("=", 1) for line in f if "=" in line)


before, after = pkgs("pkgs-before"), pkgs("pkgs-after")
tree = e["MF_TREE"]
uuid = subprocess.run(
    ["blkid", "-s", "UUID", "-o", "value", e["MF_ROOTFS"]], capture_output=True, text=True
).stdout.strip()
manifest = {
    "schema": 1,
    "kind": "craft-fc-rootfs",
    "built_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "source_image": {
        "ref": e["MF_IMAGE"],
        "pulled_from": e["MF_PULL_REF"],
        "pinned": e["MF_PINNED"],
        "digest": e["MF_DIGEST"],
        "platform": "linux/amd64",
    },
    "build_inputs": {
        "onyx_commit": e["MF_COMMIT"],
        "files_sha256": {
            n: sha256(os.path.join(e["MF_HERE"], n))
            for n in ("build-rootfs.sh", "craft-init", "attach.sh", "egress-relay.py", "init.conf")
        },
        # None: no CA in the drive; the guest daemon installs it at Init.
        "egress_ca": {
            "sha256_fingerprint": e["MF_CA_FP"],
            "subject": e["MF_CA_SUBJECT"],
            "not_after": e["MF_CA_NOT_AFTER"],
        }
        if e["MF_CA_INSTALL"] == "build"
        else None,
        "packages_added": {k: v for k, v in after.items() if k not in before},
        "packages_removed": sorted(k for k in before if k not in after),
        "packages_changed": {k: [before[k], after[k]] for k in after if k in before and before[k] != after[k]},
        "files_removed": ["/workspace/firewall-init.sh", "/workspace/sidecar-entrypoint.sh"],
    },
    "guest": {
        "init": "/sbin/craft-init",
        "boot_args": "console=ttyS0 reboot=k panic=1 pci=off init=/sbin/craft-init",
        "template_boot_args_extra": "craft.scratch=defer",
        "supervised_dir": "/craft-fc",
        "attach": {"path": "/craft-fc/lib/attach", "sha256": sha256(os.path.join(tree, "craft-fc/lib/attach"))},
        "busybox": {"path": "/craft-fc/bin/busybox", "sha256": sha256(os.path.join(tree, "craft-fc/bin/busybox"))},
        "daemon": {
            "cmd": e["MF_DAEMON_CMD"],
            "path": e["MF_DAEMON_PATH"],
            "sha256": sha256(os.path.join(tree, e["MF_DAEMON_PATH"].lstrip("/"))),
            "vsock_port": 52,
        },
        "egress_relay": {
            "kind": e["MF_RELAY_KIND"],
            "path": "/craft-fc/bin/egress-relay",
            "sha256": sha256(os.path.join(tree, "craft-fc/bin/egress-relay")),
            "pidfile": "/run/craft-fc/egress-relay.pid",
            "user": 65534,
        },
        "config": {"init_conf": "/craft-fc/etc/init.conf", "env": "/craft-fc/etc/guest.env"},
        "egress": {
            "guest_proxy": e["MF_PROXY"],
            "host_vsock_port": 3128,
            "ca_bundle": e["MF_BUNDLE"],
            "ca_install": e["MF_CA_INSTALL"],
        },
        "drives": [
            {"drive_id": "rootfs", "guest_dev": "/dev/vda", "is_root_device": True, "is_read_only": True},
            {"drive_id": "scratch", "guest_dev": "/dev/vdb", "is_read_only": False, "fs": "ext4", "mount": "/mnt/scratch"},
            {"drive_id": "managed", "guest_dev": "/dev/vdc", "is_read_only": True, "fs": "ext4", "mount": "/workspace/managed"},
        ],
        # attach mounts slot A. B is optional, the last drive, and stays
        # unmounted until a skills update (MANAGED_DEV_B in init.conf).
        "managed_slots": {"a": "/dev/vdc", "b": "/dev/vdf"},
        "overlay_dirs": ["/etc", "/home", "/root", "/opt", "/srv", "/usr", "/var", "/workspace"],
        "scratch_layout_version": 1,
    },
    "output": {
        "file": os.path.basename(e["MF_ROOTFS"]),
        "sha256": sha256(e["MF_ROOTFS"]),
        "size_bytes": os.path.getsize(e["MF_ROOTFS"]),
        "fs": "ext4",
        "fs_uuid": uuid,
        "fs_label": "craft-root",
    },
}
with open(sys.argv[1], "w") as f:
    json.dump(manifest, f, indent=2)
    f.write("\n")
PY
log "done: ${rootfs} ($(du -m --apparent-size "${rootfs}" | cut -f1) MiB), ${out}/manifest.json"
