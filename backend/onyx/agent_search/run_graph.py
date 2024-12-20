from typing import Any

from onyx.agent_search.main.graph_builder import main_graph_builder
from onyx.agent_search.main.states import MainInput
from onyx.chat.answer import AnswerStream
from onyx.chat.models import AnswerQuestionPossibleReturn
from onyx.context.search.models import SearchRequest
from onyx.db.engine import get_session_context_manager
from onyx.llm.interfaces import LLM
from onyx.tools.models import ToolResponse
from onyx.tools.tool_runner import ToolCallKickoff


def _parse_agent_output(
    output: dict[str, Any] | Any
) -> AnswerQuestionPossibleReturn | ToolCallKickoff | ToolResponse:
    if isinstance(output, dict):
        return output
    return output.model_dump()


def run_graph(
    search_request: SearchRequest,
    primary_llm: LLM,
    fast_llm: LLM,
) -> AnswerStream:
    graph = main_graph_builder()

    with get_session_context_manager() as db_session:
        input = MainInput(
            search_request=search_request,
            primary_llm=primary_llm,
            fast_llm=fast_llm,
            db_session=db_session,
        )
        compiled_graph = graph.compile()
        for output in compiled_graph.stream(
            input=input,
            stream_mode="values",
            subgraphs=True,
        ):
            parsed_object = _parse_agent_output(output)
            yield parsed_object


if __name__ == "__main__":
    from onyx.llm.factory import get_default_llms
    from onyx.context.search.models import SearchRequest

    graph = main_graph_builder()
    compiled_graph = graph.compile()
    primary_llm, fast_llm = get_default_llms()
    search_request = SearchRequest(
        query="what can you do with onyx or danswer?",
    )
    for output in run_graph(search_request, primary_llm, fast_llm):
        print(output)
