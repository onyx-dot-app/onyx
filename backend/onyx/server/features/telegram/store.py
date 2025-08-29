from typing import cast

from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.features.telegram.models import TelegramTokenSettings

_SETTINGS_KEY = "telegram_settings"


def load_telegram_settings() -> TelegramTokenSettings:
    dynamic_config_store = get_kv_store()
    try:
        settings = TelegramTokenSettings(**cast(dict, dynamic_config_store.load(_SETTINGS_KEY)))
    except KvKeyNotFoundError:
        settings = TelegramTokenSettings()
        dynamic_config_store.store(_SETTINGS_KEY, settings.dict())

    return settings


def store_telegram_settings(settings: TelegramTokenSettings) -> None:
    get_kv_store().store(_SETTINGS_KEY, settings.dict())
