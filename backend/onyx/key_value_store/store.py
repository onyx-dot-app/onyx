import json
from typing import cast

from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import KVStore
from onyx.key_value_store.interface import KeyValueStore
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()


REDIS_KEY_PREFIX = "onyx_kv_store:"
KV_REDIS_KEY_EXPIRATION = 60 * 60 * 24  # 1 Day


class PgRedisKVStore(KeyValueStore):
    def __init__(self, cache: CacheBackend | None = None) -> None:
        self._cache = cache

    def _get_cache(self) -> CacheBackend:
        if self._cache is None:
            from onyx.cache.factory import get_cache_backend

            self._cache = get_cache_backend()
        return self._cache

    def store(self, key: str, val: JSON_ro, encrypt: bool = False) -> None:
        # Not encrypted in Cache backend (typically Redis), but encrypted in Postgres
        try:
            self._get_cache().set(
                REDIS_KEY_PREFIX + key, json.dumps(val), ex=KV_REDIS_KEY_EXPIRATION
            )
        except Exception as e:
            # Fallback gracefully to Postgres if Cache backend fails
            logger.error(
                f"Failed to set value in Cache backend for key '{key}': {str(e)}"
            )

        encrypted_val = val if encrypt else None
        plain_val = val if not encrypt else None
        with get_session_with_current_tenant() as db_session:
            obj = db_session.query(KVStore).filter_by(key=key).first()
            if obj:
                obj.value = plain_val
                obj.encrypted_value = encrypted_val  # type: ignore[assignment]
            else:
                obj = KVStore(key=key, value=plain_val, encrypted_value=encrypted_val)
                db_session.query(KVStore).filter_by(key=key).delete()  # just in case
                db_session.add(obj)
            db_session.commit()

    def load(self, key: str, refresh_cache: bool = False) -> JSON_ro:
        if not refresh_cache:
            try:
                cached = self._get_cache().get(REDIS_KEY_PREFIX + key)
                if cached is not None:
                    return json.loads(cached.decode("utf-8"))
            except Exception as e:
                logger.error(
                    f"Failed to get value from cache for key '{key}': {str(e)}"
                )

        with get_session_with_current_tenant() as db_session:
            obj = db_session.query(KVStore).filter_by(key=key).first()
            if not obj:
                raise KvKeyNotFoundError

            if obj.value is not None:
                value = obj.value
            elif obj.encrypted_value is not None:
                # Unwrap SensitiveValue - this is internal backend use
                value = obj.encrypted_value.get_value(apply_mask=False)
            else:
                value = None

            try:
                self._get_cache().set(
                    REDIS_KEY_PREFIX + key,
                    json.dumps(value),
                    ex=KV_REDIS_KEY_EXPIRATION,
                )
            except Exception as e:
                logger.error(f"Failed to set value in cache for key '{key}': {str(e)}")

            return cast(JSON_ro, value)

    def delete(self, key: str) -> None:
        try:
            self._get_cache().delete(REDIS_KEY_PREFIX + key)
        except Exception as e:
            logger.error(f"Failed to delete value from cache for key '{key}': {str(e)}")

        with get_session_with_current_tenant() as db_session:
            result = db_session.query(KVStore).filter_by(key=key).delete()
            if result == 0:
                raise KvKeyNotFoundError
            db_session.commit()
