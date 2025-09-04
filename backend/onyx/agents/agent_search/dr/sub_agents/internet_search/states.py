from operator import add
from typing import Annotated

from onyx.agents.agent_search.dr.states import LoggerUpdate
from onyx.agents.agent_search.dr.sub_agents.internet_search.models import (
    InternetSearchResult,
)
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentInput
from onyx.context.search.models import InferenceSection


class InternetSearchInput(SubAgentInput):
    results_to_open: Annotated[list[tuple[str, InternetSearchResult]], add] = []
    parallelization_nr: int = 0
    branch_question: Annotated[str, lambda x, y: y] = ""
    branch_questions_to_urls: Annotated[dict[str, list[str]], lambda x, y: y] = {}
    raw_documents: Annotated[list[InferenceSection], add] = []


class InternetSearchUpdate(LoggerUpdate):
    results_to_open: Annotated[list[tuple[str, InternetSearchResult]], add] = []


class FetchInput(SubAgentInput):
    urls_to_open: Annotated[list[str], add] = []
    branch_questions_to_urls: dict[str, list[str]]
    raw_documents: Annotated[list[InferenceSection], add] = []


class FetchUpdate(LoggerUpdate):
    raw_documents: Annotated[list[InferenceSection], add] = []


class SummarizeInput(SubAgentInput):
    raw_documents: Annotated[list[InferenceSection], add] = []
    branch_questions_to_urls: dict[str, list[str]]
    branch_question: str
