from typing import Literal

from sqlalchemy import delete, select, text

from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import KV_UNSTRUCTURED_API_KEY
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import EncryptedKeyValueStore, KVStore
from onyx.key_value_store.interface import unwrap_str
from onyx.key_value_store.store import REDIS_KEY_PREFIX
from onyx.utils.logger import setup_logger

logger = setup_logger()


def access_unstructured_api_key(
    operation: Literal["load", "store", "delete"], api_key: str | None = None
) -> str | None:
    with get_session_with_current_tenant() as session:
        # Serialize migration, rotation, and deletion even when neither row exists.
        session.execute(
            text(
                "SELECT pg_advisory_xact_lock(hashtext(current_schema()), hashtext(:key))"
            ),
            {"key": KV_UNSTRUCTURED_API_KEY},
        )
        encrypted = session.scalar(
            select(EncryptedKeyValueStore).where(
                EncryptedKeyValueStore.key == KV_UNSTRUCTURED_API_KEY
            )
        )
        legacy = session.get(KVStore, KV_UNSTRUCTURED_API_KEY)
        if operation == "load":
            if encrypted is not None:
                api_key = unwrap_str(encrypted.value.get_value(apply_mask=False))
            elif legacy is not None:
                value = legacy.value
                if value is None and legacy.encrypted_value is not None:
                    value = legacy.encrypted_value.get_value(apply_mask=False)
                api_key = unwrap_str(value) if value is not None else None
        if operation == "delete":
            session.execute(
                delete(EncryptedKeyValueStore).where(
                    EncryptedKeyValueStore.key == KV_UNSTRUCTURED_API_KEY
                )
            )
            api_key = None
        elif api_key is not None and (encrypted is None or operation == "store"):
            if encrypted is None:
                encrypted = EncryptedKeyValueStore(key=KV_UNSTRUCTURED_API_KEY)
                session.add(encrypted)
            encrypted.value = {"value": api_key}  # ty: ignore[invalid-assignment]
        if legacy is not None:
            session.delete(legacy)
        session.commit()

    try:
        get_cache_backend().delete(REDIS_KEY_PREFIX + KV_UNSTRUCTURED_API_KEY)
    except Exception:
        logger.warning(
            "Could not remove the legacy Unstructured credential cache entry"
        )
    return api_key
