from onyx.cache.factory import get_cache_backend
from onyx.configs.app_configs import DISABLE_USER_KNOWLEDGE
from onyx.configs.app_configs import ENABLE_OPENSEARCH_INDEXING_FOR_ONYX
from onyx.configs.app_configs import ONYX_QUERY_HISTORY_TYPE
from onyx.configs.app_configs import SHOW_EXTRA_CONNECTORS
from onyx.configs.app_configs import USER_FILE_MAX_UPLOAD_SIZE_MB
from onyx.configs.constants import KV_SETTINGS_KEY
from onyx.configs.constants import OnyxRedisLocks
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.settings.models import Settings
from onyx.utils.logger import setup_logger

logger = setup_logger()

# TTL for settings keys - 30 days
SETTINGS_TTL = 30 * 24 * 60 * 60


def load_settings() -> Settings:
    kv_store = get_kv_store()
    try:
        stored_settings = kv_store.load(KV_SETTINGS_KEY)
        settings = (
            Settings.model_validate(stored_settings) if stored_settings else Settings()
        )
    except KvKeyNotFoundError:
        # Default to empty settings if no settings have been set yet
        logger.debug(f"No settings found in KV store for key: {KV_SETTINGS_KEY}")
        settings = Settings()
    except Exception as e:
        logger.error(f"Error loading settings from KV store: {str(e)}")
        settings = Settings()

    cache = get_cache_backend()

    try:
        value = cache.get(OnyxRedisLocks.ANONYMOUS_USER_ENABLED)
        if value is not None:
            anonymous_user_enabled = int(value.decode("utf-8")) == 1
        else:
            anonymous_user_enabled = False
            cache.set(OnyxRedisLocks.ANONYMOUS_USER_ENABLED, "0", ex=SETTINGS_TTL)
    except Exception as e:
        logger.error(f"Error loading anonymous user setting from cache: {str(e)}")
        anonymous_user_enabled = False

    settings.anonymous_user_enabled = anonymous_user_enabled

    # Read auto-scroll preference from Redis
    try:
        value = redis_client.get(OnyxRedisLocks.AUTO_SCROLL)
        if value is not None:
            assert isinstance(value, bytes)
            auto_scroll = int(value.decode("utf-8")) == 1
        else:
            # Default to False
            auto_scroll = False
            # Persist default if missing
            redis_client.set(
                OnyxRedisLocks.AUTO_SCROLL, "0", ex=SETTINGS_TTL
            )
    except Exception as e:
        # Log the error and reset to default
        logger.error(f"Error loading auto-scroll setting from Redis: {str(e)}")
        auto_scroll = False

    settings.auto_scroll = auto_scroll
    settings.query_history_type = ONYX_QUERY_HISTORY_TYPE

    if DISABLE_USER_KNOWLEDGE:
        settings.user_knowledge_enabled = False

    settings.user_file_max_upload_size_mb = USER_FILE_MAX_UPLOAD_SIZE_MB
    settings.show_extra_connectors = SHOW_EXTRA_CONNECTORS
    settings.opensearch_indexing_enabled = ENABLE_OPENSEARCH_INDEXING_FOR_ONYX
    return settings


def store_settings(settings: Settings) -> None:
    cache = get_cache_backend()

    if settings.anonymous_user_enabled is not None:
        cache.set(
            OnyxRedisLocks.ANONYMOUS_USER_ENABLED,
            "1" if settings.anonymous_user_enabled else "0",
            ex=SETTINGS_TTL,
        )

    if settings.auto_scroll is not None:
        redis_client.set(
            OnyxRedisLocks.AUTO_SCROLL,
            "1" if settings.auto_scroll else "0",
            ex=SETTINGS_TTL,
        )

    get_kv_store().store(KV_SETTINGS_KEY, settings.model_dump())
