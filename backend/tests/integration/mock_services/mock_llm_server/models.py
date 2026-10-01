from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class RequestConditions(BaseModel):
    """Conditions on a request. Every set field must hold. `prompt_contains`
    checks system and user message text only."""

    model_config = ConfigDict(extra="forbid")

    has_tools: bool | None = None
    offers: list[str] = Field(default_factory=list)
    does_not_offer: list[str] = Field(default_factory=list)
    has_results_for: list[str] = Field(default_factory=list)
    tool_choice: str | None = None
    prompt_contains: list[str] = Field(default_factory=list)

    def matches(self, request: "RecordedRequest") -> bool:
        offered = set(request.tools)
        if self.has_tools is not None and self.has_tools != bool(offered):
            return False
        if not set(self.offers) <= offered:
            return False
        if offered & set(self.does_not_offer):
            return False
        if not set(self.has_results_for) <= set(request.tool_result_ids()):
            return False
        if self.tool_choice is not None and self.tool_choice != request.tool_choice:
            return False
        prompt_text = request.prompt_text
        return all(fragment in prompt_text for fragment in self.prompt_contains)


class Reply(BaseModel):
    """One model response. A reply with `required=False` may stay unused."""

    model_config = ConfigDict(extra="forbid")

    reasoning: str | None = None
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    conditions: RequestConditions | None = None
    required: bool = True


class Conversation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    conditions: RequestConditions = Field(default_factory=RequestConditions)
    replies: list[Reply]


class Script(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversations: list[Conversation] = Field(default_factory=list)
    default_reply: Reply | None = Field(
        default_factory=lambda: Reply(text="This is a mock LLM response.")
    )


class RecordedMessage(BaseModel):
    role: str
    content: str = ""
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


class RecordedRequest(BaseModel):
    messages: list[RecordedMessage]
    tools: list[str]
    tool_choice: str | None
    body: dict[str, Any]
    conversation: str | None = None
    reply_index: int | None = None
    used_default_reply: bool = False
    error: str | None = None

    @property
    def prompt_text(self) -> str:
        return "\n".join(
            m.content for m in self.messages if m.role in ("system", "user")
        )

    @property
    def is_tool_free(self) -> bool:
        return not self.tools and not self.tool_result_ids()

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


class ScriptState(BaseModel):
    requests: list[RecordedRequest]
    pending_required: list[str]
