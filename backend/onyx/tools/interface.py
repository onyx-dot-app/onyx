import abc
from collections.abc import Callable
from functools import partial
from typing import TYPE_CHECKING, final

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from sqlalchemy.orm import Session

from onyx.agents.tools import AgentTool, ToolExecutionMode, ToolInvocation, ToolOutcome
from onyx.chat.llm_step import prompt_metadata
from onyx.configs.constants import MessageType
from onyx.db.memory import UserMemoryContext
from onyx.llm.models import Message, ToolDefinition, ToolResult
from onyx.tools.models import ChatFile, ChatMinimalTextMessage, ToolCallException
from onyx.tracing.framework.create import function_span
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.agents.models import RunState


logger = setup_logger()

CITATIONS_PER_TOOL_CALL = 100


class ToolContext(BaseModel):
    """Application data available to each tool in an agent step."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_memory_context: UserMemoryContext | None = None
    user_info: str | None = None
    citation_mapping: dict[int, str] = Field(default_factory=dict)
    next_citation_num: int = 1
    # On repeat searches, defer to the model's new queries instead of repeating
    # the expansion flow that may have produced poor results on the first pass.
    skip_search_query_expansion: bool = False
    chat_files: list[ChatFile] = Field(default_factory=list)
    url_snippet_map: dict[str, str] = Field(default_factory=dict)
    # When False, don't pass memory context to search tools for query expansion
    # (but still pass it to the memory tool for persistence)
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


def merge_tool_arguments(
    first: dict[str, JsonValue], second: dict[str, JsonValue], *, field: str
) -> dict[str, JsonValue] | None:
    """Combine nonempty string lists when all other arguments match."""
    if {key: value for key, value in first.items() if key != field} != {
        key: value for key, value in second.items() if key != field
    }:
        return None
    left, right = first.get(field), second.get(field)
    if not isinstance(left, list) or not isinstance(right, list):
        return None
    if (
        not left
        or not right
        or any(not isinstance(value, str) for value in left + right)
    ):
        return None
    merged_args = first.copy()
    merged_args[field] = left + right
    return merged_args


ToolResultFromChildren = Callable[
    [ToolInvocation, ToolContext, list["RunState"]], ToolResult
]


class Tool(abc.ABC):
    """An application tool with context, tracing, and an SDK binding."""

    result_from_children: ToolResultFromChildren | None = None
    merge_list_argument: str | None = None

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
    def tool_definition(self) -> ToolDefinition:
        raise NotImplementedError

    @abc.abstractmethod
    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        raise NotImplementedError

    @final
    def run(self, invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        """Run with tracing and convert expected tool errors into model-visible results."""
        invocation.cancellation.check()
        with function_span(self.name) as span:
            span.span_data.input = str(invocation.arguments)
            try:
                result = self._run(invocation, context)
            except ToolCallException as error:
                logger.warning("Tool call rejected by %s: %s", self.name, error)
                result = ToolResult(content=error.llm_facing_message, is_error=True)
            span.span_data.output = (
                result.text
                if isinstance(result, ToolResult)
                else result.model_dump_json()
            )
        invocation.cancellation.check()
        return result

    def bind(self, get_context: Callable[[], ToolContext]) -> AgentTool:
        """Bind runtime callbacks; resolve application context only when they execute."""
        convert_child_results = self.result_from_children
        result_from_children = None
        if convert_child_results is not None:

            def result_from_children(
                invocation: ToolInvocation, children: list["RunState"]
            ) -> ToolResult:
                context = get_context()
                invocation.cancellation.check()
                with function_span(self.name) as span:
                    span.span_data.input = str(invocation.arguments)
                    try:
                        result = convert_child_results(invocation, context, children)
                    except ToolCallException as error:
                        logger.warning("Tool call rejected by %s: %s", self.name, error)
                        result = ToolResult(
                            content=error.llm_facing_message, is_error=True
                        )
                    span.span_data.output = result.text
                invocation.cancellation.check()
                return result

        return AgentTool(
            definition=self.tool_definition(),
            execute=lambda invocation: self.run(invocation, get_context()),
            execution_mode=self.execution_mode,
            merge_arguments=partial(
                merge_tool_arguments, field=self.merge_list_argument
            )
            if self.merge_list_argument is not None
            else None,
            result_from_children=result_from_children,
        )
