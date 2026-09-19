from collections.abc import Generator
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.db import unstructured as storage
from onyx.db.models import EncryptedKeyValueStore, KVStore
from onyx.file_processing.unstructured import (
    delete_unstructured_api_key,
    get_unstructured_api_key,
    update_unstructured_api_key,
)
from onyx.key_value_store.store import REDIS_KEY_PREFIX


@pytest.fixture
def key_name(
    monkeypatch: pytest.MonkeyPatch, db_session: Session
) -> Generator[str, None, None]:
    key = f"test_unstructured_{uuid4().hex}"
    monkeypatch.setattr(storage, "KV_UNSTRUCTURED_API_KEY", key)
    yield key
    db_session.rollback()
    db_session.query(KVStore).filter_by(key=key).delete()
    db_session.query(EncryptedKeyValueStore).filter_by(key=key).delete()
    db_session.commit()


def test_legacy_key_migrates_and_rotates_without_plaintext(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, key_name: str
) -> None:
    cache = MagicMock()
    monkeypatch.setattr(storage, "get_cache_backend", lambda: cache)
    db_session.add(KVStore(key=key_name, value="synthetic-legacy"))
    db_session.commit()
    assert get_unstructured_api_key() == "synthetic-legacy"
    assert db_session.get(KVStore, key_name) is None
    ciphertext = db_session.execute(
        text("SELECT value FROM encrypted_key_value_store WHERE key = :key"),
        {"key": key_name},
    ).scalar_one()
    assert "synthetic-legacy" not in str(ciphertext)
    cache.delete.assert_called_with(REDIS_KEY_PREFIX + key_name)
    cache.get.assert_not_called()
    update_unstructured_api_key("synthetic-rotated")
    assert get_unstructured_api_key() == "synthetic-rotated"
    delete_unstructured_api_key()
    assert get_unstructured_api_key() is None


def test_failed_migration_preserves_legacy_key(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, key_name: str
) -> None:
    db_session.add(KVStore(key=key_name, value="synthetic-recovery"))
    db_session.commit()
    with monkeypatch.context() as context:
        context.setattr(
            Session,
            "commit",
            MagicMock(side_effect=RuntimeError("synthetic commit failure")),
        )
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            get_unstructured_api_key()
    legacy = db_session.get(KVStore, key_name)
    assert legacy is not None
    assert legacy.value == "synthetic-recovery"
    assert db_session.get(EncryptedKeyValueStore, key_name) is None


def test_encrypted_key_wins_over_stale_legacy_and_cache(
    monkeypatch: pytest.MonkeyPatch, db_session: Session, key_name: str
) -> None:
    cache = MagicMock()
    cache.get.return_value = b'"synthetic-stale"'
    monkeypatch.setattr(storage, "get_cache_backend", lambda: cache)
    update_unstructured_api_key("synthetic-current")
    db_session.add(KVStore(key=key_name, value="synthetic-stale"))
    db_session.commit()
    assert get_unstructured_api_key() == "synthetic-current"
    assert db_session.get(KVStore, key_name) is None
    cache.get.assert_not_called()
