from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import InternetSearchProvider
from onyx.db.web_search import fetch_active_web_content_provider
from onyx.db.web_search import fetch_active_web_search_provider
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
from onyx.tools.tool_implementations.web_search.clients.searxng_client import (
    SearXNGClient,
)
from onyx.tools.tool_implementations.web_search.clients.serper_client import (
    SerperClient,
)
from onyx.tools.tool_implementations.web_search.models import DEFAULT_MAX_RESULTS
from onyx.tools.tool_implementations.web_search.models import WebContentProviderConfig
from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.utils.logger import setup_logger
from shared_configs.enums import WebContentProviderType
from shared_configs.enums import WebSearchProviderType

logger = setup_logger()


def build_search_provider_from_config(
    provider_type: WebSearchProviderType,
    api_key: str,
    config: dict[str, str] | None,  # TODO use a typed object
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
    if provider_type == WebSearchProviderType.SEARXNG:
        searxng_base_url = config.get("searxng_base_url")
        if not searxng_base_url:
            raise ValueError("Please provide a URL for your private SearXNG instance.")
        return SearXNGClient(
            searxng_base_url,
            num_results=num_results,
        )


def _build_search_provider(provider_model: InternetSearchProvider) -> WebSearchProvider:
    return build_search_provider_from_config(
        provider_type=WebSearchProviderType(provider_model.provider_type),
        api_key=provider_model.api_key or "",
        config=provider_model.config or {},
    )


def build_content_provider_from_config(
    *,
    provider_type: WebContentProviderType,
    api_key: str,
    config: WebContentProviderConfig,
) -> WebContentProvider | None:
    if provider_type == WebContentProviderType.ONYX_WEB_CRAWLER:
        if config.timeout_seconds is not None:
            return OnyxWebCrawler(timeout_seconds=config.timeout_seconds)
        return OnyxWebCrawler()

    if provider_type == WebContentProviderType.FIRECRAWL:
        if config.base_url is None:
            raise ValueError("Firecrawl content provider requires a base URL.")
        if config.timeout_seconds is None:
            return FirecrawlClient(api_key=api_key, base_url=config.base_url)
        return FirecrawlClient(
            api_key=api_key,
            base_url=config.base_url,
            timeout_seconds=config.timeout_seconds,
        )


def get_default_provider() -> WebSearchProvider | None:
    with get_session_with_current_tenant() as db_session:
        provider_model = fetch_active_web_search_provider(db_session)
        if provider_model is None:
            return None
        return _build_search_provider(provider_model)


def get_default_content_provider() -> WebContentProvider:
    with get_session_with_current_tenant() as db_session:
        provider_model = fetch_active_web_content_provider(db_session)
        if provider_model:
            provider = build_content_provider_from_config(
                provider_type=WebContentProviderType(provider_model.provider_type),
                api_key=provider_model.api_key or "",
                config=WebContentProviderConfig.model_validate(
                    provider_model.config or {}
                ),
            )
            if provider:
                return provider

    return OnyxWebCrawler()
