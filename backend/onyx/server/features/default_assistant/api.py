"""API endpoints for default assistant configuration."""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import Tool as ToolDBModel
from onyx.db.models import User
from onyx.db.persona import get_default_assistant
from onyx.db.persona import update_default_assistant_configuration
from onyx.server.features.default_assistant.models import AvailableTool
from onyx.server.features.default_assistant.models import DefaultAssistantConfiguration
from onyx.server.features.default_assistant.models import DefaultAssistantUpdateRequest
from onyx.tools.built_in_tools import get_built_in_tool_by_id
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.web_search.web_search_tool import (
    WebSearchTool,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/admin/default-assistant")


@router.get("/configuration")
def get_default_assistant_configuration(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> DefaultAssistantConfiguration:
    """Get the current default assistant configuration.

    Returns:
        DefaultAssistantConfiguration with current tool IDs and system prompt
    """
    persona = get_default_assistant(db_session)
    if not persona:
        raise HTTPException(status_code=404, detail="Default assistant not found")

    # Extract DB tool IDs from the persona's tools
    tool_ids = [tool.id for tool in persona.tools]

    return DefaultAssistantConfiguration(
        tool_ids=tool_ids,
        system_prompt=persona.system_prompt or "",
    )


@router.patch("")
def update_default_assistant(
    update_request: DefaultAssistantUpdateRequest,
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> DefaultAssistantConfiguration:
    """Update the default assistant configuration.

    Args:
        update_request: Request with optional tool_ids and system_prompt

    Returns:
        Updated DefaultAssistantConfiguration

    Raises:
        400: If invalid tool IDs are provided
        404: If default assistant not found
    """
    # Validate tool IDs if provided
    try:
        # Update the default assistant
        updated_persona = update_default_assistant_configuration(
            db_session=db_session,
            tool_ids=update_request.tool_ids,
            system_prompt=update_request.system_prompt,
        )

        # Return the updated configuration
        tool_ids = [tool.id for tool in updated_persona.tools]
        return DefaultAssistantConfiguration(
            tool_ids=tool_ids,
            system_prompt=updated_persona.system_prompt or "",
        )

    except ValueError as e:
        if "Default assistant not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/available-tools")
def list_available_tools(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[AvailableTool]:
    """List available built-in tools that can be enabled for the default assistant."""
    tools = (
        db_session.query(ToolDBModel)
        .filter(ToolDBModel.in_code_tool_id.isnot(None))
        .all()
    )
    ORDERED_TOOL_IDS = [
        SearchTool.__name__,
        WebSearchTool.__name__,
        ImageGenerationTool.__name__,
    ]
    tool_by_in_code_id = {
        tool.in_code_tool_id: tool
        for tool in tools
        if tool.in_code_tool_id in ORDERED_TOOL_IDS
    }
    ordered_tools = [
        tool_by_in_code_id[t] for t in ORDERED_TOOL_IDS if t in tool_by_in_code_id
    ]

    # Use the same approach as tools/api.py - check tool's is_available method
    def _is_available(in_code_id: str) -> bool:
        try:
            tool_cls = get_built_in_tool_by_id(in_code_id)
            return tool_cls.is_available(db_session)
        except KeyError:
            # If tool ID not found in registry, include it by default
            return True

    return [
        AvailableTool(
            id=tool.id,
            in_code_tool_id=tool.in_code_tool_id or "",
            display_name=tool.display_name or tool.name,
            description=tool.description or "",
            is_available=_is_available(tool.in_code_tool_id or ""),
        )
        for tool in ordered_tools
    ]
