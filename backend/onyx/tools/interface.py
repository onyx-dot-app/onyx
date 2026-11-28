import abc
import traceback
from collections.abc import Callable, Collection, Sequence
from functools import cache, partial
from typing import TYPE_CHECKING, ClassVar, final

from pydantic import BaseModel, JsonValue, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from onyx.agents.tools import (
    AgentTool,
    NestedInputAnswer,
    ToolExecutionMode,
    ToolInvocation,
    ToolOutcome,
)
from onyx.chat.prompt_formatting import prompt_metadata
from onyx.configs.constants import MessageType
from onyx.llm.models import Message, ToolDefinition, ToolResult
from onyx.tools.models import (
    DEFAULT_CODE_MODE_RESULT,
    CapabilityEntry,
    ChatMinimalTextMessage,
    CodeModeExposure,
    CodeModeFunctionName,
    CodeModeResultSpec,
    IntegrationActionRef,
    ToolApprovalDetails,
    ToolApprovalScope,
    ToolCallException,
    ToolContext,
    ToolExecutionError,
    ToolExecutionException,
    ToolPreference,
)
from onyx.tools.ordering import ToolRank
from onyx.tracing.framework.create import function_span
from onyx.tracing.framework.spans import SpanError
from onyx.utils.fleet_query_telemetry import CURRENT_QUERY_OBSERVATION
from onyx.utils.fleet_telemetry import ToolKind
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from onyx.agents.models import RunState


logger = setup_logger()

CITATIONS_PER_TOOL_CALL = 100


_MESSAGE_TYPES = {
    "user": MessageType.USER,
    "assistant": MessageType.ASSISTANT,
    "system": MessageType.SYSTEM,
    "tool_result": MessageType.TOOL_CALL_RESPONSE,
}


def tool_message_history(
    messages: Sequence[Message],
) -> list[ChatMinimalTextMessage]:
    return [
        ChatMinimalTextMessage(
            message=message.text,
            message_type=MessageType.USER_REMINDER
            if prompt_metadata(message).is_reminder
            else _MESSAGE_TYPES[message.role],
        )
        for message in messages
    ]


@cache
def _accepts_null(annotation: object) -> bool:
    try:
        TypeAdapter(annotation).validate_python(None)
    except ValidationError:
        return False
    return True


def parse_tool_arguments[T: BaseModel](
    model: type[T], arguments: dict[str, JsonValue]
) -> T:
    """Validate a call with the model of `tool_definition_from_arguments`. Null
    for a defaulted argument whose type does not accept null selects the
    default, as strict definitions ask."""
    try:
        return model.model_validate(
            {
                key: value
                for key, value in arguments.items()
                if value is not None
                or (field := model.model_fields.get(key)) is None
                or field.is_required()
                or _accepts_null(field.annotation)
            }
        )
    except ValidationError as error:
        message = "; ".join(
            f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
            if item["loc"]
            else item["msg"]
            for item in error.errors(include_input=False, include_url=False)
        )
        raise ToolCallException(
            message=f"Invalid tool arguments: {message}",
            llm_facing_message=f"Invalid tool arguments: {message}",
        ) from error


def merge_tool_arguments(
    first: dict[str, JsonValue],
    second: dict[str, JsonValue],
    *,
    field: str,
    max_items: int | None = None,
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
        or (max_items is not None and len(left) + len(right) > max_items)
        or any(not isinstance(value, str) for value in left + right)
    ):
        return None
    merged_args = first.copy()
    merged_args[field] = left + right
    return merged_args


def _tool_span_error(
    name: str, invocation: ToolInvocation, error: Exception
) -> SpanError:
    return {
        "message": str(error),
        "data": {
            "tool_name": name,
            "tool_call_id": invocation.call_id,
            "error_type": type(error).__name__,
            "stack_trace": traceback.format_exc(),
        },
    }


def _invoke_tool[T: ToolOutcome](
    name: str, invocation: ToolInvocation, execute: Callable[[], T]
) -> T | ToolResult:
    """Apply application tracing, error conversion, and cancellation to a callback."""
    invocation.cancellation.check()
    with function_span(name, metadata=invocation.trace_metadata) as span:
        span.span_data.input = str(invocation.arguments)
        try:
            result = execute()
        except ToolCallException as error:
            logger.warning("Tool call rejected by %s: %s", name, error)
            span.set_error(_tool_span_error(name, invocation, error))
            result = ToolResult(content=error.llm_facing_message, is_error=True)
        except Exception as error:
            logger.exception("Tool execution failed for %s", name)
            span.set_error(_tool_span_error(name, invocation, error))
            result = ToolResult(
                content=f"Tool failed with error: {error}",
                is_error=True,
                details=ToolExecutionError(message=str(error))
                if isinstance(error, ToolExecutionException) and error.emit_error_packet
                else None,
            )
        span.span_data.output = (
            result.text if isinstance(result, ToolResult) else result.model_dump_json()
        )
    invocation.cancellation.check()
    return result


@cache
def _tool_kind_classes() -> tuple[tuple[type["Tool"], ToolKind], ...]:
    # Local imports break the Tool / implementation inheritance cycle.
    from onyx.tools.tool_implementations.api_app.rest_tool import RestTool
    from onyx.tools.tool_implementations.code_mode.code_mode_tool import (
        CodeModeTool,
        WaitCodeTool,
    )
    from onyx.tools.tool_implementations.images.image_generation_tool import (
        ImageGenerationTool,
    )
    from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
    from onyx.tools.tool_implementations.open_url.open_url_tool import OpenURLTool
    from onyx.tools.tool_implementations.python.python_tool import PythonTool
    from onyx.tools.tool_implementations.sandbox.browser_tools import BrowserTool
    from onyx.tools.tool_implementations.sandbox.sandbox_tools import SandboxTool
    from onyx.tools.tool_implementations.search.search_tool import SearchTool
    from onyx.tools.tool_implementations.web_search.web_search_tool import (
        WebSearchTool,
    )

    return (
        (SearchTool, ToolKind.SEARCH),
        (WebSearchTool, ToolKind.WEB_SEARCH),
        (OpenURLTool, ToolKind.OPEN_URL),
        (MCPTool, ToolKind.MCP),
        (RestTool, ToolKind.CUSTOM),
        (ImageGenerationTool, ToolKind.IMAGE),
        (PythonTool, ToolKind.PYTHON),
        (CodeModeTool, ToolKind.CODE_MODE),
        (WaitCodeTool, ToolKind.CODE_MODE),
        (SandboxTool, ToolKind.SANDBOX),
        (BrowserTool, ToolKind.SANDBOX),
    )


def tool_kind(tool: "Tool") -> ToolKind:
    """The tool's fixed telemetry class, from its type and never its name."""
    for tool_class, kind in _tool_kind_classes():
        if isinstance(tool, tool_class):
            return kind
    return ToolKind.OTHER


ToolResultFromChildren = Callable[
    [ToolInvocation, ToolContext, list["RunState"]], ToolResult
]
ToolResumeWithInput = Callable[
    [ToolInvocation, ToolContext, list[NestedInputAnswer]], ToolOutcome
]
ToolContinueOpenInput = Callable[
    [ToolInvocation, ToolContext, list[NestedInputAnswer]], Collection[str]
]


class Tool(abc.ABC):
    """An application tool with context, tracing, and an SDK binding."""

    result_from_children: ToolResultFromChildren | None = None
    # Continues a call that returned NestedInputWait; see AgentTool.
    resume_with_input: ToolResumeWithInput | None = None
    # Continues calls whose open requests have answers; see AgentTool.
    continue_open_input: ToolContinueOpenInput | None = None
    # Set by tools that must not run twice: the saved result of a call that
    # stopped before it finished. See AgentTool.
    interrupted_result: ToolResult | None = None
    merge_list_argument: str | None = None
    merge_list_limit: int | None = None
    # SEQUENTIAL tools of one group take turns, as calls of one tool do.
    sequence_group: str | None = None
    # Set on tools whose calls can wait for the user's approval: an integration
    # action that its policy asks for, or a built-in tool's gated action. See
    # onyx/chat/tool_approvals.py and approval_details.
    approval: ToolApprovalScope | None = None
    # Set on the tool of an integration action; a preference names it.
    integration_action: IntegrationActionRef | None = None
    # The tool's slot in the order that the model reads the tools
    # (onyx/tools/ordering.py). Every concrete tool class sets it.
    rank: ClassVar[ToolRank]

    @property
    def execution_mode(self) -> ToolExecutionMode:
        return ToolExecutionMode.PARALLEL

    @property
    def inner_tools(self) -> list["Tool"]:
        """Tools that run inside this tool's calls, such as code mode functions."""
        return []

    def matches(self, preference: ToolPreference) -> bool:
        if isinstance(preference, CapabilityEntry):
            return self.id == preference.tool_id
        return (
            self.integration_action is not None
            and self.integration_action.integration_id == preference.integration_id
            and self.integration_action.action == preference.action
        )

    def operation_names(self, preference: ToolPreference) -> list[str]:
        """How the model calls the preferred tool through this tool."""
        return [self.name] if self.matches(preference) else []

    @property
    @abc.abstractmethod
    def code_mode_exposure(self) -> CodeModeExposure:
        """How code mode offers the tool. Tools that wait for child runs
        (`result_from_children`) must be DIRECT."""
        raise NotImplementedError

    @property
    def code_mode_function_name(self) -> CodeModeFunctionName:
        return CodeModeFunctionName(name=self.name)

    @property
    def code_mode_result(self) -> CodeModeResultSpec:
        """The value and stub type a code mode program receives from the tool."""
        return DEFAULT_CODE_MODE_RESULT

    @property
    @abc.abstractmethod
    def id(self) -> int | None:
        """The tool row; None for a tool built per response without a row."""
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

    @property
    def summary(self) -> str:
        """What the tool does, without the usage guidance that its description
        can carry. A caller that writes its own guidance, as deep research
        does, shows the summary instead."""
        return self.description

    def describe(self, called_name: Callable[[str], str]) -> str | None:  # noqa: ARG002
        """The description, naming each other tool by the name that
        `called_name` gives for its tool name, such as its code mode
        function; None: the definition's description, which names no tool. A
        tool whose description names other tools overrides it, and its
        `description` names them as tools."""
        return None

    @classmethod
    def is_available(cls, db_session: Session) -> bool:  # noqa: ARG003
        return True

    def approval_details(
        self,
        arguments: dict[str, JsonValue],  # noqa: ARG002
    ) -> ToolApprovalDetails | None:
        """What the approval card of a call of this gated tool shows, or None
        when the call needs no approval. `arguments` are the ones the call
        runs with. Called before the call runs, with no database session open,
        so it must not raise: arguments that it cannot read return None, and
        the call reports its own error. The default shows the call's
        arguments."""
        return ToolApprovalDetails(display_name=self.display_name)

    @abc.abstractmethod
    def tool_definition(self) -> ToolDefinition:
        raise NotImplementedError

    @abc.abstractmethod
    def _run(self, invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        raise NotImplementedError

    @final
    def run(self, invocation: ToolInvocation, context: ToolContext) -> ToolOutcome:
        """Run with tracing and return tool errors to the model; cancellation propagates."""

        observation = CURRENT_QUERY_OBSERVATION.get()
        kind = tool_kind(self) if observation else ToolKind.OTHER

        def execute() -> ToolOutcome:
            if observation:
                observation.tool_started(kind)
            return self._run(invocation, context)

        result = _invoke_tool(self.name, invocation, execute)
        if observation and isinstance(result, ToolResult) and result.is_error:
            observation.tool_failed(kind)
        return result

    def bind(
        self, get_context: Callable[[], ToolContext], *, summary_only: bool = False
    ) -> AgentTool:
        """Bind runtime callbacks; resolve application context only when they
        execute. With `summary_only`, the definition describes the tool by its
        `summary`."""
        definition = self.tool_definition()
        if summary_only:
            definition = definition.model_copy(update={"description": self.summary})
        convert_child_results = self.result_from_children
        result_from_children = None
        if convert_child_results is not None:

            def result_from_children(
                invocation: ToolInvocation, children: list["RunState"]
            ) -> ToolResult:
                context = get_context()
                return _invoke_tool(
                    self.name,
                    invocation,
                    lambda: convert_child_results(invocation, context, children),
                )

        continue_with_input = self.resume_with_input
        resume_with_input = None
        if continue_with_input is not None:

            def resume_with_input(
                invocation: ToolInvocation, answers: list[NestedInputAnswer]
            ) -> ToolOutcome:
                context = get_context()
                return _invoke_tool(
                    self.name,
                    invocation,
                    lambda: continue_with_input(invocation, context, answers),
                )

        take_open_input = self.continue_open_input
        continue_open_input = None
        if take_open_input is not None:

            def continue_open_input(
                invocation: ToolInvocation, answers: list[NestedInputAnswer]
            ) -> Collection[str]:
                return take_open_input(invocation, get_context(), answers)

        return AgentTool(
            definition=definition,
            execute=lambda invocation: self.run(invocation, get_context()),
            execution_mode=self.execution_mode,
            sequence_group=self.sequence_group,
            merge_arguments=partial(
                merge_tool_arguments,
                field=self.merge_list_argument,
                max_items=self.merge_list_limit,
            )
            if self.merge_list_argument is not None
            else None,
            result_from_children=result_from_children,
            resume_with_input=resume_with_input,
            continue_open_input=continue_open_input,
            interrupted_result=self.interrupted_result,
            display_name=self.display_name,
            approval_required=[
                tool.name
                for tool in (self, *self.inner_tools)
                if tool.approval is not None
            ],
        )


def tool_definition_from_arguments(
    name: str,
    description: str,
    arguments: type[BaseModel],
    *,
    strict: bool = False,
) -> ToolDefinition:
    """A tool definition whose parameters are the JSON schema of the Pydantic
    model that `parse_tool_arguments` validates the call with.

    A strict definition is closed and requires every argument, as OpenAI strict
    mode does: an argument with a default accepts null, which
    `parse_tool_arguments` reads as the default. Its argument types must be
    inline, so a nested model or an enum, which Pydantic emits as a `$defs`
    reference, is an error; use a `Literal` for an enum. An object argument,
    such as a mapping, is an error too, because strict mode requires every
    object to be closed."""
    schema = arguments.model_json_schema()
    # Titles repeat the names, and a model's docstring is for developers;
    # leave both out of the arguments model and its nested models.
    for model_schema in (schema, *schema.get("$defs", {}).values()):
        model_schema.pop("title", None)
        model_schema.pop("description", None)
        for field_schema in model_schema.get("properties", {}).values():
            field_schema.pop("title", None)
    properties = schema["properties"]
    if strict:
        if "$defs" in schema:
            raise ValueError(
                f"{arguments.__name__} has referenced types; a strict definition "
                "supports only inline argument types"
            )
        pending: list[object] = list(properties.values())
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if node.get("type") == "object":
                    raise ValueError(
                        f"{arguments.__name__} has an object argument; a strict "
                        "definition supports only closed objects"
                    )
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        schema["additionalProperties"] = False
        for field_name in set(properties) - set(schema.get("required", [])):
            field_schema = properties[field_name]
            field_schema.pop("default", None)
            if {"type": "null"} not in field_schema.get("anyOf", []):
                nullable = {"anyOf": [field_schema, {"type": "null"}]}
                if "description" in field_schema:
                    nullable["description"] = field_schema.pop("description")
                properties[field_name] = nullable
        schema["required"] = list(properties)
    return ToolDefinition(
        name=name, description=description, parameters=schema, strict=strict
    )
