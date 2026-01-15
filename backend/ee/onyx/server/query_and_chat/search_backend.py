from collections.abc import Generator

from fastapi import APIRouter
from fastapi import Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ee.onyx.db.search import fetch_search_queries_for_user
from ee.onyx.search.process_search_query import gather_search_stream
from ee.onyx.search.process_search_query import stream_search_query
from ee.onyx.secondary_llm_flows.search_flow_classification import (
    classify_is_search_flow,
)
from ee.onyx.server.query_and_chat.models import SearchFlowClassificationRequest
from ee.onyx.server.query_and_chat.models import SearchFlowClassificationResponse
from ee.onyx.server.query_and_chat.models import SearchFullResponse
from ee.onyx.server.query_and_chat.models import SearchHistoryResponse
from ee.onyx.server.query_and_chat.models import SearchQueryResponse
from ee.onyx.server.query_and_chat.models import SendSearchQueryRequest
from ee.onyx.server.query_and_chat.streaming_models import SearchErrorPacket
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import User
from onyx.llm.factory import get_default_llm
from onyx.server.usage_limits import check_llm_cost_limit_for_provider
from onyx.server.utils import get_json_line
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/search")


@router.post("/search-flow-classification")
def search_flow_classification(
    request: SearchFlowClassificationRequest,
    # This is added just to ensure this endpoint isn't spammed by non-authorized users since there's an LLM call underneath it
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SearchFlowClassificationResponse:
    query = request.user_query
    # This is a heuristic that if the user is typing a lot of text, it's unlikely they're looking for some specific document
    # Most likely something needs to be done with the text included so we'll just classify it as a chat flow
    if len(query) > 200:
        return SearchFlowClassificationResponse(is_search_flow=False)

    llm = get_default_llm()

    check_llm_cost_limit_for_provider(
        db_session=db_session,
        tenant_id=get_current_tenant_id(),
        llm_provider_api_key=llm.config.api_key,
    )

    try:
        is_search_flow = classify_is_search_flow(query=query, llm=llm)
    except Exception as e:
        logger.exception(
            "Search flow classification failed; defaulting to chat flow",
            exc_info=e,
        )
        is_search_flow = False

    return SearchFlowClassificationResponse(is_search_flow=is_search_flow)


@router.post("/send-search-message", response_model=None)
def handle_send_search_message(
    request: SendSearchQueryRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> StreamingResponse | SearchFullResponse:
    """
    Execute a search query with optional streaming.

    When stream=True: Returns StreamingResponse with SSE
    When stream=False: Returns SearchFullResponse
    """
    logger.debug(f"Received search query: {request.search_query}")

    # Non-streaming path
    if not request.stream:
        try:
            packets = stream_search_query(request, user, db_session)
            return gather_search_stream(packets)
        except NotImplementedError as e:
            return SearchFullResponse(
                all_executed_queries=[],
                search_docs=[],
                error=str(e),
            )
        except Exception as e:
            logger.exception("Error processing search query")
            return SearchFullResponse(
                all_executed_queries=[],
                search_docs=[],
                error=str(e),
            )

    # Streaming path
    def stream_generator() -> Generator[str, None, None]:
        try:
            with get_session_with_current_tenant() as streaming_db_session:
                for packet in stream_search_query(request, user, streaming_db_session):
                    yield get_json_line(packet.model_dump())
        except NotImplementedError as e:
            yield get_json_line(SearchErrorPacket(error=str(e)).model_dump())
        except Exception as e:
            logger.exception("Error in search streaming")
            yield get_json_line(SearchErrorPacket(error=str(e)).model_dump())

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.get("/search-history")
def get_search_history(
    limit: int = 100,
    filter_days: int | None = None,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SearchHistoryResponse:
    """
    Fetch past search queries for the authenticated user.

    Args:
        limit: Maximum number of queries to return (default 10)
        filter_days: Only return queries from the last N days (optional)

    Returns:
        SearchHistoryResponse with list of search queries, ordered by most recent first.
    """
    # TODO remove this
    if user is None:
        # Return empty list for unauthenticated users
        return SearchHistoryResponse(search_queries=[])

    search_queries = fetch_search_queries_for_user(
        db_session=db_session,
        user_id=user.id,
        filter_days=filter_days,
        limit=limit,
    )

    return SearchHistoryResponse(
        search_queries=[
            SearchQueryResponse(
                query=sq.query,
                query_expansions=sq.query_expansions,
                created_at=sq.created_at,
            )
            for sq in search_queries
        ]
    )
