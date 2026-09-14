from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from onyx.auth.permissions import has_global_permission
from onyx.chat.emitter import NullEmitter
from onyx.context.search.models import PersonaSearchInfo
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.llm import (
    can_user_access_llm_provider,
    fetch_existing_llm_provider,
    fetch_user_group_ids,
)
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.search_settings import get_current_search_settings
from onyx.db.tools import get_tools
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.factory import get_default_llm, get_llm_for_persona, llm_from_provider
from onyx.llm.interfaces import LLM
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.usage_limits import check_llm_cost_limit_for_provider
from onyx.tools.constants import SEARCH_TOOL_ID
from onyx.tools.interface import Tool
from onyx.tools.tool_constructor import construct_tools
from shared_configs.contextvars import get_current_tenant_id


class PreparedHarness(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    llm: LLM
    index: DocumentIndex
    persona: PersonaSearchInfo
    search_tool_id: int
    external_tools: list[Tool] = []


def prepare_harness(
    user: User,
    provider_name: str | None,
    model_name: str | None,
    persona_id: int | None,
    include_persona_tools: bool,
) -> PreparedHarness:
    with get_session_with_current_tenant() as session:
        persona = None
        if persona_id is not None:
            try:
                persona = get_persona_by_id(
                    persona_id, user, session, is_for_edit=False
                )
            except ValueError as exc:
                raise OnyxError(OnyxErrorCode.PERSONA_NOT_FOUND) from exc
            session.refresh(
                persona,
                attribute_names=[
                    "tools",
                    "document_sets",
                    "attached_documents",
                    "hierarchy_nodes",
                ],
            )
        if provider_name:
            provider = fetch_existing_llm_provider(provider_name, session)
            if provider is None:
                raise OnyxError(OnyxErrorCode.NOT_FOUND, "Model provider not found")
            if not can_user_access_llm_provider(
                provider,
                fetch_user_group_ids(session, user),
                persona,
                has_global_permission(user, Permission.MANAGE_LLMS),
            ):
                raise OnyxError(OnyxErrorCode.UNAUTHORIZED)
            if model_name is None:
                raise OnyxError(OnyxErrorCode.BAD_REQUEST, "Model name required")
            llm = llm_from_provider(
                model_name=model_name, llm_provider=LLMProviderView.from_model(provider)
            )
        elif persona is not None:
            llm = get_llm_for_persona(persona, user)
        else:
            llm = get_default_llm()
        check_llm_cost_limit_for_provider(
            db_session=session,
            tenant_id=get_current_tenant_id(),
            llm_provider_api_key=llm.config.api_key,
        )
        settings = get_current_search_settings(session)
        index = get_default_document_index(settings, None, session)
        search_id = next(
            (t.id for t in get_tools(session) if t.in_code_tool_id == SEARCH_TOOL_ID),
            None,
        )
        if search_id is None:
            raise OnyxError(
                OnyxErrorCode.NOT_FOUND, "Internal search tool is unavailable"
            )
        scope = PersonaSearchInfo(
            document_set_names=[d.name for d in persona.document_sets]
            if persona
            else [],
            search_start_date=persona.search_start_date if persona else None,
            attached_document_ids=[d.id for d in persona.attached_documents]
            if persona
            else [],
            hierarchy_node_ids=[n.id for n in persona.hierarchy_nodes]
            if persona
            else [],
        )
        external_tools: list[Tool] = []
        if include_persona_tools and persona is not None:
            allowed_ids = [
                t.id
                for t in persona.tools
                if t.enabled and (t.mcp_server_id or t.openapi_schema)
            ]
            if allowed_ids:
                constructed = construct_tools(
                    persona=persona,
                    emitter=NullEmitter(),
                    user=user,
                    llm=llm,
                    db_session=session,
                    allowed_tool_ids=allowed_ids,
                )
                external_tools = [
                    tool
                    for tool_id, tools in constructed.items()
                    if tool_id in allowed_ids
                    for tool in tools
                ]
        return PreparedHarness(
            llm=llm,
            index=index,
            persona=scope,
            search_tool_id=search_id,
            external_tools=external_tools,
        )


def document_read_filters(user: User, selected_filters):
    """Fresh ACL and tenant checks for reading an already-cited document."""
    from onyx.context.search.models import IndexFilters
    from onyx.context.search.preprocessing.access_filters import (
        build_access_filters_for_user,
    )

    with get_session_with_current_tenant() as session:
        acl = build_access_filters_for_user(user, session)
    return IndexFilters(
        **(selected_filters.model_dump() if selected_filters is not None else {}),
        access_control_list=acl,
        tenant_id=get_current_tenant_id(),
    )
