from typing import Any

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.web_search import fetch_active_web_content_provider
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.tools.tool_implementations.open_url.firecrawl import FIRECRAWL_SCRAPE_URL
from onyx.tools.tool_implementations.open_url.firecrawl import FirecrawlClient
from onyx.tools.tool_implementations.open_url.models import (
    WebContentProvider,
)
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import OnyxWebCrawler
from onyx.tools.tool_implementations.web_search.clients.exa_client import (
    ExaClient,
)
from onyx.tools.tool_implementations.web_search.clients.google_pse_client import (
    GooglePSEClient,
)
from onyx.tools.tool_implementations.web_search.clients.serper_client import (
    SerperClient,
)
from onyx.tools.tool_implementations.web_search.models import DEFAULT_MAX_RESULTS
from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.utils.logger import setup_logger
from shared_configs.enums import WebContentProviderType
from shared_configs.enums import WebSearchProviderType

logger = setup_logger()


def build_search_provider_from_config(
    provider_type: WebSearchProviderType,
    api_key: str,
    config: dict[str, str] | None,
) -> WebSearchProvider:
    config = config or {}
    num_results = int(config.get("num_results") or DEFAULT_MAX_RESULTS)

    if provider_type == WebSearchProviderType.EXA:
        return ExaClient(api_key=api_key, num_results=num_results)
    if provider_type == WebSearchProviderType.SERPER:
        return SerperClient(api_key=api_key, num_results=num_results)
    if provider_type == WebSearchProviderType.GOOGLE_PSE:
        search_engine_id = (
            config.get("search_engine_id")
            or config.get("cx")
            or config.get("search_engine")
        )
        if not search_engine_id:
            raise ValueError(
                "Google PSE provider requires a search engine id (cx) in addition to the API key."
            )

        return GooglePSEClient(
            api_key=api_key,
            search_engine_id=search_engine_id,
            num_results=num_results,
            timeout_seconds=int(config.get("timeout_seconds") or 10),
        )


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
        return OnyxWebCrawler(timeout_seconds=timeout_seconds)

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
        return OnyxWebCrawler()
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(f"Failed to initialize default Onyx crawler: {exc}")
        return None
