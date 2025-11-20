from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.sub_agents.web_search.clients.onyx_web_crawler_client import (
    OnyxWebCrawlerClient,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebContentProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.models import (
    WebSearchProvider,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
    build_content_provider_from_config,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.providers import (
    build_search_provider_from_config,
)
from onyx.agents.agent_search.dr.sub_agents.web_search.utils import (
    truncate_search_result_content,
)
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
from onyx.server.manage.web_search.models import WebSearchProviderView
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
            detail="No active web search provider configured.",
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


def _get_content_provider(db_session: Session) -> WebContentProvider:
    provider_model = fetch_active_web_content_provider(db_session)

    if provider_model is not None:
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

        return provider

    # Fall back to the built-in crawler if nothing is configured.
    try:
        return OnyxWebCrawlerClient()
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.exception("Failed to initialize Onyx web crawler fallback")
        raise HTTPException(
            status_code=503, detail="No web content provider available."
        ) from exc


def _run_web_search(
    request: WebSearchToolRequest, db_session: Session
) -> tuple[WebSearchProviderView, list[LlmWebSearchResult]]:
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
    return provider_view, results


def _open_urls(
    urls: list[str],
    db_session: Session,
) -> list[LlmOpenUrlResult]:
    provider = _get_content_provider(db_session)

    try:
        docs = provider.contents(urls)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Web content provider failed to fetch URLs")
        raise HTTPException(
            status_code=502, detail="Web content provider failed to fetch URLs."
        ) from exc

    return [
        LlmOpenUrlResult(
            document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            content=truncate_search_result_content(doc.full_content),
            unique_identifier_to_strip_away=doc.link,
        )
        for doc in docs
    ]


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
    provider_view, search_results = _run_web_search(request, db_session)

    # Fetch contents for unique URLs in the order they appear
    seen: set[str] = set()
    urls_to_fetch: list[str] = []
    for result in search_results:
        url = result.url
        if url not in seen:
            seen.add(url)
            urls_to_fetch.append(url)

    fetched_results = _open_urls(urls_to_fetch, db_session) if urls_to_fetch else []

    return WebSearchWithContentResponse(
        provider_type=provider_view.provider_type,
        search_results=search_results,
        fetched_results=fetched_results,
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
    provider_view, search_results = _run_web_search(request, db_session)

    return WebSearchToolResponse(
        results=search_results, provider_type=provider_view.provider_type
    )


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
    results = _open_urls(request.urls, db_session)
    return OpenUrlsToolResponse(results=results)
