from abc import ABC
from abc import abstractmethod
from collections.abc import Callable

from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.chat.models import PersonaOverrideConfig
from onyx.chat.models import PromptOverrideConfig
from onyx.chat.models import ToolConfig
from onyx.db.llm import fetch_model_configuration_by_name
from onyx.db.tools import get_builtin_tool
from onyx.llm.override_models import LLMOverride
from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP


class EvalConfiguration(BaseModel):
    builtin_tool_types: list[str] = Field(default_factory=list)
    persona_override_config: PersonaOverrideConfig | None = None
    llms: list[LLMOverride] = Field(default_factory=list[LLMOverride])
    search_permissions_email: str | None = None
    allowed_tool_ids: list[int]


class EvalConfigurationOptions(BaseModel):
    builtin_tool_types: list[str] = list(
        tool_name
        for tool_name in BUILT_IN_TOOL_MAP.keys()
        if tool_name != "OktaProfileTool"
    )
    persona_override_config: PersonaOverrideConfig | None = None
    models: list[str] = ["gpt-4.1"]
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

        # Fetch LLM models from DB based on model names
        llms: list[LLMOverride] = []
        for model_name in self.models:
            model_config = fetch_model_configuration_by_name(db_session, model_name)
            if model_config and model_config.llm_provider:
                llms.append(
                    LLMOverride(
                        model_provider=model_config.llm_provider.name,
                        model_version=model_config.name,
                    )
                )

        return EvalConfiguration(
            persona_override_config=persona_override_config,
            llms=llms,
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
        task: Callable[[dict[str, str], LLMOverride | None], str],
        configuration: EvalConfigurationOptions,
        data: list[dict[str, dict[str, str]]] | None = None,
        remote_dataset_name: str | None = None,
    ) -> EvalationAck:
        pass
