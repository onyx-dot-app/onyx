from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from ee.onyx.secondary_llm_flows.search_flow_classification import (
    classify_is_search_flow,
)
from ee.onyx.server.query_and_chat.models import SearchFlowClassificationRequest
from ee.onyx.server.query_and_chat.models import SearchFlowClassificationResponse
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.llm.factory import get_default_llm
from onyx.server.usage_limits import check_llm_cost_limit_for_provider
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
