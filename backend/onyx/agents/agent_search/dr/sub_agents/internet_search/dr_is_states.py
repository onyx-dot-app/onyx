from operator import add
from typing import Annotated

from pydantic import BaseModel

from onyx.agents.agent_search.dr.models import IterationAnswer


### States ###


class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []


class SubAgentInput(LoggerUpdate):
    iteration_nr: int = 0
    query_list: list[str] = []
    main_question: str | None = None
    context: str | None = None


class SubAgentUpdate(LoggerUpdate):
    iteration_responses: Annotated[list[IterationAnswer], add] = []


class BranchInput(SubAgentInput):
    parallelization_nr: int = 0
    branch_question: str | None = None


class BranchUpdate(LoggerUpdate):
    branch_iteration_responses: Annotated[list[IterationAnswer], add] = []


class BranchInformationState(BranchInput, BranchUpdate):
    pass


## Graph State
class SubAgentMainState(
    # This includes the core state
    SubAgentInput,
    SubAgentUpdate,
    BranchUpdate,
):
    pass
