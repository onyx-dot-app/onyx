"""Auto-generation of human-readable build-session names.

Given a session, pull its first user message and ask the default LLM to
condense it into a short label. Falls back to a deterministic
``"Build Session <prefix>"`` if anything goes wrong.
"""

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session as DBSession

from onyx.configs.constants import MessageType
from onyx.llm.factory import get_default_llm
from onyx.llm.models import LanguageModelInput
from onyx.llm.models import ReasoningEffort
from onyx.llm.models import SystemMessage
from onyx.llm.models import UserMessage
from onyx.llm.utils import llm_response_to_string
from onyx.server.features.build.db.build_session import get_session_messages
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import ensure_trace
from onyx.tracing.llm_utils import llm_generation_span
from onyx.tracing.llm_utils import record_llm_response
from onyx.utils.logger import setup_logger

logger = setup_logger()

_MAX_NAME_LENGTH = 50
_MAX_PROMPT_INPUT_CHARS = 500

_NAMING_SYSTEM_PROMPT = (
    "Given the user's build request, provide a SHORT name for the build "
    "session. Focus on the main task or goal the user wants to accomplish.\n"
    "\n"
    "IMPORTANT: DO NOT OUTPUT ANYTHING ASIDE FROM THE NAME. MAKE IT AS "
    "CONCISE AS POSSIBLE. NEVER USE MORE THAN 5 WORDS, LESS IS FINE."
)

_NAMING_USER_PROMPT = (
    "User's request: {user_message}\n\nProvide a short name for this build session."
)


def _fallback_name(session_id: UUID) -> str:
    return f"Build Session {str(session_id)[:8]}"


def _extract_text(metadata: Any) -> str:
    """Pull the user-message text out of a BuildMessage's ``message_metadata``.

    The persisted shape is ``{type: "user_message", content: {type: "text",
    text: "..."}}`` (per ``_stream_cli_agent_response``), but we defensively
    handle the legacy non-dict shape too.
    """
    if not metadata:
        return ""
    content = metadata.get("content", {})
    if isinstance(content, dict):
        return content.get("text", "") or ""
    return str(content) if content else ""


def first_user_message_text(db_session: DBSession, session_id: UUID) -> str | None:
    """Return the text of the first USER message, or ``None`` if there are
    no user messages / it has no extractable text."""
    messages = get_session_messages(session_id, db_session)
    first_user = next((m for m in messages if m.type == MessageType.USER), None)
    if first_user is None:
        return None
    text = _extract_text(first_user.message_metadata)
    return text or None


def generate_session_name(db_session: DBSession, session_id: UUID) -> str:
    """Ask the LLM for a concise label for ``session_id`` based on its
    first user message. Always returns a non-empty string.

    Fallback order:
    1. LLM-generated name (truncated to 50 chars).
    2. First-message text truncated to 40 chars.
    3. ``Build Session <prefix>`` if the session has no user messages.
    """
    user_message = first_user_message_text(db_session, session_id)
    if not user_message:
        return _fallback_name(session_id)

    try:
        llm = get_default_llm()
        prompt_messages: LanguageModelInput = [
            SystemMessage(content=_NAMING_SYSTEM_PROMPT),
            UserMessage(
                content=_NAMING_USER_PROMPT.format(
                    user_message=user_message[:_MAX_PROMPT_INPUT_CHARS]
                )
            ),
        ]
        generated = ""
        with ensure_trace(
            "build_session_naming",
            group_id=str(session_id),
            metadata={"session_id": str(session_id)},
        ):
            with llm_generation_span(
                llm=llm,
                flow=LLMFlow.BUILD_SESSION_NAMING,
                input_messages=prompt_messages,
            ) as span_generation:
                response = llm.invoke(
                    prompt_messages, reasoning_effort=ReasoningEffort.OFF
                )
                record_llm_response(span_generation, response)
                generated = llm_response_to_string(response).strip().strip('"')

        if not generated:
            return _fallback_name(session_id)
        if len(generated) > _MAX_NAME_LENGTH:
            generated = generated[: _MAX_NAME_LENGTH - 3] + "..."
        return generated
    except Exception as e:
        logger.warning("Failed to generate session name with LLM: %s", e)
        truncated = user_message[:40].strip()
        return truncated + ("..." if len(user_message) > 40 else "")
