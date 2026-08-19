from collections.abc import Collection
from typing import TYPE_CHECKING, Any, Type, cast
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from onyx.auth.permissions import has_permission
from onyx.db.constants import UNSET, UnsetType
from onyx.db.enums import MCPServerStatus, Permission, PermissionAuthority
from onyx.db.models import (
    MCPServer,
    OAuthConfig,
    Persona,
    Persona__Tool,
    Persona__UserGroup,
    Tool,
    ToolCall,
    User,
)
from onyx.server.features.tool.models import Header
from onyx.tools.built_in_tools import BUILT_IN_TOOL_TYPES
from onyx.utils.headers import HeaderItemDict
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_json_like, sanitize_string

if TYPE_CHECKING:
    pass

logger = setup_logger()


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
        query = query.where(Tool.enabled.is_(True))

    if only_openapi:
        query = query.where(
            Tool.openapi_schema.is_not(None),
            # To avoid showing rows that have JSON literal `null` stored in the column to the user.
            # tools from mcp servers will not have an openapi schema but it has `null`, so we need to exclude them.
            func.jsonb_typeof(Tool.openapi_schema) == "object",
            # Exclude built-in tools that happen to have an openapi_schema
            Tool.in_code_tool_id.is_(None),
        )

    return list(db_session.scalars(query).all())


def get_tools_by_mcp_server_id(
    mcp_server_id: int,
    db_session: Session,
    *,
    only_enabled: bool = False,
    order_by_id: bool = False,
) -> list[Tool]:
    query = select(Tool).where(Tool.mcp_server_id == mcp_server_id)
    if only_enabled:
        query = query.where(Tool.enabled.is_(True))
    if order_by_id:
        query = query.order_by(Tool.id)
    return list(db_session.scalars(query).all())


def get_tools_by_ids(tool_ids: list[int], db_session: Session) -> list[Tool]:
    if not tool_ids:
        return []
    stmt = select(Tool).where(Tool.id.in_(tool_ids))
    return list(db_session.scalars(stmt).all())


def get_tool_by_id(tool_id: int, db_session: Session) -> Tool:
    tool = db_session.scalar(select(Tool).where(Tool.id == tool_id))
    if not tool:
        raise ValueError("Tool by specified id does not exist")
    return tool


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


def can_link_oauth_config(
    user: User, oauth_config_id: int, db_session: Session
) -> bool:
    """Whether an action may point at this OAuth config. A global actions-admin links any; a
    scoped manager only one no other creator's action already uses — the config holds shared
    client credentials, and ``_assert_can_manage_oauth_config`` derives ownership from exactly
    these referencing actions, so linking in would grant both."""
    authority = has_permission(user, Permission.MANAGE_ACTIONS)
    if authority is PermissionAuthority.GLOBAL:
        return True
    if authority is not PermissionAuthority.SCOPED:
        return False
    # Vacuously true when nothing references it yet — an unreferenced config has no owner,
    # and this is the create-config-then-link flow.
    return all(
        owner_id == user.id
        for owner_id in db_session.scalars(
            select(Tool.user_id).where(Tool.oauth_config_id == oauth_config_id)
        )
    )


def _connected_to_groups_stmt(
    column: InstrumentedAttribute[Any], group_ids: Collection[int]
) -> Select[tuple[Any]]:
    """Tools an agent in ``group_ids`` uses — one shared to or owned by the group. An action
    has no group of its own, so an agent is the only path from a group to one."""
    return (
        select(column)
        .join(Persona__Tool, Persona__Tool.tool_id == Tool.id)
        .join(Persona, Persona.id == Persona__Tool.persona_id)
        .outerjoin(Persona__UserGroup, Persona__UserGroup.persona_id == Persona.id)
        .where(
            Persona.deleted.is_(False),
            or_(
                Persona__UserGroup.user_group_id.in_(group_ids),
                Persona.owner_group_id.in_(group_ids),
            ),
        )
    )


def get_mcp_server_ids_connected_to_groups(
    group_ids: Collection[int], db_session: Session
) -> set[int]:
    """MCP server ids reachable from ``group_ids``. A scoped manager may view these without
    managing them."""
    if not group_ids:
        return set()
    rows = db_session.execute(
        _connected_to_groups_stmt(Tool.mcp_server_id, group_ids).where(
            Tool.mcp_server_id.is_not(None)
        )
    ).all()
    return {server_id for (server_id,) in rows if server_id is not None}


def get_tool_ids_connected_to_groups(
    group_ids: Collection[int], db_session: Session
) -> set[int]:
    if not group_ids:
        return set()
    rows = db_session.execute(_connected_to_groups_stmt(Tool.id, group_ids)).all()
    return {tool_id for (tool_id,) in rows}


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


def update_tool(
    tool_id: int,
    name: str | None,
    description: str | None,
    openapi_schema: dict[str, Any] | None,
    custom_headers: list[Header] | None,
    user_id: UUID | None,
    db_session: Session,
    passthrough_auth: bool | None,
    oauth_config_id: int | None | UnsetType = UNSET,
) -> Tool:
    tool = get_tool_by_id(tool_id, db_session)
    if tool is None:
        raise ValueError(f"Tool with ID {tool_id} does not exist")

    if name is not None:
        tool.name = name
    if description is not None:
        tool.description = description
    if openapi_schema is not None:
        tool.openapi_schema = openapi_schema
    if user_id is not None:
        tool.user_id = user_id
    if custom_headers is not None:
        tool.custom_headers = [
            cast(HeaderItemDict, header.model_dump()) for header in custom_headers
        ]
    if passthrough_auth is not None:
        tool.passthrough_auth = passthrough_auth
    old_oauth_config_id = tool.oauth_config_id
    if not isinstance(oauth_config_id, UnsetType):
        tool.oauth_config_id = oauth_config_id
        db_session.flush()

    # Clean up orphaned OAuthConfig if the oauth_config_id was changed
    if (
        old_oauth_config_id is not None
        and not isinstance(oauth_config_id, UnsetType)
        and old_oauth_config_id != oauth_config_id
    ):
        other_tools = db_session.scalars(
            select(Tool).where(Tool.oauth_config_id == old_oauth_config_id)
        ).all()
        if not other_tools:
            oauth_config = db_session.get(OAuthConfig, old_oauth_config_id)
            if oauth_config:
                db_session.delete(oauth_config)

    db_session.commit()
    return tool


def delete_tool__no_commit(tool_id: int, db_session: Session) -> None:
    tool = get_tool_by_id(tool_id, db_session)
    if tool is None:
        raise ValueError(f"Tool with ID {tool_id} does not exist")

    oauth_config_id = tool.oauth_config_id

    db_session.delete(tool)
    db_session.flush()

    # Clean up orphaned OAuthConfig if no other tools reference it
    if oauth_config_id is not None:
        other_tools = db_session.scalars(
            select(Tool).where(Tool.oauth_config_id == oauth_config_id)
        ).all()
        if not other_tools:
            oauth_config = db_session.get(OAuthConfig, oauth_config_id)
            if oauth_config:
                db_session.delete(oauth_config)
                db_session.flush()


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


def create_tool_call_no_commit(
    chat_session_id: UUID,
    parent_chat_message_id: int | None,
    turn_number: int,
    tool_id: int,
    tool_call_id: str,
    tool_call_arguments: dict[str, Any],
    tool_call_response: Any,
    tool_call_tokens: int,
    db_session: Session,
    *,
    parent_tool_call_id: int | None = None,
    reasoning_tokens: str | None = None,
    generated_images: list[dict] | None = None,
    tab_index: int = 0,
    add_only: bool = True,
) -> ToolCall:
    """
    Create a ToolCall entry in the database.

    Args:
        chat_session_id: The chat session ID
        parent_chat_message_id: The parent chat message ID
        turn_number: The turn number for this tool call
        tool_id: The tool ID
        tool_call_id: The tool call ID (string identifier from LLM)
        tool_call_arguments: The tool call arguments
        tool_call_response: The tool call response
        tool_call_tokens: The number of tokens in the tool call arguments
        db_session: The database session
        parent_tool_call_id: Optional parent tool call ID (for nested tool calls)
        reasoning_tokens: Optional reasoning tokens
        generated_images: Optional list of generated image metadata for replay
        tab_index: Index order of tool calls from the LLM for parallel tool calls
        commit: If True, commit the transaction; if False, flush only

    Returns:
        The created ToolCall object
    """
    tool_call = ToolCall(
        chat_session_id=chat_session_id,
        parent_chat_message_id=parent_chat_message_id,
        parent_tool_call_id=parent_tool_call_id,
        turn_number=turn_number,
        tab_index=tab_index,
        tool_id=tool_id,
        tool_call_id=tool_call_id,
        reasoning_tokens=(
            sanitize_string(reasoning_tokens) if reasoning_tokens else reasoning_tokens
        ),
        tool_call_arguments=sanitize_json_like(tool_call_arguments),
        tool_call_response=sanitize_json_like(tool_call_response),
        tool_call_tokens=tool_call_tokens,
        generated_images=sanitize_json_like(generated_images),
    )

    db_session.add(tool_call)
    if not add_only:
        db_session.add(tool_call)
    else:
        db_session.flush()
    return tool_call
