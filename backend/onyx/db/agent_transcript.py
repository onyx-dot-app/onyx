"""Store canonical output under existing chat ownership and retention rules."""

from pydantic import JsonValue, TypeAdapter

from onyx.agents.transcript import AgentTranscript
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_json_like

logger = setup_logger()

_TRANSCRIPT_JSON = TypeAdapter(dict[str, JsonValue])


def set_agent_transcript(
    message: ChatMessage,
    transcript: AgentTranscript | None,
    *,
    persist_content: bool,
) -> None:
    """Update the row; the caller owns the transaction."""
    message.agent_transcript = (
        _TRANSCRIPT_JSON.validate_python(
            sanitize_json_like(
                transcript.model_dump(
                    mode="json", exclude={"messages": {"__all__": {"details"}}}
                )
            )
        )
        if persist_content and transcript is not None
        else None
    )


def read_agent_transcript(message: ChatMessage) -> AgentTranscript | None:
    if message.agent_transcript is None:
        return None
    return AgentTranscript.model_validate(message.agent_transcript)


def save_chat_error(
    *,
    message_id: int,
    error: str,
    token_count: int,
    transcript: AgentTranscript | None,
    persist_content: bool,
) -> None:
    with get_session_with_current_tenant() as session:
        message = session.get(ChatMessage, message_id)
        if message is None:
            logger.debug(
                "Chat response %s was deleted; skipping error persistence", message_id
            )
            return
        set_agent_transcript(message, transcript, persist_content=persist_content)
        message.message = error
        message.error = error
        message.token_count = token_count
        session.commit()
