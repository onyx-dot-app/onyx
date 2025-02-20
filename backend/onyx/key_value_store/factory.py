from onyx.key_value_store.interface import KeyValueStore
from onyx.key_value_store.store import PgRedisKVStore
from shared_configs.configs import DEFAULT_REDIS_PREFIX
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR


def get_kv_store() -> KeyValueStore:
    # In the Multi Tenant case, the tenant context is picked up automatically, it does not need to be passed in
    # It's read from the global thread level variable
    return PgRedisKVStore()


def get_shared_kv_store() -> KeyValueStore:
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(DEFAULT_REDIS_PREFIX)
    try:
        return get_kv_store()
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)
