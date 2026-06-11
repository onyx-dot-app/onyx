"""CA bootstrap for the sandbox egress proxy."""

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from onyx.utils.logger import setup_logger

_CA_KEY_SIZE_BITS = 4096
_CA_VALIDITY_DAYS = 1825
_CA_COMMON_NAME = "Onyx Sandbox Proxy CA"
_CA_ORG_NAME = "Onyx"
# mitmproxy auto-loads `$confdir/mitmproxy-ca.pem`. The subdir is ours to chmod
# 0o700 (the mount root is root-owned).
_DEFAULT_CA_PEM_PATH = "/var/run/sandbox-proxy/mitmproxy-confdir/mitmproxy-ca.pem"

logger = setup_logger()


class CAStoreConflictError(Exception):
    """`persist` lost a race; bootstrap re-`load()`s the winner's CA."""


class CAStore(Protocol):
    """Persistence backend for the proxy CA.

    Under a cold-cluster race exactly one `persist` wins; losers raise
    `CAStoreConflictError`.
    """

    def load(self) -> tuple[bytes, bytes] | None: ...

    def persist(self, cert_pem: bytes, key_pem: bytes) -> None: ...


@dataclass(frozen=True)
class MaterializedCA:
    cert_pem: bytes
    key_pem: bytes
    pem_path: Path


class CABootstrap:
    def __init__(
        self,
        store: CAStore,
        pem_path: str | Path = _DEFAULT_CA_PEM_PATH,
        common_name: str = _CA_COMMON_NAME,
        org_name: str = _CA_ORG_NAME,
        key_size_bits: int = _CA_KEY_SIZE_BITS,
        validity_days: int = _CA_VALIDITY_DAYS,
    ) -> None:
        self._store = store
        self._pem_path = Path(pem_path)
        self._common_name = common_name
        self._org_name = org_name
        self._key_size_bits = key_size_bits
        self._validity_days = validity_days

    def ensure_ca(self) -> MaterializedCA:
        existing = self._store.load()
        if existing is not None:
            cert_pem, key_pem = existing
            self._validate_loaded_cert(cert_pem)
            self._log_cert_metadata(cert_pem, "Loaded existing proxy CA.")
            return self._materialize(cert_pem, key_pem)

        cert_pem, key_pem = self._generate_ca()
        try:
            self._store.persist(cert_pem, key_pem)
            self._log_cert_metadata(cert_pem, "Generated and persisted new proxy CA.")
            return self._materialize(cert_pem, key_pem)
        except CAStoreConflictError:
            logger.info("Lost CA persist race; reloading winner's CA.")
            winner = self._store.load()
            if winner is None:
                # Conflict implies a CA exists; a None here is a real fault.
                raise RuntimeError(
                    "CAStore raised conflict but subsequent load returned None."
                )
            cert_pem, key_pem = winner
            self._validate_loaded_cert(cert_pem)
            self._log_cert_metadata(cert_pem, "Loaded race winner's proxy CA.")
            return self._materialize(cert_pem, key_pem)

    @staticmethod
    def _validate_loaded_cert(cert_pem: bytes) -> None:
        try:
            cert = x509.load_pem_x509_certificate(cert_pem)
        except ValueError as e:
            raise RuntimeError(f"Proxy CA cert is not valid PEM: {e}") from e
        now = dt.datetime.now(dt.timezone.utc)
        # Matches the not_before backdating in `_generate_ca` so a freshly
        # generated cert is accepted under clock drift.
        skew = dt.timedelta(minutes=5)
        if cert.not_valid_before_utc > now + skew:
            raise RuntimeError(
                f"Proxy CA cert is not yet valid "
                f"(not_valid_before={cert.not_valid_before_utc.isoformat()})"
            )
        if cert.not_valid_after_utc <= now:
            raise RuntimeError(
                f"Proxy CA cert has expired "
                f"(not_valid_after={cert.not_valid_after_utc.isoformat()}); "
                "Rotate the CA Secret to recover."
            )

    @staticmethod
    def _log_cert_metadata(cert_pem: bytes, prefix: str) -> None:
        cert = x509.load_pem_x509_certificate(cert_pem)
        fingerprint = cert.fingerprint(hashes.SHA256()).hex()
        logger.info(
            "%s sha256=%s not_before=%s not_after=%s",
            prefix,
            fingerprint,
            cert.not_valid_before_utc.isoformat(),
            cert.not_valid_after_utc.isoformat(),
        )

    def _generate_ca(self) -> tuple[bytes, bytes]:
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=self._key_size_bits,
        )

        subject = issuer = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, self._common_name),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, self._org_name),
            ]
        )

        now = dt.datetime.now(dt.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=5))
            .not_valid_after(now + dt.timedelta(days=self._validity_days))
            .add_extension(
                x509.BasicConstraints(ca=True, path_length=0),
                critical=True,
            )
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(private_key.public_key()),
                critical=False,
            )
            .sign(private_key, hashes.SHA256())
        )

        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return cert_pem, key_pem

    def _materialize(self, cert_pem: bytes, key_pem: bytes) -> MaterializedCA:
        # mitmproxy reads key+cert from one PEM; write atomically so a partial
        # write can't leave it reading a half-file.
        self._pem_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # mkdir mode only applies on creation; enforce 0o700 if the dir already
        # exists (e.g. created by the container entrypoint).
        os.chmod(self._pem_path.parent, 0o700)
        tmp_path = self._pem_path.with_suffix(self._pem_path.suffix + ".tmp")
        # Clear a stale .tmp from a prior crash so O_EXCL can succeed.
        try:
            os.unlink(tmp_path)
        except (FileNotFoundError, PermissionError):
            pass
        payload = key_pem + b"\n" + cert_pem
        tmp_fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(tmp_fd, payload)
        finally:
            os.close(tmp_fd)
        os.replace(tmp_path, self._pem_path)
        return MaterializedCA(
            cert_pem=cert_pem, key_pem=key_pem, pem_path=self._pem_path
        )
