from typing import Any

from onyx.agents.agent_search.dr.sub_agents.web_search.clients.exa_client import (
    ExaClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.clients.firecrawl_client import (
    FIRECRAWL_SCRAPE_URL,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.clients.firecrawl_client import (
    FirecrawlClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.clients.google_pse_client import (
    GooglePSEClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.clients.onyx_web_crawler_client import (
    OnyxWebCrawlerClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.clients.serper_client import (
    SerperClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebContentProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchProvider,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.web_search import fetch_active_web_content_provider
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.utils.logger import setup_logger
from shared_configs.enums import WebContentProviderType
from shared_configs.enums import WebSearchProviderType

logger = setup_logger()


def build_search_provider_from_config(
    *,
    provider_type: WebSearchProviderType,
    api_key: str | None,
    config: dict[str, str] | None,
    provider_name: str = "web_search_provider",
) -> WebSearchProvider | None:
    provider_type_value = provider_type.value
    try:
        provider_type_enum = WebSearchProviderType(provider_type_value)
    except ValueError:
        logger.error(
            f"Unknown web search provider type '{provider_type_value}'. "
            "Skipping provider initialization."
        )
        return None

    # All web search providers require an API key
    if not api_key:
        raise ValueError(
            f"Web search provider '{provider_name}' is missing an API key."
        )
    assert api_key is not None

    config = config or {}

    if provider_type_enum == WebSearchProviderType.EXA:
        return ExaClient(api_key=api_key)
    if provider_type_enum == WebSearchProviderType.SERPER:
        return SerperClient(api_key=api_key)
    if provider_type_enum == WebSearchProviderType.GOOGLE_PSE:
        search_engine_id = (
            config.get("search_engine_id")
            or config.get("cx")
            or config.get("search_engine")
        )
        if not search_engine_id:
            raise ValueError(
                "Google PSE provider requires a search engine id (cx) in addition to the API key."
            )
        assert search_engine_id is not None
        try:
            num_results = int(config.get("num_results", 10))
        except (TypeError, ValueError):
            raise ValueError(
                "Invalid value for Google PSE 'num_results'; expected integer."
            )
        try:
            timeout_seconds = int(config.get("timeout_seconds", 10))
        except (TypeError, ValueError):
            raise ValueError(
                "Invalid value for Google PSE 'timeout_seconds'; expected integer."
            )
        return GooglePSEClient(
            api_key=api_key,
            search_engine_id=search_engine_id,
            num_results=num_results,
            timeout_seconds=timeout_seconds,
        )

    logger.error(
        f"Unhandled web search provider type '{provider_type_value}'. "
        "Skipping provider initialization."
    )
    return None


def _build_search_provider(provider_model: Any) -> WebSearchProvider | None:
    return build_search_provider_from_config(
        provider_type=WebSearchProviderType(provider_model.provider_type),
        api_key=provider_model.api_key,
        config=provider_model.config or {},
        provider_name=provider_model.name,
    )


def build_content_provider_from_config(
    *,
    provider_type: WebContentProviderType,
    api_key: str | None,
    config: dict[str, str] | None,
    provider_name: str = "web_content_provider",
) -> WebContentProvider | None:
    provider_type_value = provider_type.value
    try:
        provider_type_enum = WebContentProviderType(provider_type_value)
    except ValueError:
        logger.error(
            f"Unknown web content provider type '{provider_type_value}'. "
            "Skipping provider initialization."
        )
        return None

    if provider_type_enum == WebContentProviderType.ONYX_WEB_CRAWLER:
        config = config or {}
        timeout_value = config.get("timeout_seconds", 15)
        try:
            timeout_seconds = int(timeout_value)
        except (TypeError, ValueError):
            raise ValueError(
                "Invalid value for Onyx Web Crawler 'timeout_seconds'; expected integer."
            )
        return OnyxWebCrawlerClient(timeout_seconds=timeout_seconds)

    if provider_type_enum == WebContentProviderType.FIRECRAWL:
        if not api_key:
            raise ValueError("Firecrawl content provider requires an API key.")
        assert api_key is not None
        config = config or {}
        timeout_seconds_str = config.get("timeout_seconds")
        if timeout_seconds_str is None:
            timeout_seconds = 10
        else:
            try:
                timeout_seconds = int(timeout_seconds_str)
            except (TypeError, ValueError):
                raise ValueError(
                    "Invalid value for Firecrawl 'timeout_seconds'; expected integer."
                )
        return FirecrawlClient(
            api_key=api_key,
            base_url=config.get("base_url") or FIRECRAWL_SCRAPE_URL,
            timeout_seconds=timeout_seconds,
        )

    logger.error(
        f"Unhandled web content provider type '{provider_type_value}'. "
        "Skipping provider initialization."
    )
    return None


def _build_content_provider(provider_model: Any) -> WebContentProvider | None:
    return build_content_provider_from_config(
        provider_type=WebContentProviderType(provider_model.provider_type),
        api_key=provider_model.api_key,
        config=provider_model.config or {},
        provider_name=provider_model.name,
    )


def get_default_provider() -> WebSearchProvider | None:
    with get_session_with_current_tenant() as db_session:
        provider_model = fetch_active_web_search_provider(db_session)
        if provider_model is None:
            return None
        return _build_search_provider(provider_model)


def get_default_content_provider() -> WebContentProvider | None:
    with get_session_with_current_tenant() as db_session:
        provider_model = fetch_active_web_content_provider(db_session)
        if provider_model:
            provider = _build_content_provider(provider_model)
            if provider:
                return provider

    # Fall back to built-in Onyx crawler when nothing is configured.
    try:
        return OnyxWebCrawlerClient()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to initialize default Onyx crawler: {exc}")
        return None
