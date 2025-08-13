from operator import add
from typing import Annotated

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import OrchestratorTool
from onyx.agents.agent_search.dr.states import LoggerUpdate
from onyx.db.connector import DocumentSource


class SubAgentUpdate(LoggerUpdate):
    iteration_responses: Annotated[list[IterationAnswer], add] = []


class BranchUpdate(LoggerUpdate):
    branch_iteration_responses: Annotated[list[IterationAnswer], add] = []


class SubAgentInput(LoggerUpdate):
    iteration_nr: int = 0
    query_list: list[str] = []
    context: str | None = None
    active_source_types: list[DocumentSource] | None = None
    tools_used: Annotated[list[str], add] = []
    available_tools: dict[str, OrchestratorTool] | None = None


class SubAgentMainState(
    # This includes the core state
    SubAgentInput,
    SubAgentUpdate,
    BranchUpdate,
):
    pass


class BranchInput(SubAgentInput):
    parallelization_nr: int = 0
    branch_question: str | None = None


class CustomToolBranchInput(LoggerUpdate):
    tool_info: OrchestratorTool
