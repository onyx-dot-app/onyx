"""Guards encrypted KV row storage, updates, and missing-key errors."""

from collections.abc import Generator

import pytest
from sqlalchemy import delete

from onyx.db.encrypted_kv_store import (
    delete_encrypted_kv,
    load_encrypted_kv,
    upsert_encrypted_kv,
)
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import EncryptedKeyValueStore
from onyx.key_value_store.interface import KvKeyNotFoundError
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE

TEST_KEY = "test_encrypted_kv_accessor_key"


@pytest.fixture(autouse=True)
def _clean_encrypted_kv() -> Generator[None, None, None]:
    yield
    with get_session_with_tenant(
        tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
    ) as session:
        session.execute(delete(EncryptedKeyValueStore))
        session.commit()


class TestUpsertAndLoad:
    def test_upsert_then_load_round_trips_dict(self) -> None:
        value = {"hello": "world", "nested": {"enabled": True}}

        upsert_encrypted_kv(TEST_KEY, value)

        assert load_encrypted_kv(TEST_KEY) == value

    def test_upsert_same_key_updates_value(self) -> None:
        upsert_encrypted_kv(TEST_KEY, {"version": 1})
        updated_value = {"version": 2, "nested": {"updated": True}}

        upsert_encrypted_kv(TEST_KEY, updated_value)

        assert load_encrypted_kv(TEST_KEY) == updated_value

    def test_load_missing_key_raises(self) -> None:
        with pytest.raises(KvKeyNotFoundError):
            load_encrypted_kv(TEST_KEY)


class TestDelete:
    def test_delete_removes_key_and_future_load_raises(self) -> None:
        upsert_encrypted_kv(TEST_KEY, {"hello": "world"})

        delete_encrypted_kv(TEST_KEY)

        with pytest.raises(KvKeyNotFoundError):
            load_encrypted_kv(TEST_KEY)

    def test_delete_missing_key_raises(self) -> None:
        with pytest.raises(KvKeyNotFoundError):
            delete_encrypted_kv(TEST_KEY)
