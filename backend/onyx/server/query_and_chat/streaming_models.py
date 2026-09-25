"""Public response items and incremental updates consumed by chat clients."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, JsonValue

from onyx.agents.execution_records import RunStatus
from onyx.coding_agent.models import CodingAgentCallResult
from onyx.context.search.models import SearchDoc, SearchDocsResponse
from onyx.deep_research.models import ResearchAgentCallResult
from onyx.tools.models import (
    CustomToolCallSummary,
    FileReadResult,
    LlmBashExecutionResult,
    LlmPythonExecutionResult,
    MemoryUpdated,
)
from onyx.tools.tool_implementations.images.models import FinalImageGenerationResponse

ToolMetadata = Annotated[
    SearchDocsResponse
    | CustomToolCallSummary
    | FileReadResult
    | MemoryUpdated
    | LlmPythonExecutionResult
    | LlmBashExecutionResult
    | FinalImageGenerationResponse
    | CodingAgentCallResult
    | ResearchAgentCallResult,
    Field(discriminator="type"),
]


class ItemKind(str, Enum):
    TEXT = "text"
    REASONING = "reasoning"
    TOOL = "tool"


class TextPurpose(str, Enum):
    ANSWER = "answer"
    PLAN = "plan"
    REPORT = "report"
    COMMENTARY = "commentary"


class CitationInfo(BaseModel):
    citation_number: int
    document_id: str


class TextItem(BaseModel):
    kind: Literal[ItemKind.TEXT] = ItemKind.TEXT
    text: str = ""
    status: RunStatus = RunStatus.RUNNING
    purpose: TextPurpose = TextPurpose.ANSWER
    documents: list[SearchDoc] = Field(default_factory=list)
    citations: list[CitationInfo] = Field(default_factory=list)
    pre_answer_seconds: float | None = None


class ReasoningItem(BaseModel):
    kind: Literal[ItemKind.REASONING] = ItemKind.REASONING
    text: str = ""
    status: RunStatus = RunStatus.RUNNING


class ToolStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"
    CANCELLED = "cancelled"
    LIMIT = "limit"


class ToolItem(BaseModel):
    tool_id: int | None = None
    kind: Literal[ItemKind.TOOL] = ItemKind.TOOL
    name: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    status: ToolStatus = ToolStatus.RUNNING
    output: str = ""
    metadata: ToolMetadata | None = None


ChatItem = Annotated[TextItem | ReasoningItem | ToolItem, Field(discriminator="kind")]


class TextDelta(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    citations: list[CitationInfo] = Field(default_factory=list)


class ToolArgumentsDelta(BaseModel):
    kind: Literal["tool_arguments"] = "tool_arguments"
    name: str
    arguments: dict[str, str]


class ToolOutputUpdate(BaseModel):
    kind: Literal["tool_output"] = "tool_output"
    output: str | None = None
    metadata: ToolMetadata | None = None


class ItemUpdate(BaseModel):
    type: Literal["item_update"] = "item_update"
    item: ChatItem


class ItemDelta(BaseModel):
    type: Literal["item_delta"] = "item_delta"
    delta: Annotated[
        TextDelta | ToolArgumentsDelta | ToolOutputUpdate, Field(discriminator="kind")
    ]


class RunUpdate(BaseModel):
    type: Literal["run_update"] = "run_update"
    status: RunStatus


class OverallStop(BaseModel):
    type: Literal["stop"] = "stop"
    stop_reason: str | None = None


class ChatHeartbeat(BaseModel):
    type: Literal["chat_heartbeat"] = "chat_heartbeat"


PacketObj = Annotated[
    ItemUpdate | ItemDelta | RunUpdate | OverallStop | ChatHeartbeat,
    Field(discriminator="type"),
]


class PacketIdentity(BaseModel):
    agent_id: str | None = None
    agent_path: str | None = None
    response_id: int
    run_id: str
    message_id: str
    parent_run_id: str | None = None
    parent_message_id: str | None = None
    parent_tool_call_id: str | None = None
    tool_call_id: str | None = None
    part_id: str = "answer"


class Packet(BaseModel):
    model_index: int | None = None
    identity: PacketIdentity | None = None
    obj: PacketObj


def heartbeat_packet() -> Packet:
    return Packet(obj=ChatHeartbeat())
