from onyx.configs.constants import KV_SETTINGS_KEY
from onyx.configs.constants import OnyxRedisLocks
from onyx.key_value_store.factory import get_kv_store
from onyx.redis.redis_pool import get_redis_client
from onyx.server.settings.models import Settings
from shared_configs.configs import MULTI_TENANT


def load_settings() -> Settings:
    if MULTI_TENANT:
        # If multi-tenant, anonymous user is always false
        anonymous_user_enabled = False
    else:
        redis_client = get_redis_client(tenant_id=None)
        value = redis_client.get(OnyxRedisLocks.ANONYMOUS_USER_ENABLED)
        if value is not None:
            assert isinstance(value, bytes)
            anonymous_user_enabled = int(value.decode("utf-8")) == 1
        else:
            # Default to False
            anonymous_user_enabled = False
            # Optionally store the default back to Redis
            redis_client.set(OnyxRedisLocks.ANONYMOUS_USER_ENABLED, "0")

    settings = Settings(anonymous_user_enabled=anonymous_user_enabled)
    return settings


def store_settings(settings: Settings) -> None:
    if not MULTI_TENANT and settings.anonymous_user_enabled is not None:
        # Only non-multi-tenant scenario can set the anonymous user enabled flag
        redis_client = get_redis_client(tenant_id=None)
        redis_client.set(
            OnyxRedisLocks.ANONYMOUS_USER_ENABLED,
            "1" if settings.anonymous_user_enabled else "0",
        )

    get_kv_store().store(KV_SETTINGS_KEY, settings.model_dump())
