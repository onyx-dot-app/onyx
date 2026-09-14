from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from onyx.agents.v2.models import HarnessPolicy, HarnessResult
from onyx.context.search.models import BaseFilters
from onyx.llm.models import ReasoningEffort


class AgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=12000)
    provider: str | None = None
    model: str | None = None
    persona_id: int | None = None
    filters: BaseFilters | None = None
    include_persona_tools: bool = False
    reasoning_effort: ReasoningEffort = ReasoningEffort.LOW
    concise_answers: bool = False
    search_synthesis: bool = False
    search_expansion_strategy: Literal["legacy", "objective", "complementary"] = (
        "objective"
    )
    completion_mode: Literal["standard", "minimal"] = "standard"
    decision_mode: Literal["standard", "minimal"] = "standard"
    policy: HarnessPolicy = Field(default_factory=HarnessPolicy)

    @model_validator(mode="after")
    def validate_request(self) -> "AgentRequest":
        if bool(self.provider) != bool(self.model):
            raise ValueError("Provider and model must be specified together")
        if self.include_persona_tools and self.persona_id is None:
            raise ValueError("Persona tool discovery requires a persona")
        if (
            self.completion_mode == "minimal" or self.decision_mode == "minimal"
        ) and self.include_persona_tools:
            raise ValueError(
                "Minimal completion mode is currently limited to search-only requests"
            )
        if not self.question.strip():
            raise ValueError("Question cannot be blank")
        return self


class AgentResponse(BaseModel):
    variant: str = "search_first_v2"
    result: HarnessResult
    setup_ms: float
    request_total_ms: float
    trace_id: str | None
    trace_url: str | None = None
    sources: list[dict] = Field(default_factory=list)
