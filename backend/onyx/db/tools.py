from typing import Any, Type
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.auth.permissions import has_permission
from onyx.context.search.models import PersonaSearchInfo
from onyx.db.enums import MCPServerStatus, Permission, PermissionAuthority
from onyx.db.integration_policy import list_persona_plugin_links
from onyx.db.models import (
    MCPServer,
    Persona,
    Tool,
    User,
)
from onyx.integrations.policy import parse_action_settings
from onyx.server.features.tool.models import Header
from onyx.tools.built_in_tools import BUILT_IN_TOOL_TYPES
from onyx.tools.models import (
    PersonaToolConfiguration,
    PluginLinkConfiguration,
    ToolConfiguration,
)


def capture_persona_tool_configuration(
    persona: Persona, db_session: Session
) -> PersonaToolConfiguration:
    """Copies built-in tools and plugin links; the caller owns the session."""
    return PersonaToolConfiguration(
        persona_id=persona.id,
        persona_name=persona.name,
        tools=[
            ToolConfiguration.model_validate(tool)
            for tool in persona.tools
            if tool.in_code_tool_id is not None
        ],
        plugin_links=[
            PluginLinkConfiguration(
                plugin_id=link.plugin_id,
                action_settings=parse_action_settings(link.action_settings),
            )
            for link in list_persona_plugin_links(db_session, persona.id)
        ],
        search=PersonaSearchInfo(
            document_set_names=[item.name for item in persona.document_sets],
            search_start_date=persona.search_start_date,
            attached_document_ids=[item.id for item in persona.attached_documents],
            hierarchy_node_ids=[item.id for item in persona.hierarchy_nodes],
        ),
    )


def _openapi_tool_clause() -> ColumnElement[bool]:
    return and_(
        func.jsonb_typeof(Tool.openapi_schema) == "object",
        Tool.in_code_tool_id.is_(None),
        Tool.mcp_server_id.is_(None),
    )


def get_tools(
    db_session: Session,
    *,
    only_enabled: bool = False,
    only_connected_mcp: bool = False,
    only_openapi: bool = False,
) -> list[Tool]:
    query = select(Tool)

    if only_connected_mcp:
        # Keep tools that either:
        # 1. Don't have an MCP server (mcp_server_id IS NULL) - Non-MCP tools
        # 2. Have an MCP server that is connected - Connected MCP tools
        query = query.outerjoin(MCPServer, Tool.mcp_server_id == MCPServer.id).where(
            or_(
                Tool.mcp_server_id.is_(None),  # Non-MCP tools (built-in, custom)
                MCPServer.status == MCPServerStatus.CONNECTED,  # MCP tools connected
            )
        )

    if only_enabled:
        query = query.where(or_(Tool.enabled.is_(True), _openapi_tool_clause()))

    if only_openapi:
        query = query.where(_openapi_tool_clause())

    return list(db_session.scalars(query).all())


def get_tools_by_ids(tool_ids: list[int], db_session: Session) -> list[Tool]:
    if not tool_ids:
        return []
    stmt = select(Tool).where(Tool.id.in_(tool_ids))
    return list(db_session.scalars(stmt).all())


def can_manage_own_tool(user: User, tool: Tool) -> bool:
    """Owner-or-admin gate for every action on a custom action (edit, delete, toggle, OAuth
    config), matching the routes' ``allow_scope`` guard: a global actions-admin manages any
    action, a scoped manager only one they created. No MANAGE_ACTIONS authority — or a built-in
    tool (no owner) — never passes."""
    authority = has_permission(user, Permission.MANAGE_ACTIONS)
    if authority is PermissionAuthority.GLOBAL:
        return True
    if authority is PermissionAuthority.SCOPED:
        return tool.user_id is not None and tool.user_id == user.id
    return False


def can_manage_mcp_server(user: User, server: MCPServer) -> bool:
    """Owner-or-admin gate for every action on an MCP server (edit, delete, connect, status).
    Global MANAGE_ACTIONS manages any server — that permission is full-admin-equivalent for
    actions, so it isn't narrowed to FULL_ADMIN; a scoped manager only one they own."""
    authority = has_permission(user, Permission.MANAGE_ACTIONS)
    if authority is PermissionAuthority.GLOBAL:
        return True
    if authority is PermissionAuthority.SCOPED:
        return server.owner == user.email
    return False


def can_manage_tool(user: User, tool: Tool) -> bool:
    """The gate for every per-tool action (edit, delete, toggle, OAuth config). An MCP tool
    is created with ``user_id=None``, so its ownership lives on the server — without routing
    there, a server's owner could delete it but not disable one of its tools."""
    if tool.mcp_server is not None:
        return can_manage_mcp_server(user, tool.mcp_server)
    return can_manage_own_tool(user, tool)


def get_builtin_tool(
    db_session: Session,
    tool_type: Type[BUILT_IN_TOOL_TYPES],
) -> Tool:
    """
    Retrieves a built-in tool from the database based on the tool type.
    """
    # local import to avoid circular import. DB layer should not depend on tools layer.
    from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP

    tool_id = next(
        (
            in_code_tool_id
            for in_code_tool_id, tool_cls in BUILT_IN_TOOL_MAP.items()
            if tool_cls.__name__ == tool_type.__name__
        ),
        None,
    )

    if not tool_id:
        raise RuntimeError(
            f"Tool type {tool_type.__name__} not found in the BUILT_IN_TOOLS list."
        )

    db_tool = db_session.execute(
        select(Tool).where(Tool.in_code_tool_id == tool_id)
    ).scalar_one_or_none()

    if not db_tool:
        raise RuntimeError(f"Tool type {tool_type.__name__} not found in the database.")

    return db_tool


def get_tool_by_name(tool_name: str, db_session: Session) -> Tool:
    tool = db_session.scalar(select(Tool).where(Tool.name == tool_name))
    if not tool:
        raise ValueError("Tool by specified name does not exist")
    return tool


def create_tool__no_commit(
    name: str,
    description: str | None,
    openapi_schema: dict[str, Any] | None,
    custom_headers: list[Header] | None,
    user_id: UUID | None,
    db_session: Session,
    passthrough_auth: bool,
    *,
    mcp_server_id: int | None = None,
    oauth_config_id: int | None = None,
    enabled: bool = True,
) -> Tool:
    new_tool = Tool(
        name=name,
        description=description,
        in_code_tool_id=None,
        openapi_schema=openapi_schema,
        custom_headers=(
            [header.model_dump() for header in custom_headers] if custom_headers else []
        ),
        user_id=user_id,
        passthrough_auth=passthrough_auth,
        mcp_server_id=mcp_server_id,
        oauth_config_id=oauth_config_id,
        enabled=enabled,
    )
    db_session.add(new_tool)
    db_session.flush()  # Don't commit yet, let caller decide when to commit
    return new_tool
