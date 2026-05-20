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
_DEFAULT_CA_PEM_PATH = "/var/run/sandbox-proxy/ca.pem"

logger = setup_logger()


class CAStoreConflictError(Exception):
    """Raised by `CAStore.persist` when another writer has already
    persisted a CA. The bootstrap layer responds by re-`load()`ing and
    returning the winner's CA."""


class CAStore(Protocol):
    """Persistence backend for the proxy CA.

    `persist` must be idempotent under concurrent callers: if two
    proxy replicas race on a cold cluster, exactly one write wins.
    The loser raises `CAStoreConflictError`; the bootstrap layer
    responds by re-`load()`ing.
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
            logger.info("loaded existing proxy CA from store")
            return self._materialize(cert_pem, key_pem)

        cert_pem, key_pem = self._generate_ca()
        try:
            self._store.persist(cert_pem, key_pem)
            logger.info("generated and persisted new proxy CA")
            return self._materialize(cert_pem, key_pem)
        except CAStoreConflictError:
            logger.info("lost CA persist race; reloading winner's CA")
            winner = self._store.load()
            if winner is None:
                # Conflict means something exists; a follow-up None is
                # a real fault, not a cold store. Don't paper over it.
                raise RuntimeError(
                    "CAStore raised conflict but subsequent load returned None"
                )
            cert_pem, key_pem = winner
            return self._materialize(cert_pem, key_pem)

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
        # mitmproxy reads key+cert from one PEM. Atomic via rename so a
        # partial write can't leave it reading a half-file.
        self._pem_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._pem_path.with_suffix(self._pem_path.suffix + ".tmp")
        payload = key_pem + b"\n" + cert_pem
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        os.replace(tmp_path, self._pem_path)
        return MaterializedCA(
            cert_pem=cert_pem, key_pem=key_pem, pem_path=self._pem_path
        )
