from typing import cast

from danswer.configs.constants import KV_SETTINGS_KEY
from danswer.key_value_store.factory import get_kv_store
from danswer.key_value_store.interface import KvKeyNotFoundError
from danswer.server.settings.models import Settings


def load_settings() -> Settings:
    dynamic_config_store = get_kv_store()
    try:
        settings = Settings(**cast(dict, dynamic_config_store.load(KV_SETTINGS_KEY)))
    except KvKeyNotFoundError:
        settings = Settings()
        dynamic_config_store.store(KV_SETTINGS_KEY, settings.model_dump())

    return settings


def store_settings(settings: Settings) -> None:
    get_kv_store().store(KV_SETTINGS_KEY, settings.model_dump())
