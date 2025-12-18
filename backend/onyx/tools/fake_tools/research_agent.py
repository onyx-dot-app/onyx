from collections.abc import Callable

from pydantic import BaseModel

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.emitter import Emitter
from onyx.context.search.models import SearchDoc
from onyx.llm.interfaces import LLM
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool import Tool
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()

RESEARCH_CYCLE_CAP = 3


class ResearchAgentCallResult(BaseModel):
    report: str
    search_docs: list[SearchDoc]


def run_research_agent_call(
    research_agent_call: ToolCallKickoff,
    tools: list[Tool],
    emitter: Emitter,
    state_container: ChatStateContainer,
    llm: LLM,
    token_counter: Callable[[str], int],
) -> ResearchAgentCallResult:
    return ResearchAgentCallResult(report="report 1", search_docs=[])


def run_research_agent_calls(
    research_agent_calls: list[ToolCallKickoff],
    tools: list[Tool],
    emitter: Emitter,
    state_container: ChatStateContainer,
    llm: LLM,
    token_counter: Callable[[str], int],
) -> list[ResearchAgentCallResult]:
    # Run all research agent calls in parallel
    functions_with_args = [
        (
            run_research_agent_call,
            (research_agent_call, tools, emitter, state_container, llm, token_counter),
        )
        for research_agent_call in research_agent_calls
    ]

    return run_functions_tuples_in_parallel(
        functions_with_args,
        allow_failures=True,  # Continue even if some research agent calls fail
    )
