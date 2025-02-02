from operator import add
from typing import Annotated
from typing import TypedDict

from onyx.agents.agent_search.core_state import CoreState
from onyx.agents.agent_search.deep_search.main.states import (
    ExploratorySearchUpdate,
)
from onyx.agents.agent_search.deep_search.main.states import (
    InitialAnswerQualityUpdate,
)
from onyx.agents.agent_search.deep_search.main.states import (
    InitialAnswerUpdate,
)
from onyx.agents.agent_search.deep_search.main.states import (
    InitialQuestionDecompositionUpdate,
)
from onyx.agents.agent_search.deep_search.main.states import (
    OrigQuestionRetrievalUpdate,
)
from onyx.agents.agent_search.deep_search.main.states import (
    SubQuestionResultsUpdate,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.models import (
    QuestionRetrievalResult,
)
from onyx.context.search.models import InferenceSection


### States ###
class SubQuestionRetrievalInput(CoreState):
    exploratory_search_results: list[InferenceSection]


## Graph State
class SubQuestionRetrievalState(
    # This includes the core state
    SubQuestionRetrievalInput,
    InitialQuestionDecompositionUpdate,
    InitialAnswerUpdate,
    SubQuestionResultsUpdate,
    OrigQuestionRetrievalUpdate,
    InitialAnswerQualityUpdate,
    ExploratorySearchUpdate,
):
    base_raw_search_result: Annotated[list[QuestionRetrievalResult], add]


## Graph Output State
class SubQuestionRetrievalOutput(TypedDict):
    log_messages: list[str]
