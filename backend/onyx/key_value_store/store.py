import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

from fastapi import HTTPException
from redis.client import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from onyx.db.engine import get_sqlalchemy_engine
from onyx.db.engine import is_valid_schema_name
from onyx.db.models import KVStore
from onyx.key_value_store.interface import KeyValueStore
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger
from onyx.utils.special_types import JSON_ro
from shared_configs.configs import MULTI_TENANT
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


REDIS_KEY_PREFIX = "onyx_kv_store:"
KV_REDIS_KEY_EXPIRATION = 60 * 60 * 24  # 1 Day


class PgRedisKVStore(KeyValueStore):
    def __init__(self, redis_client: Redis | None = None) -> None:
        self.tenant_id = get_current_tenant_id()

        # If no redis_client is provided, fall back to the context var
        if redis_client is not None:
            self.redis_client = redis_client
        else:
            self.redis_client = get_redis_client(tenant_id=self.tenant_id)

    @contextmanager
    def _get_session(self) -> Iterator[Session]:
        engine = get_sqlalchemy_engine()
        with Session(engine, expire_on_commit=False) as session:
            if MULTI_TENANT:
                if self.tenant_id == POSTGRES_DEFAULT_SCHEMA:
                    raise HTTPException(
                        status_code=401, detail="User must authenticate"
                    )
                if not is_valid_schema_name(self.tenant_id):
                    raise HTTPException(status_code=400, detail="Invalid tenant ID")
                # Set the search_path to the tenant's schema
                session.execute(text(f'SET search_path = "{self.tenant_id}"'))
            yield session

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
        with self._get_session() as session:
            obj = session.query(KVStore).filter_by(key=key).first()
            if obj:
                obj.value = plain_val
                obj.encrypted_value = encrypted_val
            else:
                obj = KVStore(
                    key=key, value=plain_val, encrypted_value=encrypted_val
                )  # type: ignore
                session.query(KVStore).filter_by(key=key).delete()  # just in case
                session.add(obj)
            session.commit()

    def load(self, key: str) -> JSON_ro:
        try:
            redis_value = self.redis_client.get(REDIS_KEY_PREFIX + key)
            if redis_value:
                assert isinstance(redis_value, bytes)
                return json.loads(redis_value.decode("utf-8"))
        except Exception as e:
            logger.error(f"Failed to get value from Redis for key '{key}': {str(e)}")

        with self._get_session() as session:
            obj = session.query(KVStore).filter_by(key=key).first()
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

        with self._get_session() as session:
            result = session.query(KVStore).filter_by(key=key).delete()  # type: ignore
            if result == 0:
                raise KvKeyNotFoundError
            session.commit()
