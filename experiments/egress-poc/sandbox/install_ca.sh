#!/usr/bin/env bash
# Trust-store wiring for every HTTP runtime in the sandbox.
#
# This is the highest-risk file in the image build — silent partial trust
# (Python trusts our CA, Node doesn't) breaks the explicit-mode security
# story. Each step has an assertion afterwards.

set -euo pipefail

CA_SRC="/usr/local/share/ca-certificates/onyx-ca.crt"

if [[ ! -f "$CA_SRC" ]]; then
    echo "[install_ca] ERROR: $CA_SRC not present in build context."
    echo "[install_ca] Run ca/gen-ca.sh and copy ca/ca.crt to sandbox/ca.crt"
    echo "[install_ca] before docker build (the Makefile does this for you)."
    exit 1
fi

# 1. OS trust store (curl, git, wget, openssl, anything using openssl defaults).
echo "[install_ca] updating OS trust store"
update-ca-certificates
# Also publish under the same path env vars point to, so REQUESTS_CA_BUNDLE
# etc. all resolve to the same file regardless of runtime quirks.
cp "$CA_SRC" /etc/ssl/certs/onyx-ca.crt

# Verify openssl now trusts it via the system bundle.
openssl verify -CAfile /etc/ssl/certs/ca-certificates.crt "$CA_SRC" >/dev/null

# 2. Python certifi bundle (requests/httpx/urllib3/aiohttp use this regardless
#    of the system trust store).
echo "[install_ca] patching certifi bundle"
CERTIFI_PATH="$(python3 -c 'import certifi; print(certifi.where())')"
if [[ -z "$CERTIFI_PATH" || ! -f "$CERTIFI_PATH" ]]; then
    echo "[install_ca] ERROR: could not locate certifi bundle"
    exit 1
fi
# Idempotent: only append if our cert isn't already present.
if ! grep -q "Onyx Egress PoC TLS Inspection CA" "$CERTIFI_PATH"; then
    cat "$CA_SRC" >> "$CERTIFI_PATH"
fi

# Verify Python requests sees the trust anchor by parsing the bundle.
python3 - <<'PY'
import ssl
import certifi

ctx = ssl.create_default_context(cafile=certifi.where())
subjects = {ca["subject"] for ca in ctx.get_ca_certs()}
needle = "Onyx Egress PoC TLS Inspection CA"
if not any(needle in str(s) for s in subjects):
    raise SystemExit(f"certifi patch failed: {needle} not in trust store")
print("[install_ca] certifi patch verified")
PY

# 3. Node uses NODE_EXTRA_CA_CERTS env var at runtime; nothing to install at
#    build time. The env var is set by the entrypoint scripts and points to
#    /etc/ssl/certs/onyx-ca.crt.

# 4. Java is not installed in this image. If V1 needs Java workloads, add a
#    keytool import here.

echo "[install_ca] done"
