from abc import ABC
from abc import abstractmethod
from collections.abc import Callable

from pydantic import BaseModel
from pydantic import Field
from sqlalchemy.orm import Session

from onyx.db.tools import get_builtin_tool
from onyx.llm.override_models import LLMOverride
from onyx.tools.built_in_tools import BUILT_IN_TOOL_MAP


class EvalConfiguration(BaseModel):
    builtin_tool_types: list[str] = Field(default_factory=list)
    llm: LLMOverride = Field(default_factory=LLMOverride)
    search_permissions_email: str | None = None
    allowed_tool_ids: list[int]


class EvalConfigurationOptions(BaseModel):
    builtin_tool_types: list[str] = list(BUILT_IN_TOOL_MAP.keys())
    llm: LLMOverride = LLMOverride(
        model_provider="Default",
        model_version="gpt-4.1",
        temperature=0.0,
    )
    search_permissions_email: str
    dataset_name: str
    no_send_logs: bool = False

    def get_configuration(self, db_session: Session) -> EvalConfiguration:
        return EvalConfiguration(
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
        task: Callable[[dict[str, str]], str],
        configuration: EvalConfigurationOptions,
        data: list[dict[str, dict[str, str]]] | None = None,
        remote_dataset_name: str | None = None,
    ) -> EvalationAck:
        pass
