from typing import cast

from onyx.configs.constants import KV_SEARCH_SETTINGS
from onyx.context.search.models import SavedSearchSettings
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.utils.logger import setup_logger

logger = setup_logger()


def get_kv_search_settings() -> SavedSearchSettings | None:
    """Get all user configured search settings which affect the search pipeline
    Note: KV store is used in this case since there is no need to rollback the value or any need to audit past values

    Note: for now we can't cache this value because if the API server is scaled, the cache could be out of sync
    if the value is updated by another process/instance of the API server. If this reads from an in memory cache like
    reddis then it will be ok. Until then this has some performance implications (though minor)
    """
    kv_store = get_kv_store()
    try:
        return SavedSearchSettings(**cast(dict, kv_store.load(KV_SEARCH_SETTINGS)))
    except KvKeyNotFoundError:
        return None
    except Exception as e:
        logger.error(f"Error loading search settings: {e}")
        # Wiping it so that next server startup, it can load the defaults
        # or the user can set it via the API/UI
        kv_store.delete(KV_SEARCH_SETTINGS)
        return None
