import abc
from collections.abc import Awaitable, Callable
from typing import Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from sqlalchemy.orm import Session

from onyx.agents.tools import ToolExecutionMode, ToolInvocation
from onyx.configs.constants import MessageType
from onyx.context.messages import prompt_metadata
from onyx.db.memory import UserMemoryContext
from onyx.llm.models import Message, ToolResult
from onyx.tools.models import ChatFile, ChatMinimalTextMessage, ToolCallException

CITATIONS_PER_TOOL_CALL = 100


class ToolFunctionDefinition(TypedDict):
    name: str
    description: str
    parameters: dict[str, JsonValue]
    strict: NotRequired[bool]


class FunctionToolDefinition(TypedDict):
    type: Literal["function"]
    function: ToolFunctionDefinition


class ToolContext(BaseModel):
    """Application data available to each tool in an agent step."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_memory_context: UserMemoryContext | None = None
    user_info: str | None = None
    citation_mapping: dict[int, str] = Field(default_factory=dict)
    next_citation_num: int = 1
    skip_search_query_expansion: bool = False
    chat_files: list[ChatFile] = Field(default_factory=list)
    url_snippet_map: dict[str, str] = Field(default_factory=dict)
    inject_memories_in_prompt: bool = True


_MESSAGE_TYPES = {
    "user": MessageType.USER,
    "assistant": MessageType.ASSISTANT,
    "system": MessageType.SYSTEM,
    "tool_result": MessageType.TOOL_CALL_RESPONSE,
}


def tool_message_history(messages: list[Message]) -> list[ChatMinimalTextMessage]:
    return [
        ChatMinimalTextMessage(
            message=message.text,
            message_type=MessageType.USER_REMINDER
            if prompt_metadata(message).is_reminder
            else _MESSAGE_TYPES[message.role],
        )
        for message in messages
    ]


def parse_tool_arguments[T: BaseModel](
    model: type[T], arguments: dict[str, JsonValue]
) -> T:
    try:
        return model.model_validate(arguments)
    except ValidationError as error:
        message = "; ".join(
            item["msg"] for item in error.errors(include_input=False, include_url=False)
        )
        raise ToolCallException(
            message=f"Invalid tool arguments: {message}",
            llm_facing_message=f"Invalid tool arguments: {message}",
        ) from error


class Tool(abc.ABC):
    """An application tool bound to the runtime with a ToolContext."""

    def for_agent(self) -> "Tool":
        """Return an instance safe to bind to one agent's conversation."""
        return self

    @property
    def execution_mode(self) -> ToolExecutionMode:
        return ToolExecutionMode.PARALLEL

    @property
    @abc.abstractmethod
    def id(self) -> int:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def display_name(self) -> str:
        raise NotImplementedError

    @classmethod
    def is_available(cls, db_session: Session) -> bool:  # noqa: ARG003
        return True

    @abc.abstractmethod
    def tool_definition(self) -> FunctionToolDefinition:
        raise NotImplementedError

    def run(self, invocation: ToolInvocation, context: ToolContext) -> ToolResult:  # noqa: ARG002
        raise RuntimeError(f"Tool {self.name} requires asynchronous execution")

    @property
    def execute_async(
        self,
    ) -> Callable[[ToolInvocation, ToolContext], Awaitable[ToolResult]] | None:
        return None
