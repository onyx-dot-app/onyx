from operator import add
from typing import Annotated

from onyx.agents.agent_search.dr.states import LoggerUpdate
from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput


class InternetSearchInput(SubAgentInput):
    urls_to_open: Annotated[list[tuple[str, str]], add] = []
    branch_question: Annotated[str, lambda x, y: y] = ""
    deduped_branch_question_to_urls: Annotated[dict[str, list[str]], lambda x, y: y] = (
        {}
    )


class InternetSearchUpdate(LoggerUpdate):
    urls_to_open: Annotated[list[tuple[str, str]], add] = []


class FetchInput(BranchInput):
    urls_to_open: list[str]
