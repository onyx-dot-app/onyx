"""Sentry instance identities persist encrypted-at-rest, never in the plain KV store."""

from sqlalchemy.orm import Session

from onyx.configs.constants import KV_CUSTOMER_UUID_KEY
from onyx.db.encrypted_kv_store import load_encrypted_kv
from onyx.db.models import EncryptedKeyValueStore, KVStore
from onyx.key_value_store.interface import unwrap_str
from onyx.utils import instance_identity


def _purge(db_session: Session, key: str) -> None:
    db_session.query(EncryptedKeyValueStore).filter_by(key=key).delete()
    db_session.query(KVStore).filter_by(key=key).delete()
    db_session.commit()


def test_customer_uuid_persists_in_encrypted_table(db_session: Session) -> None:
    instance_identity._CACHED_UUID = None
    _purge(db_session, KV_CUSTOMER_UUID_KEY)
    try:
        generated = instance_identity.get_or_generate_uuid()

        assert unwrap_str(load_encrypted_kv(KV_CUSTOMER_UUID_KEY)) == generated
        assert (
            db_session.query(KVStore).filter_by(key=KV_CUSTOMER_UUID_KEY).first()
            is None
        )
    finally:
        instance_identity._CACHED_UUID = None
