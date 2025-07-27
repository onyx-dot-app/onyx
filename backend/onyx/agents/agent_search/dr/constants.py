from onyx.agents.agent_search.dr.models import DRPath
from onyx.agents.agent_search.dr.models import DRTimeBudget

MAX_DR_ITERATION_DEPTH = 5
MAX_CHAT_HISTORY_MESSAGES = (
    3  # note: actual count is x2 to account for user and assistant messages
)
MAX_DR_PARALLEL_SEARCH = 8

CLARIFICATION_REQUEST_PREFIX = "PLEASE CLARIFY:"
HIGH_LEVEL_PLAN_PREFIX = "HIGH_LEVEL PLAN:"

AVERAGE_TOOL_COSTS: dict[DRPath, float] = {
    DRPath.SEARCH: 1.0,
    DRPath.KNOWLEDGE_GRAPH: 2.0,
    DRPath.INTERNET_SEARCH: 1.5,
    DRPath.CLOSER: 0.0,
}

DR_TIME_BUDGET_BY_TYPE = {
    DRTimeBudget.FAST: 3.0,
    DRTimeBudget.SHALLOW: 6.0,
    DRTimeBudget.DEEP: 10.0,
}
