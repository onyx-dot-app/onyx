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


@router.post("/search", response_model=WebSearchToolResponse)
def execute_web_search(
    request: WebSearchToolRequest,
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> WebSearchToolResponse:
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

        for search_result in search_results:
            results.append(
                LlmWebSearchResult(
                    document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
                    url=search_result.link,
                    title=search_result.title,
                    snippet=search_result.snippet or "",
                    unique_identifier_to_strip_away=search_result.link,
                )
            )

    return WebSearchToolResponse(
        results=results, provider_type=provider_view.provider_type
    )


@router.post("/open-urls", response_model=OpenUrlsToolResponse)
def execute_open_urls(
    request: OpenUrlsToolRequest,
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> OpenUrlsToolResponse:
    provider = _get_content_provider(db_session)

    try:
        docs = provider.contents(request.urls)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Web content provider failed to fetch URLs")
        raise HTTPException(
            status_code=502, detail="Web content provider failed to fetch URLs."
        ) from exc

    results = [
        LlmOpenUrlResult(
            document_citation_number=DOCUMENT_CITATION_NUMBER_EMPTY_VALUE,
            content=truncate_search_result_content(doc.full_content),
            unique_identifier_to_strip_away=doc.link,
        )
        for doc in docs
    ]

    return OpenUrlsToolResponse(results=results)
