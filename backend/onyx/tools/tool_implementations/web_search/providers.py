from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import InternetSearchProvider
from onyx.db.web_search import fetch_active_web_content_provider
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.tools.tool_implementations.open_url.firecrawl import FirecrawlClient
from onyx.tools.tool_implementations.open_url.models import (
    WebContentProvider,
)
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import (
    DEFAULT_MAX_HTML_SIZE_BYTES,
)
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import (
    DEFAULT_MAX_PDF_SIZE_BYTES,
)
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import OnyxWebCrawler
from onyx.tools.tool_implementations.web_search.clients.brave_client import (
    BraveClient,
)
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


def provider_requires_api_key(provider_type: WebSearchProviderType) -> bool:
    """Return True if the given provider type requires an API key.
    This list is most likely just going to contain SEARXNG. The way it works is that it uses public search engines that do not
    require an API key. You can also set it up in a way which requires a key but SearXNG itself does not require a key.
    """
    return provider_type != WebSearchProviderType.SEARXNG


def build_search_provider_from_config(
    provider_type: WebSearchProviderType,
    api_key: str | None,
    config: dict[str, str] | None,  # TODO use a typed object
) -> WebSearchProvider:
    config = config or {}
    num_results = int(config.get("num_results") or DEFAULT_MAX_RESULTS)

    # SearXNG does not require an API key
    if provider_type == WebSearchProviderType.SEARXNG:
        searxng_base_url = config.get("searxng_base_url")
        if not searxng_base_url:
            raise ValueError("Please provide a URL for your private SearXNG instance.")
        return SearXNGClient(
            searxng_base_url,
            num_results=num_results,
        )

    # All other providers require an API key
    if not api_key:
        raise ValueError(f"API key is required for {provider_type.value} provider.")

    if provider_type == WebSearchProviderType.EXA:
        return ExaClient(api_key=api_key, num_results=num_results)
    if provider_type == WebSearchProviderType.BRAVE:
        return BraveClient(
            api_key=api_key,
            num_results=num_results,
            timeout_seconds=int(config.get("timeout_seconds") or 10),
        )
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

    raise ValueError(f"Unknown provider type: {provider_type.value}")


def _build_search_provider(provider_model: InternetSearchProvider) -> WebSearchProvider:
    return build_search_provider_from_config(
        provider_type=WebSearchProviderType(provider_model.provider_type),
        api_key=(
            provider_model.api_key.get_value(apply_mask=False)
            if provider_model.api_key
            else None
        ),
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
            return OnyxWebCrawler(
                timeout_seconds=config.timeout_seconds,
                max_pdf_size_bytes=DEFAULT_MAX_PDF_SIZE_BYTES,
                max_html_size_bytes=DEFAULT_MAX_HTML_SIZE_BYTES,
            )
        return OnyxWebCrawler(
            max_pdf_size_bytes=DEFAULT_MAX_PDF_SIZE_BYTES,
            max_html_size_bytes=DEFAULT_MAX_HTML_SIZE_BYTES,
        )

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

    if provider_type == WebContentProviderType.EXA:
        return ExaClient(api_key=api_key)


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
                api_key=(
                    provider_model.api_key.get_value(apply_mask=False)
                    if provider_model.api_key
                    else ""
                ),
                config=provider_model.config or WebContentProviderConfig(),
            )
            if provider:
                return provider

    return OnyxWebCrawler(
        max_pdf_size_bytes=DEFAULT_MAX_PDF_SIZE_BYTES,
        max_html_size_bytes=DEFAULT_MAX_HTML_SIZE_BYTES,
    )
