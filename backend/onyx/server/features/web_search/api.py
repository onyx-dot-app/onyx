from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.chat.models import DOCUMENT_CITATION_NUMBER_EMPTY_VALUE
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
from onyx.tools.tool_implementations.web_search.clients.onyx_web_crawler_client import (
    OnyxWebCrawlerClient,
)
from onyx.tools.tool_implementations.web_search.models import (
    WebContentProvider,
)
from onyx.tools.tool_implementations.web_search.models import (
    WebSearchProvider,
)
from onyx.tools.tool_implementations.web_search.providers import (
    build_content_provider_from_config,
)
from onyx.tools.tool_implementations.web_search.providers import (
    build_search_provider_from_config,
)
from onyx.tools.tool_implementations.web_search.utils import (
    truncate_search_result_content,
)
from onyx.tools.tool_implementations_v2.tool_result_models import (
    LlmOpenUrlResult,
)
from onyx.tools.tool_implementations_v2.tool_result_models import (
    LlmWebSearchResult,
)
from onyx.utils.logger import setup_logger
from shared_configs.enums import WebContentProviderType
from shared_configs.enums import WebSearchProviderType

router = APIRouter(prefix="/web-search")
logger = setup_logger()


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

    try:
        provider: WebSearchProvider | None = build_search_provider_from_config(
            provider_type=provider_view.provider_type,
            api_key=provider_model.api_key,
            config=provider_model.config or {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if provider is None:
        raise HTTPException(
            status_code=400,
            detail="Unable to initialize the configured web search provider.",
        )

    return provider_view, provider


def _get_active_content_provider(
    db_session: Session,
) -> tuple[WebContentProviderView | None, WebContentProvider]:
    provider_model = fetch_active_web_content_provider(db_session)

    if provider_model is None:
        # Default to the built-in crawler if nothing is configured. Always available.
        # NOTE: the OnyxWebCrawlerClient is not stored in the content provider table,
        # so we need to return it directly.

        return None, OnyxWebCrawlerClient()

    try:
        provider_type = WebContentProviderType(provider_model.provider_type)
        provider: WebContentProvider | None = build_content_provider_from_config(
            provider_type=provider_type,
            api_key=provider_model.api_key,
            config=provider_model.config or {},
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

        trimmed_results = list(search_results)[: request.max_results]
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
    provider_view, provider = _get_active_content_provider(db_session)

    try:
        docs = provider.contents(urls)
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
