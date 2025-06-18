from onyx.configs.constants import KV_KG_CONFIG_KEY
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.kg.models import KGConfigSettings
from onyx.server.kg.models import EnableKGConfigRequest
from onyx.utils.logger import setup_logger

logger = setup_logger()


def set_kg_config_settings(kg_config_settings: KGConfigSettings) -> None:
    kv_store = get_kv_store()
    kv_store.store(KV_KG_CONFIG_KEY, kg_config_settings.model_dump())


def get_kg_config_settings() -> KGConfigSettings:
    kv_store = get_kv_store()
    try:
        # refresh cache True until beta is over as we may manually update the config in the db
        stored_config = kv_store.load(KV_KG_CONFIG_KEY, refresh_cache=True)
        return KGConfigSettings.model_validate(stored_config or {})
    except KvKeyNotFoundError:
        # Default to empty kg config if no config have been set yet
        logger.debug(f"No kg config found in KV store for key: {KV_KG_CONFIG_KEY}")
        return KGConfigSettings()
    except Exception as e:
        logger.error(f"Error loading kg config from KV store: {str(e)}")
        return KGConfigSettings()


def validate_kg_settings(kg_config_settings: KGConfigSettings) -> None:
    if not kg_config_settings.KG_ENABLED:
        raise ValueError("KG is not enabled")
    if not kg_config_settings.KG_VENDOR:
        raise ValueError("KG_VENDOR is not set")
    if not kg_config_settings.KG_VENDOR_DOMAINS:
        raise ValueError("KG_VENDOR_DOMAINS is not set")


def is_kg_config_settings_enabled_valid(kg_config_settings: KGConfigSettings) -> bool:
    try:
        validate_kg_settings(kg_config_settings)
        return True
    except Exception:
        return False


def enable_kg(enable_req: EnableKGConfigRequest) -> None:
    kg_config_settings = get_kg_config_settings()
    kg_config_settings.KG_ENABLED = True
    kg_config_settings.KG_VENDOR = enable_req.vendor
    kg_config_settings.KG_VENDOR_DOMAINS = enable_req.vendor_domains
    kg_config_settings.KG_IGNORE_EMAIL_DOMAINS = enable_req.ignore_domains
    kg_config_settings.KG_COVERAGE_START = enable_req.coverage_start.strftime(
        "%Y-%m-%d"
    )
    kg_config_settings.KG_MAX_COVERAGE_DAYS = 10000  # TODO: revisit after public beta

    validate_kg_settings(kg_config_settings)
    set_kg_config_settings(kg_config_settings)


def disable_kg() -> None:
    kg_config_settings = get_kg_config_settings()
    kg_config_settings.KG_ENABLED = False
    set_kg_config_settings(kg_config_settings)
