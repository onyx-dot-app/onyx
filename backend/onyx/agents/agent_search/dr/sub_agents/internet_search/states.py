from operator import add
from typing import Annotated

from onyx.agents.agent_search.dr.states import LoggerUpdate
from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput


def dict_op():
    def _f(d1: dict, d2: dict):
        return {**d1, **d2}

    return _f


class InternetSearchInput(SubAgentInput):
    urls_to_open: Annotated[list[tuple[str, str]], add] = []
    parallelization_nr: Annotated[int, add] = 0
    branch_question: Annotated[str, add] = ""
    deduped_branch_question_to_urls: Annotated[dict[str, list[str]], dict_op()] = {}


class InternetSearchUpdate(LoggerUpdate):
    urls_to_open: Annotated[list[tuple[str, str]], add] = []


class FetchInput(BranchInput):
    urls_to_open: list[str]
