from operator import add
from typing import Annotated

from onyx.agents.agent_search.dr.states import LoggerUpdate
from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetSearchResult,
)
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput


class InternetSearchInput(SubAgentInput):
    results_to_open: Annotated[list[tuple[str, InternetSearchResult]], add] = []
    branch_question: Annotated[str, lambda x, y: y] = ""
    branch_questions_to_urls: Annotated[dict[str, list[str]], lambda x, y: y] = {}


class InternetSearchUpdate(LoggerUpdate):
    results_to_open: Annotated[list[tuple[str, InternetSearchResult]], add] = []


class FetchInput(SubAgentInput):
    urls_to_open: list[str]
    branch_questions_to_urls: dict[str, list[str]]
