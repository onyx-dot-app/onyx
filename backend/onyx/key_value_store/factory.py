from onyx.key_value_store.interface import KeyValueStore
from onyx.key_value_store.store import PgRedisKVStore


def get_kv_store() -> KeyValueStore:
    # In the Multi Tenant case, the tenant context is picked up automatically, it does not need to be passed in
    # It's read from the global thread level variable
    return PgRedisKVStore()
