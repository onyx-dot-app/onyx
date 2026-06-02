import datetime as dt
import threading
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from onyx.sandbox_proxy.ca import CABootstrap
from onyx.sandbox_proxy.ca import CAStore
from onyx.sandbox_proxy.ca import CAStoreConflictError


class _InMemoryStore(CAStore):
    def __init__(self) -> None:
        self._data: tuple[bytes, bytes] | None = None
        self._lock = threading.Lock()
        self.persist_calls = 0

    def load(self) -> tuple[bytes, bytes] | None:
        with self._lock:
            return self._data

    def persist(self, cert_pem: bytes, key_pem: bytes) -> None:
        with self._lock:
            self.persist_calls += 1
            if self._data is not None:
                raise CAStoreConflictError("already persisted")
            self._data = (cert_pem, key_pem)


def _bootstrap(store: CAStore, pem_path: Path) -> CABootstrap:
    return CABootstrap(store=store, pem_path=pem_path, key_size_bits=2048)


def test_cold_store_generates_and_persists(tmp_path: Path) -> None:
    store = _InMemoryStore()
    bootstrap = _bootstrap(store, tmp_path / "ca.pem")

    materialized = bootstrap.ensure_ca()

    assert store.persist_calls == 1
    assert store.load() == (materialized.cert_pem, materialized.key_pem)

    contents = materialized.pem_path.read_bytes()
    assert b"BEGIN CERTIFICATE" in contents
    assert b"BEGIN PRIVATE KEY" in contents
    assert materialized.pem_path.stat().st_mode & 0o777 == 0o600
    # Parent dir holds the CA private key, so must be 0o700.
    assert materialized.pem_path.parent.stat().st_mode & 0o777 == 0o700

    parsed = x509.load_pem_x509_certificate(materialized.cert_pem)
    bc = parsed.extensions.get_extension_for_class(x509.BasicConstraints)
    assert bc.value.ca is True


def _build_cert(
    *,
    not_valid_before: dt.datetime,
    not_valid_after: dt.datetime,
) -> tuple[bytes, bytes]:
    """Build a (cert_pem, key_pem) with explicit validity bounds."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_valid_before)
        .not_valid_after(not_valid_after)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(private_key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def test_load_rejects_expired_cert(tmp_path: Path) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    cert_pem, key_pem = _build_cert(
        not_valid_before=now - dt.timedelta(days=400),
        not_valid_after=now - dt.timedelta(days=1),
    )
    store = _InMemoryStore()
    store._data = (cert_pem, key_pem)

    with pytest.raises(RuntimeError, match="has expired"):
        _bootstrap(store, tmp_path / "ca.pem").ensure_ca()


def test_load_rejects_not_yet_valid_cert(tmp_path: Path) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    # 1 hour ahead is well outside the 5-minute skew tolerance.
    cert_pem, key_pem = _build_cert(
        not_valid_before=now + dt.timedelta(hours=1),
        not_valid_after=now + dt.timedelta(days=365),
    )
    store = _InMemoryStore()
    store._data = (cert_pem, key_pem)

    with pytest.raises(RuntimeError, match="not yet valid"):
        _bootstrap(store, tmp_path / "ca.pem").ensure_ca()


def test_load_rejects_malformed_pem(tmp_path: Path) -> None:
    store = _InMemoryStore()
    store._data = (b"this is not a PEM cert", b"this is not a PEM key")

    with pytest.raises(RuntimeError, match="not valid PEM"):
        _bootstrap(store, tmp_path / "ca.pem").ensure_ca()


def test_load_accepts_cert_within_skew_tolerance(tmp_path: Path) -> None:
    # 2 minutes ahead is inside the 5-minute skew window, so accepted.
    now = dt.datetime.now(dt.timezone.utc)
    cert_pem, key_pem = _build_cert(
        not_valid_before=now + dt.timedelta(minutes=2),
        not_valid_after=now + dt.timedelta(days=365),
    )
    store = _InMemoryStore()
    store._data = (cert_pem, key_pem)

    materialized = _bootstrap(store, tmp_path / "ca.pem").ensure_ca()
    assert materialized.cert_pem == cert_pem


def test_warm_store_loads_without_regenerating(tmp_path: Path) -> None:
    store = _InMemoryStore()
    first = _bootstrap(store, tmp_path / "ca.pem").ensure_ca()
    second = _bootstrap(store, tmp_path / "ca2.pem").ensure_ca()

    assert store.persist_calls == 1
    assert second.cert_pem == first.cert_pem
    assert second.key_pem == first.key_pem


def test_persist_conflict_returns_winners_ca(tmp_path: Path) -> None:
    class _ConflictingStore(CAStore):
        def __init__(self, winner_cert: bytes, winner_key: bytes) -> None:
            self.load_calls = 0
            self._winner_cert = winner_cert
            self._winner_key = winner_key

        def load(self) -> tuple[bytes, bytes] | None:
            self.load_calls += 1
            if self.load_calls == 1:
                return None
            return self._winner_cert, self._winner_key

        def persist(
            self,
            cert_pem: bytes,  # noqa: ARG002
            key_pem: bytes,  # noqa: ARG002
        ) -> None:
            raise CAStoreConflictError("simulated race loss")

    winner_store = _InMemoryStore()
    winner = _bootstrap(winner_store, tmp_path / "winner.pem").ensure_ca()

    loser_store = _ConflictingStore(winner.cert_pem, winner.key_pem)
    materialized = _bootstrap(loser_store, tmp_path / "loser.pem").ensure_ca()

    assert materialized.cert_pem == winner.cert_pem
    assert materialized.key_pem == winner.key_pem
    assert loser_store.load_calls == 2


def test_persist_conflict_with_missing_winner_raises(tmp_path: Path) -> None:
    class _BrokenStore(CAStore):
        def load(self) -> tuple[bytes, bytes] | None:
            return None

        def persist(
            self,
            cert_pem: bytes,  # noqa: ARG002
            key_pem: bytes,  # noqa: ARG002
        ) -> None:
            raise CAStoreConflictError("simulated race loss")

    with pytest.raises(RuntimeError, match="subsequent load returned None"):
        _bootstrap(_BrokenStore(), tmp_path / "ca.pem").ensure_ca()
