"""The deployment's fleet telemetry key."""

import secrets

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.models import KVStore
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
