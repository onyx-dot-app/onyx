#!/usr/bin/env bash
# One-shot CA generator. Produces:
#   ca/ca.crt        — public cert (mounted into proxy + baked into sandbox image)
#   ca/ca.key.enc    — AES-256-CBC-encrypted RSA key (mounted into proxy)
#
# Idempotent: if ca.crt and ca.key.enc already exist, exits 0.
#
# Encryption: openssl enc -aes-256-cbc -pbkdf2 -iter 100000, key derived
# from ENCRYPTION_KEY_SECRET (env). The proxy decrypts with the same call.
# In V1 ENCRYPTION_KEY_SECRET comes from Onyx's secret manager.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [[ -f ca.crt && -f ca.key.enc ]]; then
    echo "[ca] ca.crt and ca.key.enc already present — skipping"
    exit 0
fi

ENCRYPTION_KEY_SECRET="${ENCRYPTION_KEY_SECRET:-poc-key-not-for-prod}"
export ENCRYPTION_KEY_SECRET

echo "[ca] generating 4096-bit RSA CA"
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
    -keyout ca.key \
    -out ca.crt \
    -subj "/O=Onyx/CN=Onyx Egress PoC TLS Inspection CA" \
    -addext "basicConstraints=critical,CA:TRUE" \
    -addext "keyUsage=critical,keyCertSign,cRLSign,digitalSignature" \
    2>/dev/null

echo "[ca] encrypting private key with AES-256-CBC + PBKDF2 (100k iters)"
openssl enc -aes-256-cbc -pbkdf2 -salt -iter 100000 \
    -in ca.key -out ca.key.enc \
    -pass env:ENCRYPTION_KEY_SECRET

# Discard raw key; only the encrypted version persists on disk.
rm -f ca.key

echo "[ca] done. ca.crt + ca.key.enc are in $DIR"
