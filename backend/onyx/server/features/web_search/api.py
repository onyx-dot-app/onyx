from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.web_search import fetch_active_web_content_provider
from onyx.db.web_search import fetch_active_web_search_provider
from onyx.server.features.web_search.models import OpenUrlsToolRequest
from onyx.server.features.web_search.models import OpenUrlsToolResponse
from onyx.server.features.web_search.models import WebSearchToolRequest
from onyx.server.features.web_search.models import WebSearchToolResponse
from onyx.server.features.web_search.models import WebSearchWithContentResponse
from onyx.server.manage.web_search.models import WebContentProviderView
from onyx.server.manage.web_search.models import WebSearchProviderView
from onyx.server.utils import PUBLIC_API_TAGS
from onyx.tools.models import LlmOpenUrlResult
from onyx.tools.models import LlmWebSearchResult
from onyx.tools.tool_implementations.open_url.models import WebContentProvider
from onyx.tools.tool_implementations.open_url.onyx_web_crawler import (
    OnyxWebCrawler,
)
from onyx.tools.tool_implementations.open_url.utils import (
    filter_web_contents_with_no_title_or_content,
)
from onyx.tools.tool_implementations.web_search.models import WebContentProviderConfig
from onyx.tools.tool_implementations.web_search.models import WebSearchProvider
from onyx.tools.tool_implementations.web_search.providers import (
    build_content_provider_from_config,
)
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
)
from onyx.tools.tool_implementations.web_search.utils import (
    filter_web_search_results_with_no_title_or_snippet,
)
from onyx.tools.tool_implementations.web_search.utils import (
    truncate_search_result_content,
)
from onyx.utils.logger import setup_logger
from shared_configs.enums import WebContentProviderType
from shared_configs.enums import WebSearchProviderType

router = APIRouter(prefix="/web-search", tags=PUBLIC_API_TAGS)
logger = setup_logger()


DOCUMENT_CITATION_NUMBER_EMPTY_VALUE = -1


def _get_active_search_provider(
    db_session: Session,
) -> tuple[WebSearchProviderView, WebSearchProvider]:
    provider_model = fetch_active_web_search_provider(db_session)
    if provider_model is None:
        raise HTTPException(
            status_code=400,
            detail="No web search provider configured.",
        )

    provider_view = WebSearchProviderView(
        id=provider_model.id,
        name=provider_model.name,
        provider_type=WebSearchProviderType(provider_model.provider_type),
        is_active=provider_model.is_active,
        config=provider_model.config or {},
        has_api_key=bool(provider_model.api_key),
    )

    if not provider_model.api_key:
        raise HTTPException(
            status_code=400,
            detail="Web search provider requires an API key.",
        )

    try:
        provider: WebSearchProvider = build_search_provider_from_config(
            provider_type=provider_view.provider_type,
            api_key=provider_model.api_key,
            config=provider_model.config or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return provider_view, provider


def _get_active_content_provider(
    db_session: Session,
) -> tuple[WebContentProviderView | None, WebContentProvider]:
    provider_model = fetch_active_web_content_provider(db_session)

    if provider_model is None:
        # Default to the built-in crawler if nothing is configured. Always available.
        # NOTE: the OnyxWebCrawler is not stored in the content provider table,
        # so we need to return it directly.

        return None, OnyxWebCrawler()

    if provider_model.api_key is None:
        # TODO - this is not a great error, in fact, this key should not be nullable.
        raise HTTPException(
            status_code=400,
            detail="Web content provider requires an API key.",
        )

    try:
        provider_type = WebContentProviderType(provider_model.provider_type)

        config = provider_model.config or {}
        timeout_conf = config.get("timeout_seconds")
        if timeout_conf is not None:
            timeout_seconds = int(timeout_conf)
        else:
            timeout_seconds = None
        base_url = config.get("base_url")
        provider: WebContentProvider | None = build_content_provider_from_config(
            provider_type=provider_type,
            api_key=provider_model.api_key,
            config=WebContentProviderConfig(
                timeout_seconds=timeout_seconds,
                base_url=base_url,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if provider is None:
        raise HTTPException(
            status_code=400,
            detail="Unable to initialize the configured web content provider.",
        )

    provider_view = WebContentProviderView(
        id=provider_model.id,
        name=provider_model.name,
        provider_type=provider_type,
        is_active=provider_model.is_active,
        config=provider_model.config or {},
        has_api_key=bool(provider_model.api_key),
    )

    return provider_view, provider


def _run_web_search(
    request: WebSearchToolRequest, db_session: Session
) -> tuple[WebSearchProviderType, list[LlmWebSearchResult]]:
    provider_view, provider = _get_active_search_provider(db_session)

    results: list[LlmWebSearchResult] = []
    for query in request.queries:
        try:
            search_results = provider.search(query)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Web search provider failed for query '%s'", query)
            raise HTTPException(
                status_code=502, detail="Web search provider failed to execute query."
            ) from exc

        filtered_results = filter_web_search_results_with_no_title_or_snippet(
            list(search_results)
        )
        trimmed_results = list(filtered_results)[: request.max_results]
        for search_result in trimmed_results:
            results.append(
                LlmWebSearchResult(
                    document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                    url=search_result.link,
                    title=search_result.title,
                    snippet=search_result.snippet or "",
                    unique_identifier_to_strip_away=search_result.link,
                )
            )
    return provider_view.provider_type, results


def _open_urls(
    urls: list[str],
    db_session: Session,
) -> tuple[WebContentProviderType | None, list[LlmOpenUrlResult]]:
    # SSRF protection is handled inside the content provider (OnyxWebCrawler)
    # which uses ssrf_safe_get() to validate and fetch atomically,
    # preventing DNS rebinding attacks
    provider_view, provider = _get_active_content_provider(db_session)

    try:
        docs = filter_web_contents_with_no_title_or_content(
            list(provider.contents(urls))
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Web content provider failed to fetch URLs")
        raise HTTPException(
            status_code=502, detail="Web content provider failed to fetch URLs."
        ) from exc

    results: list[LlmOpenUrlResult] = []
    for doc in docs:
        results.append(
            LlmOpenUrlResult(
                document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                content=truncate_search_result_content(doc.full_content),
                unique_identifier_to_strip_away=doc.link,
            )
        )
    provider_type = (
        provider_view.provider_type
        if provider_view
        else WebContentProviderType.ONYX_WEB_CRAWLER
    )
    return provider_type, results


@router.post("/search", response_model=WebSearchWithContentResponse)
def execute_web_search(
    request: WebSearchToolRequest,
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> WebSearchWithContentResponse:
    """
    Perform a web search and immediately fetch content for the returned URLs.

    Use this when you want both snippets and page contents from one call.

    If you want to selectively fetch content (i.e. let the LLM decide which URLs to read),
    use `/search-lite` and then call `/open-urls` separately.
    """
    search_provider_type, search_results = _run_web_search(request, db_session)

    if not search_results:
        return WebSearchWithContentResponse(
            search_provider_type=search_provider_type,
            content_provider_type=None,
            search_results=[],
            full_content_results=[],
        )

    # Fetch contents for unique URLs in the order they appear
    seen: set[str] = set()
    urls_to_fetch: list[str] = []
    for result in search_results:
        url = result.url
        if url not in seen:
            seen.add(url)
            urls_to_fetch.append(url)

    content_provider_type, full_content_results = _open_urls(urls_to_fetch, db_session)

    return WebSearchWithContentResponse(
        search_provider_type=search_provider_type,
        content_provider_type=content_provider_type,
        search_results=search_results,
        full_content_results=full_content_results,
    )


@router.post("/search-lite", response_model=WebSearchToolResponse)
def execute_web_search_lite(
    request: WebSearchToolRequest,
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> WebSearchToolResponse:
    """
    Lightweight search-only endpoint. Returns search snippets and URLs without
    fetching page contents. Pair with `/open-urls` if you need to fetch content
    later.
    """
    provider_type, search_results = _run_web_search(request, db_session)

    return WebSearchToolResponse(results=search_results, provider_type=provider_type)


@router.post("/open-urls", response_model=OpenUrlsToolResponse)
def execute_open_urls(
    request: OpenUrlsToolRequest,
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> OpenUrlsToolResponse:
    """
    Fetch content for specific URLs using the configured content provider.
    Intended to complement `/search-lite` when you need content for a subset of URLs.
    """
    provider_type, results = _open_urls(request.urls, db_session)
    return OpenUrlsToolResponse(results=results, provider_type=provider_type)
