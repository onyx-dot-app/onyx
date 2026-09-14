from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

Outcome = Literal[
    "completed",
    "partial",
    "needs_user_input",
    "blocked",
    "budget_exhausted",
    "cancelled",
]

SearchFeedback = Literal[
    "off", "novelty", "source_scope", "visibility", "outcomes", "navigation"
]


class HarnessPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_feedback: SearchFeedback = "off"
    source_cards: bool = False
    search_task_anchor: bool = False
    search_document_read: bool = False
    search_candidate_preparation: bool = False
    search_hierarchical_selection: bool = False
    search_final_selection_limit: int = Field(default=10, ge=1, le=15)
    search_model: str | None = "gpt-5.6-luna"

    max_model_calls: int = Field(default=8, ge=1, le=20)
    max_llm_calls: int = Field(default=80, ge=1, le=300)
    max_tool_calls: int = Field(default=12, ge=1, le=40)
    max_elapsed_seconds: float = Field(default=120, gt=0, le=600)
    # In soft mode max_elapsed_seconds is guidance, never a dispatch deadline.
    duration_mode: Literal["hard", "soft"] = "soft"
    model_timeout_seconds: float = Field(default=120, gt=0, le=600)
    tool_timeout_seconds: float = Field(default=180, gt=0, le=600)
    reservation_wait_seconds: float = Field(default=30, gt=0, le=600)
    max_context_tokens: int | None = Field(default=None, ge=1000)
    max_total_tokens: int = Field(default=120000, ge=1000, le=500000)
    completion_reserve_tokens: int = Field(default=0, ge=0, le=250000)
    preserve_search_evidence: bool = False
    protect_search_budget: bool = False
    # Give a provisional completed answer one evidence-grounded revision pass.
    completion_review: bool = False
    max_output_tokens: int | None = Field(default=None, ge=1)
    # Outer decision/final-answer allowance. Unlike max_output_tokens, this does
    # not lower the ceilings of internal search model calls sharing the ledger.
    decision_max_output_tokens: int | None = Field(default=None, ge=1)
    # Internal search output allowance; independent of the outer input window.
    search_max_output_tokens: int | None = Field(default=16384, ge=1)
    max_cost_cents: float | None = Field(default=None, gt=0, le=1000)
    max_exposed_tools: int = Field(default=6, ge=1, le=20)
    max_result_tokens: int = Field(default=3000, ge=128, le=20000)
    max_store_bytes: int = Field(default=8_000_000, ge=4096, le=32_000_000)


class ToolOutput(BaseModel):
    status: Literal["success", "partial", "error", "blocked"] = "success"
    content: str
    answer: str | None = None
    receipt: dict[str, Any] = Field(default_factory=dict)
    document_ids: list[str] = Field(default_factory=list)
    citation_mapping: dict[int, str] = Field(default_factory=dict)


class ExecutionContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    run_id: str
    task: str
    remaining_seconds: float
    remaining_tokens: int
    cancelled: Callable[[], bool]


class RegisteredTool(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    name: str
    description: str
    parameters: dict[str, Any]
    execute: Callable[[dict[str, Any], ExecutionContext], ToolOutput]
    pinned: bool = False
    requires_approval: bool = True


class ToolInvocation(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ModelDecision(BaseModel):
    continue_turn: bool = False
    calls: list[ToolInvocation] = Field(default_factory=list)
    outcome: Outcome | None = None
    answer: str = ""
    answer_ref: str | None = None
    reason: str = ""
    decision_mode: str | None = None


class UsageSnapshot(BaseModel):
    total_tokens: int = 0
    cost_cents: float = 0
    unpriced_calls: int = 0
    calls: int = 0
    cost_scope: Literal["estimated_llm_only"] = "estimated_llm_only"


class DecisionModel(Protocol):
    def decide(
        self,
        *,
        task: str,
        context: str,
        tools: list[dict[str, Any]],
        remaining_seconds: float,
        remaining_tokens: int,
        max_output_tokens: int | None,
    ) -> ModelDecision: ...


class HarnessEvent(BaseModel):
    kind: str
    elapsed_ms: float
    data: dict[str, Any] = Field(default_factory=dict)


class HarnessResult(BaseModel):
    run_id: str
    outcome: Outcome
    answer: str
    reason: str
    model_calls: int
    tool_calls: int
    total_ms: float
    usage: UsageSnapshot
    events: list[HarnessEvent]
    receipts: list[dict[str, Any]]
    document_ids: list[str] = Field(default_factory=list)
    citation_mapping: dict[int, str] = Field(default_factory=dict)
