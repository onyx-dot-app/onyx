"""Encrypted-at-rest key/value storage for instance-level secrets.

Backed by the ``encrypted_key_value_store`` table and never mirrored to the cache, so
secrets stay encrypted at rest and out of Redis. Tenant context is picked up from the
current-tenant contextvar, matching the plain KV store."""

from typing import Any
from typing import cast

from sqlalchemy.dialects.postgresql import insert as pg_insert

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import EncryptedKeyValueStore
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.special_types import JSON_ro


def upsert_encrypted_kv(key: str, value: dict[str, Any]) -> None:
    with get_session_with_current_tenant() as db_session:
        # Native upsert so concurrent first writes for a key cannot race into a
        # primary-key violation.
        stmt = pg_insert(EncryptedKeyValueStore).values(key=key, value=value)
        db_session.execute(
            stmt.on_conflict_do_update(
                index_elements=["key"], set_={"value": stmt.excluded.value}
            )
        )
        db_session.commit()


def load_encrypted_kv(key: str) -> JSON_ro:
    with get_session_with_current_tenant() as db_session:
        obj = db_session.query(EncryptedKeyValueStore).filter_by(key=key).first()
        if obj is None:
            raise KvKeyNotFoundError
        return cast(JSON_ro, obj.value.get_value(apply_mask=False))


def delete_encrypted_kv(key: str) -> None:
    with get_session_with_current_tenant() as db_session:
        deleted = db_session.query(EncryptedKeyValueStore).filter_by(key=key).delete()
        if deleted == 0:
            raise KvKeyNotFoundError
        db_session.commit()
