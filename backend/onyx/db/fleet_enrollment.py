"""The deployment's fleet telemetry key."""

import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from onyx.configs.constants import KV_CUSTOMER_UUID_KEY
from onyx.db.encrypted_kv_store import load_encrypted_kv
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import KVStore
from onyx.key_value_store.interface import KvKeyNotFoundError, unwrap_str
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA

DEPLOYMENT_KEY_NAME: str = "fleet_telemetry_deployment_key"


def get_or_create_deployment_key() -> str:
    """One random key per deployment. It stays the same across restarts and upgrades."""
    with get_session_with_tenant(tenant_id=POSTGRES_DEFAULT_SCHEMA) as db_session:
        # Processes that start together all read the one key that the first insert stored.
        db_session.execute(
            insert(KVStore)
            .values(key=DEPLOYMENT_KEY_NAME, value=secrets.token_hex(32))
            .on_conflict_do_nothing(index_elements=["key"])
        )
        key: object = db_session.execute(
            select(KVStore.value).where(KVStore.key == DEPLOYMENT_KEY_NAME)
        ).scalar_one()
        db_session.commit()
    return str(key)


def get_legacy_customer_uuid() -> str | None:
    """The instance UUID that Onyx before v5 stored and sent. Never creates one."""
    try:
        value: str = unwrap_str(load_encrypted_kv(KV_CUSTOMER_UUID_KEY))
    except KvKeyNotFoundError:
        return None
    return str(uuid.UUID(value))
