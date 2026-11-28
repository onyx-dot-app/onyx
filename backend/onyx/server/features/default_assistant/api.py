"""API endpoints for default assistant configuration."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import Persona, User
from onyx.db.persona import (
    get_default_assistant,
    set_default_chat_tools__no_commit,
    update_default_assistant_configuration,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.prompts.chat_prompts import DEFAULT_SYSTEM_PROMPT
from onyx.server.features.default_assistant.models import (
    DefaultAssistantConfiguration,
    DefaultAssistantToolsUpdateRequest,
    DefaultAssistantUpdateRequest,
)
from onyx.server.features.tool.tool_visibility import is_default_chat_tool_selected
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/admin/default-assistant")

_DEFAULT_ASSISTANT_NOT_FOUND = "Default assistant not found"


def _to_configuration(persona: Persona) -> DefaultAssistantConfiguration:
    return DefaultAssistantConfiguration(
        tool_ids=[
            tool.id for tool in persona.tools if is_default_chat_tool_selected(tool)
        ],
        system_prompt=persona.system_prompt,
        default_system_prompt=DEFAULT_SYSTEM_PROMPT,
    )


def _to_onyx_error(error: ValueError) -> OnyxError:
    if _DEFAULT_ASSISTANT_NOT_FOUND in str(error):
        return OnyxError(OnyxErrorCode.NOT_FOUND, str(error))
    return OnyxError(OnyxErrorCode.INVALID_INPUT, str(error))


@router.get("/configuration")
def get_default_assistant_configuration(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> DefaultAssistantConfiguration:
    """Get the current default assistant configuration."""
    persona = get_default_assistant(db_session)
    if not persona:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, _DEFAULT_ASSISTANT_NOT_FOUND)
    return _to_configuration(persona)


@router.patch("")
def update_default_assistant(
    update_request: DefaultAssistantUpdateRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> DefaultAssistantConfiguration:
    """Replace the default assistant's tool list and/or system prompt."""
    # Distinguish "not provided" from "explicitly set to null"
    update_system_prompt = "system_prompt" in update_request.model_fields_set
    try:
        updated_persona = update_default_assistant_configuration(
            db_session=db_session,
            tool_ids=update_request.tool_ids,
            system_prompt=update_request.system_prompt,
            update_system_prompt=update_system_prompt,
        )
    except ValueError as e:
        raise _to_onyx_error(e) from e
    return _to_configuration(updated_persona)


@router.patch("/tools")
def update_default_assistant_tools(
    update_request: DefaultAssistantToolsUpdateRequest,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
    db_session: Session = Depends(get_session),
) -> DefaultAssistantConfiguration:
    """Add or remove only the given tools. Safe for concurrent callers."""
    try:
        persona = set_default_chat_tools__no_commit(
            db_session, update_request.tool_ids, update_request.enabled
        )
    except ValueError as e:
        raise _to_onyx_error(e) from e
    db_session.commit()
    return _to_configuration(persona)
