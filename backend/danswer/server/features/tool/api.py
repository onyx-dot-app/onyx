from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.auth.users import current_user
from danswer.db.engine import get_session
from danswer.db.models import User
from danswer.db.tools import create_tool
from danswer.db.tools import delete_tool
from danswer.db.tools import get_tool_by_id
from danswer.db.tools import get_tools
from danswer.db.tools import update_tool
from danswer.server.features.tool.models import ToolSnapshot
from danswer.tools.custom.openapi_parsing import MethodSpec
from danswer.tools.custom.openapi_parsing import openapi_to_method_specs
from danswer.tools.custom.openapi_parsing import validate_openapi_schema

router = APIRouter(prefix="/tool")
admin_router = APIRouter(prefix="/admin/tool")


class CustomToolCreate(BaseModel):
    name: str
    description: str | None
    definition: dict[str, Any]


class CustomToolUpdate(BaseModel):
    name: str | None
    description: str | None
    definition: dict[str, Any] | None


def _validate_tool_definition(definition: dict[str, Any]) -> None:
    try:
        validate_openapi_schema(definition)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@admin_router.post("/custom")
def create_custom_tool(
    tool_data: CustomToolCreate,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_admin_user),
) -> ToolSnapshot:
    _validate_tool_definition(tool_data.definition)
    tool = create_tool(
        name=tool_data.name,
        description=tool_data.description,
        openapi_schema=tool_data.definition,
        user_id=user.id if user else None,
        db_session=db_session,
    )
    return ToolSnapshot.from_model(tool)


@admin_router.put("/custom/{tool_id}")
def update_custom_tool(
    tool_id: int,
    tool_data: CustomToolUpdate,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_admin_user),
) -> ToolSnapshot:
    if tool_data.definition:
        _validate_tool_definition(tool_data.definition)
    updated_tool = update_tool(
        tool_id=tool_id,
        name=tool_data.name,
        description=tool_data.description,
        openapi_schema=tool_data.definition,
        user_id=user.id if user else None,
        db_session=db_session,
    )
    return ToolSnapshot.from_model(updated_tool)


@admin_router.delete("/custom/{tool_id}")
def delete_custom_tool(
    tool_id: int,
    db_session: Session = Depends(get_session),
    _: User | None = Depends(current_admin_user),
) -> None:
    try:
        delete_tool(tool_id, db_session)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        # handles case where tool is still used by an Assistant
        raise HTTPException(status_code=400, detail=str(e))


class ValidateToolRequest(BaseModel):
    definition: dict[str, Any]


class ValidateToolResponse(BaseModel):
    methods: list[MethodSpec]


@admin_router.post("/custom/validate")
def validate_tool(
    tool_data: ValidateToolRequest,
    _: User | None = Depends(current_admin_user),
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
    tools = get_tools(db_session)
    return [ToolSnapshot.from_model(tool) for tool in tools]
