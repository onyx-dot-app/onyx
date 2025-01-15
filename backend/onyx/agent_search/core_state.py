from operator import add
from typing import Annotated
from typing import TypedDict
from typing import TypeVar

from sqlalchemy.orm import Session

from onyx.chat.models import ProSearchConfig
from onyx.db.models import User
from onyx.llm.interfaces import LLM
from onyx.tools.tool_implementations.search.search_tool import SearchTool


class CoreState(TypedDict, total=False):
    """
    This is the core state that is shared across all subgraphs.
    """

    config: ProSearchConfig
    primary_llm: LLM
    fast_llm: LLM
    # a single session for the entire agent search
    # is fine if we are only reading
    db_session: Session
    user: User | None
    log_messages: Annotated[list[str], add]
    search_tool: SearchTool


class SubgraphCoreState(TypedDict, total=False):
    """
    This is the core state that is shared across all subgraphs.
    """

    subgraph_config: ProSearchConfig
    subgraph_primary_llm: LLM
    subgraph_fast_llm: LLM
    # a single session for the entire agent search
    # is fine if we are only reading
    subgraph_db_session: Session

    subgraph_search_tool: SearchTool


# This ensures that the state passed in extends the CoreState
T = TypeVar("T", bound=CoreState)
T_SUBGRAPH = TypeVar("T_SUBGRAPH", bound=SubgraphCoreState)


def extract_core_fields(state: T) -> CoreState:
    filtered_dict = {k: v for k, v in state.items() if k in CoreState.__annotations__}
    return CoreState(**dict(filtered_dict))  # type: ignore


def extract_core_fields_for_subgraph(state: T) -> SubgraphCoreState:
    filtered_dict = {
        "subgraph_" + k: v for k, v in state.items() if k in CoreState.__annotations__
    }
    return SubgraphCoreState(**dict(filtered_dict))  # type: ignore


def in_subgraph_extract_core_fields(state: T_SUBGRAPH) -> SubgraphCoreState:
    filtered_dict = {
        k: v for k, v in state.items() if k in SubgraphCoreState.__annotations__
    }
    return SubgraphCoreState(**dict(filtered_dict))  # type: ignore
