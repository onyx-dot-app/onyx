from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from onyx.configs.app_configs import GLOMI_DEFAULT_WEB_SEARCH_API_BASE
from onyx.configs.app_configs import GLOMI_DEFAULT_WEB_SEARCH_API_KEY
from onyx.configs.app_configs import GLOMI_DEFAULT_WEB_SEARCH_CHANNEL
from onyx.configs.app_configs import GLOMI_DEFAULT_WEB_SEARCH_ENABLED
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.db.web_search import fetch_web_search_provider_by_name_and_type
from onyx.db.web_search import upsert_web_search_provider
from onyx.utils.logger import setup_logger
from shared_configs.enums import WebSearchProviderType

logger = setup_logger()

GLOMI_SEARCH_PROVIDER_NAME = "Glomi Search"


@dataclass(frozen=True)
class GlomiDefaultWebSearchConfig:
    enabled: bool
    api_base: str | None
    api_key: str | None
    channel: str | None


@dataclass(frozen=True)
class GlomiDefaultWebSearchSeedResult:
    seeded: bool
    reason: str


def get_glomi_default_web_search_config() -> GlomiDefaultWebSearchConfig:
    return GlomiDefaultWebSearchConfig(
        enabled=GLOMI_DEFAULT_WEB_SEARCH_ENABLED,
        api_base=GLOMI_DEFAULT_WEB_SEARCH_API_BASE,
        api_key=GLOMI_DEFAULT_WEB_SEARCH_API_KEY,
        channel=GLOMI_DEFAULT_WEB_SEARCH_CHANNEL,
    )


def _clean_optional_config_value(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _build_glomi_provider_config(
    config: GlomiDefaultWebSearchConfig,
) -> dict[str, str]:
    api_base = _clean_optional_config_value(config.api_base)
    if api_base is None:
        raise ValueError("api_base is required")

    provider_config = {"base_url": api_base}
    channel = _clean_optional_config_value(config.channel)
    if channel:
        provider_config["channel"] = channel
    return provider_config


def _should_activate_glomi_provider(active_provider: object | None) -> bool:
    if active_provider is None:
        return True
    return (
        getattr(active_provider, "provider_type", None) == WebSearchProviderType.GLOMI
    )


def seed_glomi_default_web_search_provider(
    db_session: Session,
    config: GlomiDefaultWebSearchConfig | None = None,
) -> GlomiDefaultWebSearchSeedResult:
    config = config or get_glomi_default_web_search_config()
    if not config.enabled:
        logger.info("Skipping Glomi Search provider seed: disabled")
        return GlomiDefaultWebSearchSeedResult(seeded=False, reason="disabled")

    if not _clean_optional_config_value(config.api_base):
        logger.warning(
            "Skipping Glomi Search provider seed: "
            "GLOMI_DEFAULT_WEB_SEARCH_API_BASE is unset"
        )
        return GlomiDefaultWebSearchSeedResult(
            seeded=False, reason="missing_api_base"
        )

    if not _clean_optional_config_value(config.api_key):
        logger.warning(
            "Skipping Glomi Search provider seed: "
            "GLOMI_DEFAULT_WEB_SEARCH_API_KEY is unset"
        )
        return GlomiDefaultWebSearchSeedResult(seeded=False, reason="missing_api_key")

    existing_provider = fetch_web_search_provider_by_name_and_type(
        name=GLOMI_SEARCH_PROVIDER_NAME,
        provider_type=WebSearchProviderType.GLOMI,
        db_session=db_session,
    )
    active_provider = fetch_active_web_search_provider(db_session)
    should_activate = _should_activate_glomi_provider(active_provider)

    upsert_web_search_provider(
        provider_id=existing_provider.id if existing_provider else None,
        name=GLOMI_SEARCH_PROVIDER_NAME,
        provider_type=WebSearchProviderType.GLOMI,
        api_key=config.api_key,
        api_key_changed=True,
        config=_build_glomi_provider_config(config),
        activate=should_activate,
        db_session=db_session,
    )

    return GlomiDefaultWebSearchSeedResult(seeded=True, reason="seeded")
