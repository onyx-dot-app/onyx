from pathlib import Path

import pytest

from onyx.sandbox_proxy.ca import CAStoreConflictError
from onyx.sandbox_proxy.ca_docker import FileCAStore

_CERT = b"-----BEGIN CERTIFICATE-----\nfake-cert\n-----END CERTIFICATE-----\n"
_KEY = b"-----BEGIN PRIVATE KEY-----\nfake-key\n-----END PRIVATE KEY-----\n"


def _store(tmp_path: Path) -> FileCAStore:
    return FileCAStore(root=tmp_path / "ca")


def test_cold_store_load_returns_none(tmp_path: Path) -> None:
    assert _store(tmp_path).load() is None


def test_persist_then_load_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.persist(_CERT, _KEY)

    loaded = store.load()
    assert loaded == (_CERT, _KEY)


def test_persist_writes_correct_modes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.persist(_CERT, _KEY)

    cert_path = tmp_path / "ca" / "ca.crt"
    key_path = tmp_path / "ca" / "ca.key"
    # 0o644 cert so sandboxes mounting RO can read; 0o600 key, proxy-only.
    assert cert_path.stat().st_mode & 0o777 == 0o644
    assert key_path.stat().st_mode & 0o777 == 0o600


def test_persist_conflict_raises_when_cert_present(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.persist(_CERT, _KEY)

    # Second call simulates a racing replica losing on O_EXCL. CABootstrap
    # catches CAStoreConflictError and re-load()s the winner's CA.
    with pytest.raises(CAStoreConflictError):
        store.persist(_CERT, _KEY)


def test_load_with_cert_but_missing_key_fails_loud(tmp_path: Path) -> None:
    root = tmp_path / "ca"
    root.mkdir(parents=True)
    (root / "ca.crt").write_bytes(_CERT)
    # No ca.key -- simulates a crash between cert and key write.

    with pytest.raises(RuntimeError, match="key is missing"):
        FileCAStore(root=root).load()


def test_load_with_key_but_missing_cert_fails_loud(tmp_path: Path) -> None:
    root = tmp_path / "ca"
    root.mkdir(parents=True)
    (root / "ca.key").write_bytes(_KEY)

    with pytest.raises(RuntimeError, match="cert is missing"):
        FileCAStore(root=root).load()


def test_persist_creates_root_if_missing(tmp_path: Path) -> None:
    # `tmp_path/ca` does not yet exist; persist should mkdir it.
    store = FileCAStore(root=tmp_path / "fresh" / "ca")
    store.persist(_CERT, _KEY)

    assert (tmp_path / "fresh" / "ca" / "ca.crt").exists()
    assert (tmp_path / "fresh" / "ca" / "ca.key").exists()
