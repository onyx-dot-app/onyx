from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.enums import ResearchType

MAX_CHAT_HISTORY_MESSAGES = (
    3  # note: actual count is x2 to account for user and assistant messages
)

MAX_DR_PARALLEL_SEARCH = 4

# TODO: test more, generally not needed/adds unnecessary iterations
MAX_NUM_CLOSER_SUGGESTIONS = (
    0  # how many times the closer can send back to the orchestrator
)

CLARIFICATION_REQUEST_PREFIX = "PLEASE CLARIFY:"
HIGH_LEVEL_PLAN_PREFIX = "The Plan:"

AVERAGE_TOOL_COSTS: dict[DRPath, float] = {
    DRPath.INTERNAL_SEARCH: 1.0,
    DRPath.KNOWLEDGE_GRAPH: 2.0,
    DRPath.WEB_SEARCH: 1.5,
    DRPath.IMAGE_GENERATION: 3.0,
    DRPath.GENERIC_TOOL: 1.5,  # TODO: see todo in OrchestratorTool
    DRPath.CLOSER: 0.0,
}

DR_TIME_BUDGET_BY_TYPE = {
    ResearchType.THOUGHTFUL: 3.0,
    ResearchType.DEEP: 12.0,
    ResearchType.FAST: 0.5,
}
