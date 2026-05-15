"""Search API endpoint (POST /api/search).

Runs the full SearchTool.run() pipeline — the same multi-stage search that
powers chat mode. Returns ranked results without generating an LLM answer.

Intended for programmatic consumers (onyx-cli, Craft sandbox, integrations).

Not the same as the Onyx Search UI backend at /api/search/send-search-message
(ee/onyx/server/query_and_chat/search_backend.py), which calls search_pipeline()
directly — a lighter-weight flow with optional query expansion.
"""

import json
from datetime import timezone
from typing import cast

from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.auth.schemas import UserRole
from onyx.chat.emitter import NullEmitter
from onyx.configs.constants import MessageType
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import PersonaSearchInfo
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.llm import can_user_access_llm_provider
from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import fetch_user_group_ids
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.search_settings import get_current_search_settings
from onyx.db.tools import get_tools
from onyx.document_index.factory import get_default_document_index
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.factory import get_default_llm
from onyx.llm.factory import get_llm_for_persona
from onyx.llm.factory import llm_from_provider
from onyx.server.features.search.models import SearchRequest
from onyx.server.features.search.models import SearchResponse
from onyx.server.features.search.models import SearchResult
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.query_and_chat.placement import Placement
from onyx.server.usage_limits import check_llm_cost_limit_for_provider
from onyx.server.utils_vector_db import require_vector_db
from onyx.tools.constants import SEARCH_TOOL_ID
from onyx.tools.models import ChatMinimalTextMessage
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from shared_configs.contextvars import get_current_tenant_id

router = APIRouter(prefix="/search")


@router.post("", dependencies=[Depends(require_vector_db)])
def search(
    request: SearchRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SearchResponse:
    # 1. Load persona
    persona = None
    if request.persona_id is not None:
        try:
            persona = get_persona_by_id(
                persona_id=request.persona_id,
                user=user,
                db_session=db_session,
                is_for_edit=False,
            )
        except ValueError:
            raise OnyxError(OnyxErrorCode.PERSONA_NOT_FOUND)

        persona_search_info = PersonaSearchInfo(
            document_set_names=[ds.name for ds in persona.document_sets],
            search_start_date=persona.search_start_date,
            attached_document_ids=[doc.id for doc in persona.attached_documents],
            hierarchy_node_ids=[node.id for node in persona.hierarchy_nodes],
        )
    else:
        persona_search_info = PersonaSearchInfo(
            document_set_names=[],
            search_start_date=None,
            attached_document_ids=[],
            hierarchy_node_ids=[],
        )

    # 2. Get LLM
    if request.provider:
        provider_model = fetch_existing_llm_provider(request.provider, db_session)
        if not provider_model:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND,
                f"LLM provider '{request.provider}' not found",
            )
        user_group_ids = fetch_user_group_ids(db_session, user)
        if not can_user_access_llm_provider(
            provider_model,
            user_group_ids,
            persona,
            user.role == UserRole.ADMIN,
        ):
            raise OnyxError(OnyxErrorCode.UNAUTHORIZED)

        llm_provider_view = LLMProviderView.from_model(provider_model)
        llm = llm_from_provider(
            model_name=cast(str, request.model),
            llm_provider=llm_provider_view,
        )
    elif persona is not None:
        llm = get_llm_for_persona(persona, user)
    else:
        llm = get_default_llm()

    # Since the agentic search flow requires multiple LLM calls
    # we should check the tenant usage limits before continuing
    check_llm_cost_limit_for_provider(
        db_session=db_session,
        tenant_id=get_current_tenant_id(),
        llm_provider_api_key=llm.config.api_key,
    )

    # 3. Build filters. See SearchRequest.time_cutoff for the naive-→-UTC
    # contract; we apply it here so downstream comparison against tz-aware
    # document timestamps works.
    time_cutoff = request.time_cutoff
    if time_cutoff is not None and time_cutoff.tzinfo is None:
        time_cutoff = time_cutoff.replace(tzinfo=timezone.utc)

    base_filters = BaseFilters(
        source_type=request.sources,
        document_set=request.document_sets,
        time_cutoff=time_cutoff,
        tags=request.tags,
    )

    # 4. Get document index
    search_settings = get_current_search_settings(db_session)
    document_index = get_default_document_index(search_settings, None, db_session)

    # 5. Get tool_id
    all_tools = get_tools(db_session)
    tool_id = next(
        (tool.id for tool in all_tools if tool.in_code_tool_id == SEARCH_TOOL_ID),
        None,
    )
    if tool_id is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "Search tool not found in database",
        )

    # 6. Construct SearchTool
    search_tool = SearchTool(
        tool_id=tool_id,
        emitter=NullEmitter(),
        user=user,
        persona_search_info=persona_search_info,
        llm=llm,
        document_index=document_index,
        user_selected_filters=base_filters,
        project_id_filter=None,
        persona_id_filter=None,
        bypass_acl=False,
        slack_context=None,
        enable_slack_search=True,
    )

    # 7. Run search
    tool_response = search_tool.run(
        placement=Placement(turn_index=0),
        override_kwargs=SearchToolOverrideKwargs(
            starting_citation_num=1,
            original_query=request.query,
            skip_query_expansion=request.skip_query_expansion,
            include_link=True,
            message_history=request.message_history
            or [
                ChatMinimalTextMessage(
                    message=request.query,
                    message_type=MessageType.USER,
                ),
            ],
        ),
        queries=[request.query],
    )

    # 8. Map LLM-facing JSON entries to SearchResults (one per merged section).
    llm_facing_text = tool_response.llm_facing_response
    entries = json.loads(llm_facing_text)["results"] if llm_facing_text else []
    return SearchResponse(
        results=[
            SearchResult(
                citation_id=entry["document"],
                title=entry["title"],
                content=entry["content"],
                link=entry.get("url"),
                source_type=entry["source_type"],
                updated_at=entry.get("updated_at"),
            )
            for entry in entries
        ],
    )
