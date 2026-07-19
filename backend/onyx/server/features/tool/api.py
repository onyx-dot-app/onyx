from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permissions import get_effective_permissions
from onyx.auth.permissions import has_permission
from onyx.auth.permissions import require_permission
from onyx.auth.scoped_permissions import agent_mediated_scope_allows
from onyx.configs.constants import PUBLIC_API_TAGS
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.enums import PermissionAuthority
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.db.tools import create_tool__no_commit
from onyx.db.tools import delete_tool__no_commit
from onyx.db.tools import get_action_agent_scope
from onyx.db.tools import get_tool_by_id
from onyx.db.tools import get_tools
from onyx.db.tools import get_tools_by_ids
from onyx.db.tools import update_tool
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.tool.models import CustomToolCreate
from onyx.server.features.tool.models import CustomToolUpdate
from onyx.server.features.tool.models import ToolSnapshot
from onyx.server.features.tool.tool_visibility import should_expose_tool_to_fe
from onyx.tools.built_in_tools import get_built_in_tool_by_id
from onyx.tools.tool_implementations.custom.openapi_parsing import MethodSpec
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    openapi_to_method_specs,
)
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    validate_openapi_schema,
)

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


def _assert_action_within_managed_scope(
    tool_id: int, db_session: Session, user: User
) -> None:
    """A scoped group manager may edit an action only when every agent using it is
    private and in a group they manage. An action reachable via a public agent (so
    org-wide), or used by no agent (no group context), is owner/admin-only."""
    group_ids, has_public_agent, has_ungrouped_private_agent = get_action_agent_scope(
        tool_id, db_session
    )
    if not agent_mediated_scope_allows(
        user,
        db_session,
        group_ids=group_ids,
        has_public_agent=has_public_agent,
        has_ungrouped_private_agent=has_ungrouped_private_agent,
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "You can only modify actions scoped to groups you manage.",
        )


def _get_editable_custom_tool(tool_id: int, db_session: Session, user: User) -> Tool:
    """Fetch a custom tool and ensure the caller has permission to edit it."""
    try:
        tool = get_tool_by_id(tool_id, db_session)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if tool.in_code_tool_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Built-in tools cannot be modified through this endpoint.",
        )

    # Admins bypass; owners may always edit the action they created.
    if Permission.FULL_ADMIN_PANEL_ACCESS in get_effective_permissions(user):
        return tool
    if tool.user_id is not None and tool.user_id == user.id:
        return tool

    # A scoped group manager may edit an action scoped (via its agents) to groups
    # they manage; everyone else is limited to actions they created.
    if has_permission(user, Permission.MANAGE_ACTIONS) is PermissionAuthority.SCOPED:
        _assert_action_within_managed_scope(tool_id, db_session, user)
        return tool

    raise OnyxError(
        OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
        "You can only modify actions that you created.",
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
    tool = create_tool__no_commit(
        name=tool_data.name,
        description=tool_data.description,
        openapi_schema=tool_data.definition,
        custom_headers=tool_data.custom_headers,
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
    existing_tool = _get_editable_custom_tool(tool_id, db_session, user)
    if tool_data.definition:
        _validate_tool_definition(tool_data.definition)
    _validate_auth_settings(tool_data)
    updated_tool = update_tool(
        tool_id=tool_id,
        name=tool_data.name,
        description=tool_data.description,
        openapi_schema=tool_data.definition,
        custom_headers=tool_data.custom_headers,
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
    user: User = Depends(require_permission(Permission.MANAGE_ACTIONS)),
) -> None:
    _ = _get_editable_custom_tool(tool_id, db_session, user)
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
    user: User = Depends(require_permission(Permission.MANAGE_ACTIONS)),  # noqa: ARG001
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


@router.get("/openapi", tags=PUBLIC_API_TAGS)
def list_openapi_tools(
    db_session: Session = Depends(get_session),
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> list[ToolSnapshot]:
    tools = get_tools(db_session, only_openapi=True)

    openapi_tools: list[ToolSnapshot] = []
    for tool in tools:
        if not should_expose_tool_to_fe(tool):
            continue

        openapi_tools.append(ToolSnapshot.from_model(tool))

    return openapi_tools


@router.get("/{tool_id}", tags=PUBLIC_API_TAGS)
def get_custom_tool(
    tool_id: int,
    db_session: Session = Depends(get_session),
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> ToolSnapshot:
    try:
        tool = get_tool_by_id(tool_id, db_session)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ToolSnapshot.from_model(tool)


@router.get("", tags=PUBLIC_API_TAGS)
def list_tools(
    db_session: Session = Depends(get_session),
    _: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> list[ToolSnapshot]:
    tools = get_tools(db_session, only_enabled=True, only_connected_mcp=True)

    filtered_tools: list[ToolSnapshot] = []
    for tool in tools:
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
