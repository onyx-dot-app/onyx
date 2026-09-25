import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FinishReason = Literal["stop", "tool_calls", "length", "content_filter"]


class ToolCall(BaseModel):
    """A native tool call the mock model emits. A string `arguments` is sent
    verbatim, so it can carry malformed JSON."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any] | str = Field(default_factory=dict)

    def arguments_json(self) -> str:
        if isinstance(self.arguments, str):
            return self.arguments
        return json.dumps(self.arguments)


class RecordedMessage(BaseModel):
    role: str
    content: str = ""
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class RecordedRequest(BaseModel):
    """One chat-completions request as the server saw it, plus what served it."""

    index: int
    script_id: str
    model: str
    stream: bool
    include_usage: bool
    messages: list[RecordedMessage]
    tools: list[str]
    tool_choice: str | None
    response_format: str | None
    max_tokens: int | None
    raw_body: dict[str, Any]
    lane: str | None = None
    step_index: int | None = None
    builtin: str | None = None
    error: str | None = None

    @property
    def matched(self) -> bool:
        return self.error is None

    @property
    def prompt_text(self) -> str:
        """System and user message text, the only text `text_contains` sees."""
        return "\n".join(
            m.content for m in self.messages if m.role in ("system", "user")
        )

    def tool_result(self, tool_call_id: str) -> str | None:
        for message in self.messages:
            if message.role == "tool" and message.tool_call_id == tool_call_id:
                return message.content
        return None

    def tool_result_ids(self) -> list[str]:
        return [
            m.tool_call_id
            for m in self.messages
            if m.role == "tool" and m.tool_call_id is not None
        ]


class Matcher(BaseModel):
    """Conditions on a request; every set field must hold.

    Prefer request shape (tools, tool results, tool_choice, response_format).
    `text_contains` looks only at system and user message text and is meant as
    a last resort, e.g. to tell parallel Deep Research agents apart by task.
    """

    model_config = ConfigDict(extra="forbid")

    tools_offered: bool | None = None
    offered_tools: list[str] = Field(default_factory=list)
    not_offered_tools: list[str] = Field(default_factory=list)
    tool_results_for: list[str] = Field(default_factory=list)
    tool_choice: str | None = None
    response_format: str | None = None
    text_contains: list[str] = Field(default_factory=list)

    def matches(self, request: RecordedRequest) -> bool:
        offered = set(request.tools)
        if self.tools_offered is not None and self.tools_offered != bool(offered):
            return False
        if not set(self.offered_tools) <= offered:
            return False
        if offered & set(self.not_offered_tools):
            return False
        if not set(self.tool_results_for) <= set(request.tool_result_ids()):
            return False
        if self.tool_choice is not None and self.tool_choice != request.tool_choice:
            return False
        if (
            self.response_format is not None
            and self.response_format != request.response_format
        ):
            return False
        prompt_text = request.prompt_text
        return all(fragment in prompt_text for fragment in self.text_contains)


class Step(BaseModel):
    """One model response. `finish_reason` defaults to `tool_calls` when the
    step has tool calls and `stop` otherwise. `disconnect` closes a streamed
    response before its first chunk (a non-streamed request gets HTTP 500).
    A step with `required=False` may stay unconsumed at teardown."""

    model_config = ConfigDict(extra="forbid")

    reasoning: str | None = None
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: FinishReason | None = None
    match: Matcher | None = None
    required: bool = True
    disconnect: bool = False

    def resolved_finish_reason(self) -> FinishReason:
        if self.finish_reason is not None:
            return self.finish_reason
        return "tool_calls" if self.tool_calls else "stop"

    def response_key(self) -> str:
        return self.model_dump_json(exclude={"match", "required"})


class Lane(BaseModel):
    """An ordered sequence of steps. A request is served by the next pending
    step of the lane whose `match` (and that step's own `match`) accepts it."""

    model_config = ConfigDict(extra="forbid")

    name: str
    match: Matcher = Field(default_factory=Matcher)
    steps: list[Step]


class Script(BaseModel):
    """Lanes plus built-in responder settings. `builtin_overrides` replaces a
    built-in responder's text; `disabled_builtins` sends those requests to the
    lanes instead."""

    model_config = ConfigDict(extra="forbid")

    lanes: list[Lane] = Field(default_factory=list)
    builtin_overrides: dict[str, str] = Field(default_factory=dict)
    disabled_builtins: set[str] = Field(default_factory=set)
