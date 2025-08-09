from operator import add
from typing import Annotated

from pydantic import BaseModel

from onyx.agents.agent_search.dr.models import IterationAnswer


### States ###


class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []


class CustomToolSubAgentInput(LoggerUpdate):
    iteration_nr: int = 0
    query_list: list[str] = []
    main_question: str | None = None
    context: str | None = None
    query_path: Annotated[list[str], add] = []
    available_tools: list[dict[str, str]]


class CustomToolSubAgentPrepareUpdate(LoggerUpdate):
    tool_name: str | None = None
    tool_dict: dict[str, str]


class CustomToolSubAgentUpdate(LoggerUpdate):
    iteration_responses: Annotated[list[IterationAnswer], add] = []


class CustomToolBranchInput(CustomToolSubAgentInput):
    parallelization_nr: int = 0
    branch_question: str | None = None
    tool_name: str | None = None
    tool_dict: dict[str, str]


class GenericToolBranchUpdate(LoggerUpdate):
    branch_iteration_responses: Annotated[list[IterationAnswer], add] = []


class GenericToolBranchInformationState(CustomToolBranchInput, GenericToolBranchUpdate):
    pass


## Graph State
class GenericToolSubAgentMainState(
    # This includes the core state
    CustomToolSubAgentInput,
    CustomToolSubAgentUpdate,
    GenericToolBranchUpdate,
):
    pass
