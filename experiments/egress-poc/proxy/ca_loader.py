"""Load the Onyx CA on proxy startup.

The CA key on disk is AES-256-CBC-encrypted (PBKDF2-derived from
ENCRYPTION_KEY_SECRET); the proxy decrypts via the openssl CLI and writes
the combined PEM to mitmproxy's confdir.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("egress-poc.proxy")


def prepare_ca_file(confdir: str) -> None:
    ca_cert_path = Path(os.getenv("CA_CERT_PATH", "/ca/ca.crt"))
    ca_key_enc_path = Path(os.getenv("CA_KEY_PATH", "/ca/ca.key.enc"))
    if "ENCRYPTION_KEY_SECRET" not in os.environ:
        raise RuntimeError("ENCRYPTION_KEY_SECRET must be set to decrypt CA key")

    result = subprocess.run(
        [
            "openssl",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-iter",
            "100000",
            "-in",
            str(ca_key_enc_path),
            "-pass",
            "env:ENCRYPTION_KEY_SECRET",
        ],
        check=True,
        capture_output=True,
    )
    key_pem = result.stdout
    cert_pem = ca_cert_path.read_bytes()

    confdir_path = Path(confdir)
    confdir_path.mkdir(parents=True, exist_ok=True)

    # mitmproxy expects the combined PEM (key followed by cert).
    combined = confdir_path / "mitmproxy-ca.pem"
    combined.write_bytes(key_pem + b"\n" + cert_pem)
    combined.chmod(0o600)

    (confdir_path / "mitmproxy-ca-cert.pem").write_bytes(cert_pem)

    log.info("CA loaded from %s into %s", ca_cert_path, confdir)
