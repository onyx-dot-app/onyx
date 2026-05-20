import threading
from pathlib import Path

import pytest
from cryptography import x509

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

    parsed = x509.load_pem_x509_certificate(materialized.cert_pem)
    bc = parsed.extensions.get_extension_for_class(x509.BasicConstraints)
    assert bc.value.ca is True


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
