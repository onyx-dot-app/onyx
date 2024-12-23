import asyncio
from collections.abc import AsyncIterable
from collections.abc import Iterable

from langchain_core.runnables.schema import StreamEvent
from langgraph.graph import StateGraph

from onyx.agent_search.main.graph_builder import main_graph_builder
from onyx.agent_search.main.states import MainInput
from onyx.chat.answer import AnswerStream
from onyx.chat.models import AnswerQuestionPossibleReturn
from onyx.context.search.models import SearchRequest
from onyx.db.engine import get_session_context_manager
from onyx.llm.interfaces import LLM
from onyx.tools.models import ToolResponse
from onyx.tools.tool_runner import ToolCallKickoff


def _parse_agent_event(
    event: StreamEvent,
) -> AnswerQuestionPossibleReturn | ToolCallKickoff | ToolResponse | None:
    """
    Parse the event into a typed object.
    Return None if we are not interested in the event.
    """
    event_type = event["event"]
    if event_type == "tool_call_kickoff":
        return ToolCallKickoff(**event["data"])
    elif event_type == "tool_response":
        return ToolResponse(**event["data"])
    elif event_type == "answer_question_possible":
        return AnswerQuestionPossibleReturn(**event["data"])
    return None


def _manage_async_event_streaming(
    graph: StateGraph,
    graph_input: MainInput,
) -> Iterable[StreamEvent]:
    async def _run_async_event_stream() -> AsyncIterable[StreamEvent]:
        compiled_graph = graph.compile()
        async for event in compiled_graph.astream_events(
            input=graph_input,
            # indicating v2 here deserves further scrutiny
            version="v2",
        ):
            yield event

    # This might be able to be simplified
    def _yield_async_to_sync() -> Iterable[StreamEvent]:
        loop = asyncio.new_event_loop()
        try:
            # Get the async generator
            async_gen = _run_async_event_stream()
            # Convert to AsyncIterator
            async_iter = async_gen.__aiter__()
            while True:
                try:
                    # Create a coroutine by calling anext with the async iterator
                    next_coro = anext(async_iter)
                    # Run the coroutine to get the next event
                    event = loop.run_until_complete(next_coro)
                    yield event
                except StopAsyncIteration:
                    break
        finally:
            loop.close()

    return _yield_async_to_sync()


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
        for event in _manage_async_event_streaming(
            graph=compiled_graph, graph_input=input
        ):
            if parsed_object := _parse_agent_event(event):
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
