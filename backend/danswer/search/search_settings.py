from typing import cast

from danswer.configs.constants import KV_SEARCH_SETTINGS
from danswer.dynamic_configs.factory import get_dynamic_config_store
from danswer.dynamic_configs.interface import ConfigNotFoundError
from danswer.search.models import SavedSearchSettings
from danswer.utils.logger import setup_logger

logger = setup_logger()


def get_multilingual_expansion() -> list[str]:
    search_settings = get_search_settings()
    return search_settings.multilingual_expansion if search_settings else []


def get_search_settings() -> SavedSearchSettings | None:
    """Get all user configured search settings which affect the search pipeline
    Note: KV store is used in this case since there is no need to rollback the value or any need to audit past values

    Note: for now we can't cache this value because if the API server is scaled, the cache could be out of sync
    if the value is updated by another process/instance of the API server. If this reads from an in memory cache like
    reddis then it will be ok. Until then this has some performance implications (though minor)
    """
    kv_store = get_dynamic_config_store()
    try:
        return SavedSearchSettings(**cast(dict, kv_store.load(KV_SEARCH_SETTINGS)))
    except ConfigNotFoundError:
        return None
    except Exception as e:
        logger.error(f"Error loading search settings: {e}")
        # Wiping it so that next server startup, it can load the defaults
        # or the user can set it via the API/UI
        kv_store.delete(KV_SEARCH_SETTINGS)
        return None


def update_search_settings(settings: SavedSearchSettings) -> None:
    kv_store = get_dynamic_config_store()
    kv_store.store(KV_SEARCH_SETTINGS, settings.dict())
