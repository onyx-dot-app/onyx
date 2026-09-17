"""Assemble the outbound-TLS trust store for the model server.

Every other Onyx pod merges operator-supplied CA roots into the system trust
store with a shell `update-ca-certificates` wrapper. The model server runs on a
distroless image with no shell, so when custom roots are mounted this module
reproduces that merge in pure Python: it concatenates certifi's public roots with
the mounted roots into a single bundle and points `REQUESTS_CA_BUNDLE` /
`SSL_CERT_FILE` at it. Keeping custom roots *additive* to the public roots (rather
than replacing them) preserves TLS to public endpoints -- e.g. HuggingFace model
downloads -- for operators who add only a private root.

A no-op unless `ONYX_CUSTOM_CA_CERTS_DIR` is set, so default deployments are
unaffected and keep verifying against certifi directly.
"""

import os
import tempfile
from pathlib import Path

from onyx.utils.logger import setup_logger

logger = setup_logger()

# Directory the custom CA Secret/ConfigMap is mounted at; each key becomes a file.
# Set by the Helm model-server templates when customCACerts is enabled.
CUSTOM_CA_CERTS_DIR_ENV = "ONYX_CUSTOM_CA_CERTS_DIR"

_MERGED_BUNDLE_NAME = "onyx-model-server-ca-bundle.crt"
_CERT_SUFFIXES = {".crt", ".pem"}


def _iter_custom_cert_files(certs_dir: Path) -> list[Path]:
    """PEM/CRT files projected into the mount, sorted for a stable bundle.

    Kubernetes projects each Secret/ConfigMap key as a file alongside hidden
    `..data` symlinks used for atomic updates; skipping dotfiles and non-files
    leaves just the operator's cert keys, under any key name (not only
    `ca-certificates.crt`).
    """
    return sorted(
        path
        for path in certs_dir.iterdir()
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix in _CERT_SUFFIXES
    )


def configure_trusted_ca_bundle() -> None:
    certs_dir_value = os.environ.get(CUSTOM_CA_CERTS_DIR_ENV, "").strip()
    if not certs_dir_value:
        return

    certs_dir = Path(certs_dir_value)
    if not certs_dir.is_dir():
        logger.warning(
            "%s=%s is not a directory; skipping custom CA bundle assembly.",
            CUSTOM_CA_CERTS_DIR_ENV,
            certs_dir_value,
        )
        return

    custom_cert_files = _iter_custom_cert_files(certs_dir)
    if not custom_cert_files:
        logger.warning(
            "No .crt/.pem files found in %s; skipping custom CA bundle assembly.",
            certs_dir_value,
        )
        return

    import certifi

    try:
        merged = Path(certifi.where()).read_bytes()
        for cert_file in custom_cert_files:
            merged += b"\n" + cert_file.read_bytes()

        bundle_path = Path(tempfile.gettempdir()) / _MERGED_BUNDLE_NAME
        bundle_path.write_bytes(merged)
    except OSError:
        # The operator explicitly configured custom CA roots. If we can't assemble
        # the bundle, fail fast rather than boot into a state that passes health
        # checks but silently can't verify TLS to their private-CA endpoints.
        logger.exception(
            "Failed to assemble the custom CA bundle from %s.",
            certs_dir_value,
        )
        raise

    os.environ["REQUESTS_CA_BUNDLE"] = str(bundle_path)
    os.environ["SSL_CERT_FILE"] = str(bundle_path)
    logger.notice(
        "Trusting %s custom CA file(s) from %s on top of certifi's roots (bundle: %s).",
        len(custom_cert_files),
        certs_dir_value,
        bundle_path,
    )
