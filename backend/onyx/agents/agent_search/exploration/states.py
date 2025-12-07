from operator import add
from typing import Annotated
from typing import Any
from typing import Dict
from typing import TypedDict

from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from pydantic import BaseModel

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.exploration.models import IterationAnswer
from onyx.agents.agent_search.exploration.models import IterationInstructions
from onyx.agents.agent_search.exploration.models import OrchestrationClarificationInfo
from onyx.agents.agent_search.exploration.models import OrchestrationPlan
from onyx.agents.agent_search.exploration.models import OrchestratorTool
from onyx.context.search.models import InferenceSection
from onyx.db.connector import DocumentSource

### States ###


class LoggerUpdate(BaseModel):
    log_messages: Annotated[list[str], add] = []


class OrchestrationUpdate(LoggerUpdate):
    tools_used: Annotated[list[str], add] = []
    query_list: list[str] = []
    iteration_nr: int = 0
    current_step_nr: int = 1
    plan_of_record: OrchestrationPlan | None = None  # None for Thoughtful
    remaining_time_budget: float = 2.0  # set by default to about 2 searches
    num_closer_suggestions: int = 0  # how many times the closer was suggested
    gaps: list[str] = (
        []
    )  # gaps that may be identified by the closer before being able to answer the question.
    iteration_instructions: Annotated[list[IterationInstructions], add] = []
    message_history_for_continuation: Annotated[
        list[SystemMessage | HumanMessage | AIMessage], add
    ] = []
    iteration_responses: Annotated[list[IterationAnswer], add] = []
    num_search_iterations: int = 0


class CSUpdate(BaseModel):
    extended_base_knowledge: dict[str, Any] = {}
    knowledge_update_pairs: dict[str, dict[str, list[tuple[str, str]]]] = {}


class CSUpdateConsolidatorInput(BaseModel):
    area: str
    update_type: str
    update_pair: tuple[str, str]


class CSUpdateConsolidatorUpdate(BaseModel):
    area: str
    update_type: str
    consolidated_update: str


class OrchestrationSetup(OrchestrationUpdate):
    original_question: str | None = None
    chat_history_string: str | None = None
    clarification: OrchestrationClarificationInfo | None = None
    available_tools: dict[str, OrchestratorTool] | None = None
    num_closer_suggestions: int = 0  # how many times the closer was suggested

    active_source_types: list[DocumentSource] | None = None
    active_source_types_descriptions: str | None = None
    assistant_system_prompt: str | None = None
    assistant_task_prompt: str | None = None
    uploaded_test_context: str | None = None
    uploaded_image_context: list[dict[str, Any]] | None = None
    message_history_for_continuation: Annotated[
        list[SystemMessage | HumanMessage | AIMessage], add
    ] = []
    original_cheat_sheet_context: Dict[str, Any] | None = None
    use_clarifier: bool = False
    use_thinking: bool = False
    use_plan: bool = False
    use_plan_updates: bool = False
    use_corpus_history: bool = False
    use_dc: bool = False
    use_context_explorer: bool = False


class AnswerUpdate(LoggerUpdate):
    iteration_responses: Annotated[list[IterationAnswer], add] = []


class FinalUpdate(LoggerUpdate):
    final_answer: str | None = None
    all_cited_documents: list[InferenceSection] = []


## Graph Input State
class MainInput(CoreState):
    pass


## Graph State
class MainState(
    # This includes the core state
    MainInput,
    OrchestrationSetup,
    AnswerUpdate,
    FinalUpdate,
    CSUpdate,
):
    consolidated_updates: Annotated[list[CSUpdateConsolidatorUpdate], add] = []


## Graph Output State
class MainOutput(TypedDict):
    log_messages: list[str]
    final_answer: str | None
    all_cited_documents: list[InferenceSection]
