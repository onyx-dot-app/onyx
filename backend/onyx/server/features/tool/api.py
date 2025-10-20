from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.schemas import UserRole
from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.db.tools import create_tool__no_commit
from onyx.db.tools import delete_tool__no_commit
from onyx.db.tools import get_tool_by_id
from onyx.db.tools import get_tools
from onyx.db.tools import update_tool
from onyx.server.features.tool.models import CustomToolCreate
from onyx.server.features.tool.models import CustomToolUpdate
from onyx.server.features.tool.models import ToolSnapshot
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


def _get_editable_custom_tool(
    tool_id: int, db_session: Session, user: User | None
) -> Tool:
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

    # Admins can always make changes; non-admins must own the tool.
    if not user or user.role == UserRole.ADMIN:
        return tool

    if tool.user_id is None or tool.user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only modify actions that you created.",
        )

    return tool


@admin_router.post("/custom")
def create_custom_tool(
    tool_data: CustomToolCreate,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_curator_or_admin_user),
) -> ToolSnapshot:
    _validate_tool_definition(tool_data.definition)
    _validate_auth_settings(tool_data)
    tool = create_tool__no_commit(
        name=tool_data.name,
        description=tool_data.description,
        openapi_schema=tool_data.definition,
        custom_headers=tool_data.custom_headers,
        user_id=user.id if user else None,
        db_session=db_session,
        passthrough_auth=tool_data.passthrough_auth,
        enabled=True,
    )
    db_session.commit()
    return ToolSnapshot.from_model(tool)


@admin_router.put("/custom/{tool_id}")
def update_custom_tool(
    tool_id: int,
    tool_data: CustomToolUpdate,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_curator_or_admin_user),
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
    )
    return ToolSnapshot.from_model(updated_tool)


@admin_router.delete("/custom/{tool_id}")
def delete_custom_tool(
    tool_id: int,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_curator_or_admin_user),
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


class ValidateToolRequest(BaseModel):
    definition: dict[str, Any]


class ValidateToolResponse(BaseModel):
    methods: list[MethodSpec]


@admin_router.post("/custom/validate")
def validate_tool(
    tool_data: ValidateToolRequest,
    _: User | None = Depends(current_curator_or_admin_user),
) -> ValidateToolResponse:
    _validate_tool_definition(tool_data.definition)
    method_specs = openapi_to_method_specs(tool_data.definition)
    return ValidateToolResponse(methods=method_specs)


"""Endpoints for all"""


@router.get("/{tool_id}")
def get_custom_tool(
    tool_id: int,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_user),
) -> ToolSnapshot:
    try:
        tool = get_tool_by_id(tool_id, db_session)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return ToolSnapshot.from_model(tool)


@router.get("")
def list_tools(
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_user),
) -> list[ToolSnapshot]:
    tools = get_tools(db_session, only_enabled=True)

    filtered_tools: list[ToolSnapshot] = []
    for tool in tools:
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
