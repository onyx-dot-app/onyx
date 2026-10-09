from onyx.configs.app_configs import ENABLE_MULTIPASS_INDEXING
from onyx.db.models import SearchSettings
from onyx.indexing.models import MultipassConfig


def should_use_multipass(search_settings: SearchSettings | None) -> bool:
    """
    Determines whether multipass should be used based on the search settings
    or the default config if settings are unavailable.
    """
    if search_settings is not None:
        return search_settings.multipass_indexing
    return ENABLE_MULTIPASS_INDEXING


def get_multipass_config(search_settings: SearchSettings) -> MultipassConfig:
    """
    Determines whether to enable multipass and large chunks by examining
    the current search settings and the embedder configuration.
    """
    multipass = should_use_multipass(search_settings)
    enable_large_chunks = SearchSettings.can_use_large_chunks(
        multipass, search_settings.model_name, search_settings.provider_type
    )
    return MultipassConfig(
        multipass_indexing=multipass, enable_large_chunks=enable_large_chunks
    )
