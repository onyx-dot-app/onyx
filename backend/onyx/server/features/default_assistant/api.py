"""API endpoints for default assistant configuration."""

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.persona import get_default_assistant
from onyx.db.persona import update_default_assistant_configuration
from onyx.server.features.default_assistant.models import DefaultAssistantConfiguration
from onyx.server.features.default_assistant.models import DefaultAssistantUpdateRequest
from onyx.server.features.default_assistant.models import VALID_BUILTIN_TOOL_IDS
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

    # Extract tool IDs from the persona's tools
    tool_ids = [tool.name for tool in persona.tools]

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
    if update_request.tool_ids is not None:
        invalid_tools = [
            tid for tid in update_request.tool_ids if tid not in VALID_BUILTIN_TOOL_IDS
        ]
        if invalid_tools:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid tool IDs provided: {invalid_tools}. "
                f"Valid tool IDs are: {VALID_BUILTIN_TOOL_IDS}",
            )

    try:
        # Update the default assistant
        updated_persona = update_default_assistant_configuration(
            db_session=db_session,
            tool_ids=update_request.tool_ids,
            system_prompt=update_request.system_prompt,
        )

        # Return the updated configuration
        tool_ids = [tool.name for tool in updated_persona.tools]
        return DefaultAssistantConfiguration(
            tool_ids=tool_ids,
            system_prompt=updated_persona.system_prompt or "",
        )

    except ValueError as e:
        if "Default assistant not found" in str(e):
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))
