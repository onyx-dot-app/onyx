"""Store canonical output under existing chat ownership and retention rules."""

from pydantic import JsonValue, TypeAdapter

from onyx.agents.transcript import AgentTranscript
from onyx.chat.models import (
    ChatExecutionRecord,
    MessagePresentation,
    ToolRecordReference,
)
from onyx.db.models import ChatMessage
from onyx.utils.postgres_sanitization import sanitize_json_like

_TRANSCRIPT_JSON = TypeAdapter(dict[str, JsonValue])


def set_agent_transcript(
    message: ChatMessage,
    transcript: AgentTranscript | None,
    *,
    persist_content: bool,
    presentation: list[MessagePresentation] | None = None,
    tool_records: list[ToolRecordReference] | None = None,
) -> None:
    """Update the row; the caller owns the transaction."""
    record = (
        ChatExecutionRecord(
            transcript=transcript,
            presentation=presentation or [],
            tool_records=tool_records or [],
        )
        if transcript is not None
        else None
    )
    message.agent_transcript = (
        _TRANSCRIPT_JSON.validate_python(
            sanitize_json_like(record.model_dump(mode="json"))
        )
        if persist_content and record is not None
        else None
    )


def read_chat_execution(message: ChatMessage) -> ChatExecutionRecord | None:
    if message.agent_transcript is None:
        return None
    if "transcript" in message.agent_transcript:
        return ChatExecutionRecord.model_validate(message.agent_transcript)
    return ChatExecutionRecord(
        transcript=AgentTranscript.model_validate(message.agent_transcript)
    )


def read_agent_transcript(message: ChatMessage) -> AgentTranscript | None:
    record = read_chat_execution(message)
    return record.transcript if record else None
