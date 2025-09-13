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
from onyx.llm.override_models import LLMOverride
from onyx.tools.built_in_tools import BUILT_IN_TOOLS
from onyx.tools.built_in_tools import get_builtin_tool
from onyx.tools.built_in_tools import get_builtin_tool_type_by_name


class EvalConfiguration(BaseModel):
    builtin_tool_types: list[str] = Field(default_factory=list)
    persona_override_config: PersonaOverrideConfig | None = None
    llm: LLMOverride = Field(default_factory=LLMOverride)
    impersonation_email: str | None = None


class EvalConfigurationOptions(BaseModel):
    builtin_tool_types: list[str] = [tool["cls"].__name__ for tool in BUILT_IN_TOOLS]
    persona_override_config: PersonaOverrideConfig | None = None
    llm: LLMOverride = LLMOverride(
        name="Default",
        model_version="gpt-4.1",
        temperature=0.5,
    )
    impersonation_email: str | None = None
    dataset_name: str

    def get_configuration(self, db_session: Session) -> EvalConfiguration:
        persona_override_config = self.persona_override_config or PersonaOverrideConfig(
            name="Eval",
            description="A persona for evaluation",
            tools=[
                ToolConfig(
                    id=get_builtin_tool(
                        db_session, get_builtin_tool_type_by_name(tool)
                    ).id
                )
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
            builtin_tool_types=self.builtin_tool_types,
            persona_override_config=persona_override_config,
            llm=self.llm,
            impersonation_email=self.impersonation_email,
        )


class EvaluationResult(BaseModel):
    success: bool


class EvalProvider(ABC):
    @abstractmethod
    def eval(
        self, configuration: EvalConfigurationOptions, task: Callable, data: Any
    ) -> EvaluationResult:
        pass
