from langchain_core.callbacks.manager import dispatch_custom_event
from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agent_search.basic.states import BasicInput
from onyx.agent_search.basic.states import BasicOutput
from onyx.agent_search.basic.states import BasicState
from onyx.agent_search.basic.states import BasicStateUpdate
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.chat.stream_processing.utils import (
    map_document_id_order,
)

def basic_graph_builder() -> StateGraph:
    graph = StateGraph(
        state_schema=BasicState,
        input=BasicInput,
        output=BasicOutput,
    )

    ### Add nodes ###

    graph.add_node(
        node="get_response",
        action=get_response,
    )

    ### Add edges ###

    graph.add_edge(start_key=START, end_key="get_response")

    graph.add_conditional_edges("get_response", should_continue, ["get_response", END])
    graph.add_edge(
        start_key="get_response",
        end_key=END,
    )

    return graph


def should_continue(state: BasicState) -> str:
    return (
        END if state["last_llm_call"] is None or state["calls"] > 1 else "get_response"
    )


def get_response(state: BasicState) -> BasicStateUpdate:
    llm = state["llm"]
    current_llm_call = state["last_llm_call"]
    if current_llm_call is None:
        raise ValueError("last_llm_call is None")
    answer_style_config = state["answer_style_config"]
    response_handler_manager = state["response_handler_manager"]
    # DEBUG: good breakpoint
    stream = llm.stream(
        # For tool calling LLMs, we want to insert the task prompt as part of this flow, this is because the LLM
        # may choose to not call any tools and just generate the answer, in which case the task prompt is needed.
        prompt=current_llm_call.prompt_builder.build(),
        tools=[tool.tool_definition() for tool in current_llm_call.tools] or None,
        tool_choice=(
            "required"
            if current_llm_call.tools and current_llm_call.force_use_tool.force_use
            else None
        ),
        structured_response_format=answer_style_config.structured_response_format,
    )

    for response in response_handler_manager.handle_llm_response(stream):
        dispatch_custom_event(
            "basic_response",
            response,
        )


    next_call = response_handler_manager.next_llm_call(current_llm_call)
    if next_call is not None:
        final_search_results, displayed_search_results = SearchTool.get_search_result(
            next_call
        ) or ([], [])
    else:
        final_search_results, displayed_search_results = [], []
        
    response_handler_manager.answer_handler.update((
        final_search_results, 
        map_document_id_order(final_search_results), 
        map_document_id_order(displayed_search_results)))
    return BasicStateUpdate(
        last_llm_call=next_call,
        calls=state["calls"] + 1,
    )


if __name__ == "__main__":
    pass
