from operator import add
from typing import Annotated

from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import OrchestratorTool
from onyx.agents.agent_search.dr.states import LoggerUpdate
from onyx.db.connector import DocumentSource


class SubAgentUpdate(LoggerUpdate):
    iteration_responses: Annotated[list[IterationAnswer], add] = []
    current_step_nr: int = 1


class BranchUpdate(LoggerUpdate):
    branch_iteration_responses: Annotated[list[IterationAnswer], add] = []


class SubAgentInput(LoggerUpdate):
    iteration_nr: int = 0
    current_step_nr: int = 1
    query_list: list[str] = []
    context: str | None = None
    active_source_types: list[DocumentSource] | None = None
    tools_used: Annotated[list[str], add] = []
    available_tools: dict[str, OrchestratorTool] | None = None
    assistant_system_prompt: str | None = None
    assistant_task_prompt: str | None = None


class SubAgentMainState(
    # This includes the core state
    SubAgentInput,
    SubAgentUpdate,
    BranchUpdate,
):
    pass


class BranchInput(SubAgentInput):
    parallelization_nr: int = 0
    branch_question: str


class CustomToolBranchInput(LoggerUpdate):
    tool_info: OrchestratorTool
