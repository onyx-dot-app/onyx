"""Execution outcomes and conversation replay rules."""

from enum import Enum

from pydantic import BaseModel, Field, JsonValue

from onyx.llm.exceptions import LLMErrorInfo
from onyx.llm.models import AssistantMessage, Message, ToolCall, ToolResultMessage
from onyx.utils.logger import setup_logger

logger = setup_logger()


class RunStatus(str, Enum):
    RUNNING = "running"
    SUSPENDED = "suspended"
    COMPLETE = "complete"
    LIMIT = "limit"
    CANCELLED = "cancelled"
    ERROR = "error"

    @property
    def is_terminal(self) -> bool:
        return self not in (RunStatus.RUNNING, RunStatus.SUSPENDED)


class RunFailureKind(str, Enum):
    LLM = "llm"
    LLM_TIMEOUT = "llm_timeout"
    LLM_RATE_LIMIT = "llm_rate_limit"
    EXECUTION = "execution"


class RunFailure(BaseModel):
    kind: RunFailureKind
    message: str
    llm_error: LLMErrorInfo | None = None


class CompactionCheckpoint(BaseModel):
    summary: str
    covered_count: int = Field(gt=0)
    covered_digest: str


class OperationSnapshot(BaseModel):
    """Recorded generation or tool outcome; tool enrichment can revise the result.

    A completed tool outcome does not imply its callbacks or cleanup have finished.
    """

    step_index: int
    message_index: int
    tool_call_id: str | None = None
    status: RunStatus


class AgentRestorationConfig(BaseModel):
    feature: str
    settings: dict[str, JsonValue] = Field(default_factory=dict)


def completed_tool_call_ids(messages: list[Message], assistant_index: int) -> set[str]:
    result_ids: set[str] = set()
    for index in range(assistant_index + 1, len(messages)):
        following = messages[index]
        if not isinstance(following, ToolResultMessage):
            break
        result_ids.add(following.tool_call_id)
    return result_ids


def messages_for_model(messages: list[Message]) -> list[Message]:
    """Exclude unfinished tool calls while preserving recorded partial output."""
    result: list[Message] = []
    accepted: set[str] = set()
    for index, message in enumerate(messages):
        if isinstance(message, AssistantMessage):
            result_ids = completed_tool_call_ids(messages, index)
            accepted = {call.id for call in message.tool_calls if call.id in result_ids}
            copy = message.model_copy(deep=True)
            copy.content = [
                part
                for part in copy.content
                if not isinstance(part, ToolCall) or part.id in accepted
            ]
            if copy.content:
                result.append(copy)
            else:
                logger.debug(
                    "Omitting an unfinished empty assistant message from model context"
                )
        elif isinstance(message, ToolResultMessage):
            if message.tool_call_id in accepted:
                result.append(message.model_copy(deep=True))
                accepted.remove(message.tool_call_id)
            else:
                logger.debug(
                    "Omitting an incomplete tool result from model context: %s",
                    message.tool_call_id,
                )
        else:
            accepted.clear()
            result.append(message.model_copy(deep=True))
    return result
