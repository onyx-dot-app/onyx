from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permission_projection import tool_permissions
from onyx.auth.permissions import has_permission, require_permission
from onyx.auth.scoped_permissions import get_scoped_groups
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission, PermissionAuthority
from onyx.db.mcp import get_mcp_servers_accessible_to_user
from onyx.db.models import Tool, User
from onyx.db.oauth_config import get_oauth_config
from onyx.db.persona import get_tool_ids_on_editable_personas
from onyx.db.tools import (
    can_link_oauth_config,
    can_manage_tool,
    create_tool__no_commit,
    delete_tool__no_commit,
    get_tool_by_id,
    get_tool_ids_connected_to_groups,
    get_tools,
    get_tools_by_ids,
    update_tool,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.tool.models import (
    CustomToolCreate,
    CustomToolUpdate,
    Header,
    ToolSnapshot,
)
from onyx.server.features.tool.tool_visibility import should_expose_tool_to_fe
from onyx.tools.built_in_tools import get_built_in_tool_by_id
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    MethodSpec,
    openapi_to_method_specs,
    validate_openapi_schema,
)
from onyx.utils.encryption import is_masked_credential

router = APIRouter(prefix="/tool")
admin_router = APIRouter(prefix="/admin/tool")


def _validate_tool_definition(definition: dict[str, Any]) -> None:
    try:
        validate_openapi_schema(definition)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


def _validate_auth_settings(tool_data: CustomToolCreate | CustomToolUpdate) -> None:
    if tool_data.passthrough_auth and tool_data.custom_headers:
        for header in tool_data.custom_headers:
            if header.key.lower() == "authorization":
                raise HTTPException(
                    status_code=400,
                    detail="Cannot use passthrough auth with custom authorization headers",
                )


def _resolve_masked_headers(
    headers: list[Header] | None, stored: list[Any] | None
) -> list[Header] | None:
    """Restore header values the caller echoed back masked.

    Reads mask header values, and the admin UI round-trips whatever it read, so
    a masked value means "keep the stored one". A caller rotating to a value
    that equals the stored mask exactly is read as an unchanged echo; only a
    changed-flag on the request could separate the two.
    """
    if not headers:
        return headers

    stored_by_key = {
        item["key"]: item["value"]
        for item in (stored or [])
        if isinstance(item, dict) and isinstance(item.get("value"), str)
    }

    resolved: list[Header] = []
    for header in headers:
        if not is_masked_credential(header.value):
            resolved.append(header)
            continue
        stored_value = stored_by_key.get(header.key)
        if stored_value is None:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Header '{header.key}' was sent as a masked placeholder but has "
                "no stored value to keep. Send the actual header value.",
            )
        resolved.append(Header(key=header.key, value=stored_value))
    return resolved


def _get_manageable_custom_tool(tool_id: int, db_session: Session, user: User) -> Tool:
    """Fetch a custom tool and assert the caller may manage it (owner or admin) — the gate for
    every action on it: edit, delete, toggle, and OAuth config."""
    try:
        tool = get_tool_by_id(tool_id, db_session)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if tool.in_code_tool_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Built-in tools cannot be modified through this endpoint.",
        )
    if not can_manage_tool(user, tool):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "You can only manage actions you created, or ones belonging to an "
            "MCP server you own.",
        )
    return tool


def _assert_can_link_oauth_config(
    oauth_config_id: int | None,
    db_session: Session,
    user: User,
    current_oauth_config_id: int | None = None,
) -> None:
    """GATE 2 for the OAuth config an action points at — the route's own gate only covers
    the action itself. Authorizes the *change*: re-sending the config the action already
    uses is no new link, so an admin sharing one across creators can't lock them out of
    ordinary edits (the editor round-trips the id on every save)."""
    if oauth_config_id is None or oauth_config_id == current_oauth_config_id:
        return
    # Before asking who references it, establish it exists: an unknown id has no referencing
    # actions, so the gate would pass it through to the FK and surface as a 500.
    if get_oauth_config(oauth_config_id, db_session) is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"OAuth config with id {oauth_config_id} not found",
        )
    if not can_link_oauth_config(user, oauth_config_id, db_session):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "You can only use OAuth configurations that no other creator's action uses.",
        )


@admin_router.post("/custom", tags=PUBLIC_API_TAGS)
def create_custom_tool(
    tool_data: CustomToolCreate,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> ToolSnapshot:
    _validate_tool_definition(tool_data.definition)
    _validate_auth_settings(tool_data)
    _assert_can_link_oauth_config(tool_data.oauth_config_id, db_session, user)
    custom_headers = _resolve_masked_headers(tool_data.custom_headers, None)
    tool = create_tool__no_commit(
        name=tool_data.name,
        description=tool_data.description,
        openapi_schema=tool_data.definition,
        custom_headers=custom_headers,
        user_id=user.id,
        db_session=db_session,
        passthrough_auth=tool_data.passthrough_auth,
        oauth_config_id=tool_data.oauth_config_id,
        enabled=True,
    )
    db_session.commit()
    return ToolSnapshot.from_model(tool)


@admin_router.put("/custom/{tool_id}", tags=PUBLIC_API_TAGS)
def update_custom_tool(
    tool_id: int,
    tool_data: CustomToolUpdate,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> ToolSnapshot:
    existing_tool = _get_manageable_custom_tool(tool_id, db_session, user)
    if tool_data.definition:
        _validate_tool_definition(tool_data.definition)
    _validate_auth_settings(tool_data)
    _assert_can_link_oauth_config(
        tool_data.oauth_config_id,
        db_session,
        user,
        current_oauth_config_id=existing_tool.oauth_config_id,
    )
    updated_tool = update_tool(
        tool_id=tool_id,
        name=tool_data.name,
        description=tool_data.description,
        openapi_schema=tool_data.definition,
        custom_headers=_resolve_masked_headers(
            tool_data.custom_headers, existing_tool.custom_headers
        ),
        user_id=existing_tool.user_id,
        db_session=db_session,
        passthrough_auth=tool_data.passthrough_auth,
        oauth_config_id=tool_data.oauth_config_id,
    )
    return ToolSnapshot.from_model(updated_tool)


@admin_router.delete("/custom/{tool_id}", tags=PUBLIC_API_TAGS)
def delete_custom_tool(
    tool_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> None:
    _ = _get_manageable_custom_tool(tool_id, db_session, user)
    try:
        delete_tool__no_commit(tool_id, db_session)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # handles case where tool is still used by an Assistant
        raise HTTPException(status_code=400, detail=str(e))
    db_session.commit()


class ToolStatusUpdateRequest(BaseModel):
    tool_ids: list[int]
    enabled: bool


class ToolStatusUpdateResponse(BaseModel):
    updated_count: int
    tool_ids: list[int]


@admin_router.patch("/status")
def update_tools_status(
    update_data: ToolStatusUpdateRequest,
    db_session: Session = Depends(get_session),
    user: User = Depends(
        require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)
    ),
) -> ToolStatusUpdateResponse:
    """Enable or disable one or more tools.

    Pass a single tool ID in the list to update one tool, or multiple IDs for
    bulk updates.
    """
    if not update_data.tool_ids:
        raise HTTPException(status_code=400, detail="No tool IDs provided")

    tools = get_tools_by_ids(update_data.tool_ids, db_session)
    tools_by_id = {tool.id: tool for tool in tools}

    updated_tools = []
    missing_tools = []

    for tool_id in update_data.tool_ids:
        tool = tools_by_id.get(tool_id)
        if tool:
            if not can_manage_tool(user, tool):
                raise OnyxError(
                    OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                    "You can only enable or disable actions you created, or ones "
                    "belonging to an MCP server you own.",
                )
            tool.enabled = update_data.enabled
            updated_tools.append(tool_id)
        else:
            missing_tools.append(tool_id)

    if missing_tools:
        raise HTTPException(
            status_code=404, detail=f"Tools with IDs {missing_tools} not found"
        )

    db_session.commit()

    return ToolStatusUpdateResponse(
        updated_count=len(updated_tools),
        tool_ids=updated_tools,
    )


class ValidateToolRequest(BaseModel):
    definition: dict[str, Any]


class ValidateToolResponse(BaseModel):
    methods: list[MethodSpec]


@admin_router.post("/custom/validate", tags=PUBLIC_API_TAGS)
def validate_tool(
    tool_data: ValidateToolRequest,
    _: User = Depends(require_permission(Permission.MANAGE_ACTIONS, allow_scope=True)),
) -> ValidateToolResponse:
    _validate_tool_definition(tool_data.definition)
    method_specs = openapi_to_method_specs(tool_data.definition)
    return ValidateToolResponse(methods=method_specs)


"""Endpoints for all"""


def _connected_tool_ids(user: User, db_session: Session) -> set[int]:
    """Tools viewable without managing them — including those on agents the user can
    edit, since the editor rebuilds tool_ids from this and drops whatever it never saw."""
    # global holders need no set — can_manage_tool passes them before this is read
    if has_permission(user, Permission.MANAGE_ACTIONS) is PermissionAuthority.GLOBAL:
        return set()
    return get_tool_ids_connected_to_groups(
        get_scoped_groups(user, db_session, Permission.MANAGE_ACTIONS), db_session
    ) | get_tool_ids_on_editable_personas(user, db_session)


def _may_view_tool(tool: Tool, user: User, connected_tool_ids: set[int]) -> bool:
    """Read gate for the management surfaces: can_manage_tool covers admin, creator and MCP
    server owner; the connected set adds what a manager sees without owning."""
    if tool.in_code_tool_id is not None:
        return True
    return can_manage_tool(user, tool) or tool.id in connected_tool_ids


@router.get("/openapi", tags=PUBLIC_API_TAGS)
def list_openapi_tools(
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> list[ToolSnapshot]:
    tools = get_tools(db_session, only_openapi=True)
    connected_tool_ids = _connected_tool_ids(user, db_session)

    openapi_tools: list[ToolSnapshot] = []
    for tool in tools:
        if not should_expose_tool_to_fe(tool):
            continue
        if not _may_view_tool(tool, user, connected_tool_ids):
            continue

        openapi_tools.append(
            ToolSnapshot.from_model(
                tool,
                permissions=tool_permissions(can_manage=can_manage_tool(user, tool)),
            )
        )

    return openapi_tools


@router.get("/{tool_id}", tags=PUBLIC_API_TAGS)
def get_custom_tool(
    tool_id: int,
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> ToolSnapshot:
    try:
        tool = get_tool_by_id(tool_id, db_session)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    if not _may_view_tool(tool, user, _connected_tool_ids(user, db_session)):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "You can only view actions you manage, or ones an agent in your groups uses.",
        )
    return ToolSnapshot.from_model(tool)


@router.get("", tags=PUBLIC_API_TAGS)
def list_tools(
    db_session: Session = Depends(get_session),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> list[ToolSnapshot]:
    tools = get_tools(db_session, only_enabled=True, only_connected_mcp=True)

    # Attach catalog: omit MCP tools the user cannot put on a persona.
    accessible_mcp_server_ids = {
        server.id for server in get_mcp_servers_accessible_to_user(user, db_session)
    }

    filtered_tools: list[ToolSnapshot] = []
    for tool in tools:
        if (
            tool.mcp_server_id is not None
            and tool.mcp_server_id not in accessible_mcp_server_ids
        ):
            continue
        if not should_expose_tool_to_fe(tool):
            continue

        # Check if it's a built-in tool and if it's available
        if tool.in_code_tool_id:
            try:
                tool_cls = get_built_in_tool_by_id(tool.in_code_tool_id)
                if not tool_cls.is_available(db_session):
                    continue
            except KeyError:
                # If tool ID not found in registry, include it by default
                pass

        # All custom tools and available built-in tools are included
        filtered_tools.append(ToolSnapshot.from_model(tool))

    return filtered_tools
