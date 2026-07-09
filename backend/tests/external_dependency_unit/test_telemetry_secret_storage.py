"""Telemetry instance secrets persist encrypted-at-rest, never in the plain KV store."""

from sqlalchemy.orm import Session

from onyx.configs.constants import KV_CUSTOMER_UUID_KEY
from onyx.configs.constants import KV_INSTANCE_DOMAIN_KEY
from onyx.db.encrypted_kv_store import load_encrypted_kv
from onyx.db.models import EncryptedKeyValueStore
from onyx.db.models import KVStore
from onyx.key_value_store.interface import unwrap_str
from onyx.utils import telemetry
from tests.external_dependency_unit.conftest import create_test_user


def _purge(db_session: Session, key: str) -> None:
    db_session.query(EncryptedKeyValueStore).filter_by(key=key).delete()
    db_session.query(KVStore).filter_by(key=key).delete()
    db_session.commit()


def test_customer_uuid_persists_in_encrypted_table(db_session: Session) -> None:
    telemetry._CACHED_UUID = None
    _purge(db_session, KV_CUSTOMER_UUID_KEY)
    try:
        generated = telemetry.get_or_generate_uuid()

        assert unwrap_str(load_encrypted_kv(KV_CUSTOMER_UUID_KEY)) == generated
        assert (
            db_session.query(KVStore).filter_by(key=KV_CUSTOMER_UUID_KEY).first()
            is None
        )
    finally:
        telemetry._CACHED_UUID = None


def test_instance_domain_persists_in_encrypted_table(db_session: Session) -> None:
    telemetry._CACHED_INSTANCE_DOMAIN = None
    _purge(db_session, KV_INSTANCE_DOMAIN_KEY)
    create_test_user(db_session, "telemetry_domain")
    try:
        domain = telemetry._get_or_generate_instance_domain()

        assert domain is not None
        assert unwrap_str(load_encrypted_kv(KV_INSTANCE_DOMAIN_KEY)) == domain
        assert (
            db_session.query(KVStore).filter_by(key=KV_INSTANCE_DOMAIN_KEY).first()
            is None
        )
    finally:
        telemetry._CACHED_INSTANCE_DOMAIN = None
