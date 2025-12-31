from abc import ABC
from abc import abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.chat.models import PersonaOverrideConfig
from onyx.chat.models import PromptOverrideConfig
from onyx.chat.models import ToolConfig
from onyx.db.tools import get_builtin_tool
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP


class ToolAssertion(BaseModel):
    """Assertion about expected tool usage during evaluation."""

    expected_tools: list[str]  # Tool type names that should be called
    require_all: bool = False  # If True, ALL expected tools must be called


class EvalToolResult(BaseModel):
    """Result of a single eval with tool call information."""

    answer: str
    tools_called: list[str]  # Names of tools that were called
    tool_call_details: list[dict[str, Any]]  # Full tool call info
    citations: list[CitationInfo]  # Citations used in the answer
    assertion_passed: bool | None = None  # None if no assertion configured
    assertion_details: str | None = None  # Explanation of pass/fail


class EvalConfiguration(BaseModel):
    builtin_tool_types: list[str] = Field(default_factory=list)
    persona_override_config: PersonaOverrideConfig | None = None
    llm: LLMOverride = Field(default_factory=LLMOverride)
    search_permissions_email: str | None = None
    allowed_tool_ids: list[int]


class EvalConfigurationOptions(BaseModel):
    builtin_tool_types: list[str] = list(BUILT_IN_TOOL_MAP.keys())
    persona_override_config: PersonaOverrideConfig | None = None
    llm: LLMOverride = LLMOverride(
        model_provider=None,
        model_version="gpt-4o",
        temperature=0.0,
    )
    search_permissions_email: str
    dataset_name: str
    no_send_logs: bool = False

    def get_configuration(self, db_session: Session) -> EvalConfiguration:
        persona_override_config = self.persona_override_config or PersonaOverrideConfig(
            name="Eval",
            description="A persona for evaluation",
            tools=[
                ToolConfig(id=get_builtin_tool(db_session, BUILT_IN_TOOL_MAP[tool]).id)
                for tool in self.builtin_tool_types
            ],
            prompts=[
                PromptOverrideConfig(
                    name="Default",
                    description="Default prompt for evaluation",
                    system_prompt="You are a helpful assistant.",
                    task_prompt="",
                    datetime_aware=True,
                )
            ],
        )

        return EvalConfiguration(
            persona_override_config=persona_override_config,
            llm=self.llm,
            search_permissions_email=self.search_permissions_email,
            allowed_tool_ids=[
                get_builtin_tool(db_session, BUILT_IN_TOOL_MAP[tool]).id
                for tool in self.builtin_tool_types
            ],
        )


class EvalationAck(BaseModel):
    success: bool


class EvalProvider(ABC):
    @abstractmethod
    def eval(
        self,
        task: Callable[[dict[str, Any]], EvalToolResult],
        configuration: EvalConfigurationOptions,
        data: list[dict[str, Any]] | None = None,
        remote_dataset_name: str | None = None,
    ) -> EvalationAck:
        pass
