import json
from typing import cast

from redis.client import Redis

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import KVStore
from onyx.key_value_store.interface import KeyValueStore
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro


logger = setup_logger()


REDIS_KEY_PREFIX = "onyx_kv_store:"
KV_REDIS_KEY_EXPIRATION = 60 * 60 * 24  # 1 Day


class PgRedisKVStore(KeyValueStore):
    def __init__(self, redis_client: Redis | None = None) -> None:
        # If no redis_client is provided, fall back to the context var
        if redis_client is not None:
            self.redis_client = redis_client
        else:
            self.redis_client = get_redis_client()

    def store(self, key: str, val: JSON_ro, encrypt: bool = False) -> None:
        # Not encrypted in Redis, but encrypted in Postgres
        try:
            self.redis_client.set(
                REDIS_KEY_PREFIX + key, json.dumps(val), ex=KV_REDIS_KEY_EXPIRATION
            )
        except Exception as e:
            # Fallback gracefully to Postgres if Redis fails
            logger.error(f"Failed to set value in Redis for key '{key}': {str(e)}")

        encrypted_val = val if encrypt else None
        plain_val = val if not encrypt else None
        with get_session_with_current_tenant() as db_session:
            obj = db_session.query(KVStore).filter_by(key=key).first()
            if obj:
                obj.value = plain_val
                obj.encrypted_value = encrypted_val
            else:
                obj = KVStore(
                    key=key, value=plain_val, encrypted_value=encrypted_val
                )  # type: ignore
                db_session.query(KVStore).filter_by(key=key).delete()  # just in case
                db_session.add(obj)
            db_session.commit()

    def load(self, key: str, refresh_cache: bool = False) -> JSON_ro:
        if not refresh_cache:
            try:
                redis_value = self.redis_client.get(REDIS_KEY_PREFIX + key)
                if redis_value:
                    if not isinstance(redis_value, bytes):
                        raise ValueError(
                            f"Redis value for key '{key}' is not a bytes object"
                        )
                    return json.loads(redis_value.decode("utf-8"))
            except Exception as e:
                logger.error(
                    f"Failed to get value from Redis for key '{key}': {str(e)}"
                )

        with get_session_with_current_tenant() as db_session:
            obj = db_session.query(KVStore).filter_by(key=key).first()
            if not obj:
                raise KvKeyNotFoundError

            if obj.value is not None:
                value = obj.value
            elif obj.encrypted_value is not None:
                value = obj.encrypted_value
            else:
                value = None

            try:
                self.redis_client.set(REDIS_KEY_PREFIX + key, json.dumps(value))
            except Exception as e:
                logger.error(f"Failed to set value in Redis for key '{key}': {str(e)}")

            return cast(JSON_ro, value)

    def delete(self, key: str) -> None:
        try:
            self.redis_client.delete(REDIS_KEY_PREFIX + key)
        except Exception as e:
            logger.error(f"Failed to delete value from Redis for key '{key}': {str(e)}")

        with get_session_with_current_tenant() as db_session:
            result = db_session.query(KVStore).filter_by(key=key).delete()  # type: ignore
            if result == 0:
                raise KvKeyNotFoundError
            db_session.commit()
