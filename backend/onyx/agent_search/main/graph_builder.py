from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph

from onyx.agent_search.answer_question.graph_builder import answer_query_graph_builder
from onyx.agent_search.expanded_retrieval.graph_builder import (
    expanded_retrieval_graph_builder,
)
from onyx.agent_search.main.edges import parallelize_decompozed_answer_queries
from onyx.agent_search.main.edges import send_to_initial_retrieval
from onyx.agent_search.main.nodes.base_decomp import main_decomp_base
from onyx.agent_search.main.nodes.generate_initial_answer import (
    generate_initial_answer,
)
from onyx.agent_search.main.nodes.ingest_answers import ingest_answers
from onyx.agent_search.main.nodes.ingest_initial_retrieval import (
    ingest_initial_retrieval,
)
from onyx.agent_search.main.states import MainInput
from onyx.agent_search.main.states import MainState


def main_graph_builder() -> StateGraph:
    graph = StateGraph(
        state_schema=MainState,
        input=MainInput,
    )

    ### Add nodes ###

    graph.add_node(
        node="base_decomp",
        action=main_decomp_base,
    )
    answer_query_subgraph = answer_query_graph_builder().compile()
    graph.add_node(
        node="answer_query",
        action=answer_query_subgraph,
    )
    expanded_retrieval_subgraph = expanded_retrieval_graph_builder().compile()
    graph.add_node(
        node="initial_retrieval",
        action=expanded_retrieval_subgraph,
    )
    graph.add_node(
        node="ingest_initial_retrieval",
        action=ingest_initial_retrieval,
    )
    graph.add_node(
        node="ingest_answers",
        action=ingest_answers,
    )
    graph.add_node(
        node="generate_initial_answer",
        action=generate_initial_answer,
    )

    ### Add edges ###

    graph.add_conditional_edges(
        source=START,
        path=send_to_initial_retrieval,
        path_map=["initial_retrieval"],
    )
    graph.add_edge(
        start_key="initial_retrieval",
        end_key="ingest_initial_retrieval",
    )

    graph.add_edge(
        start_key=START,
        end_key="base_decomp",
    )
    graph.add_conditional_edges(
        source="base_decomp",
        path=parallelize_decompozed_answer_queries,
        path_map=["answer_query"],
    )
    graph.add_edge(
        start_key="answer_query",
        end_key="ingest_answers",
    )

    graph.add_edge(
        start_key=["ingest_answers", "ingest_initial_retrieval"],
        end_key="generate_initial_answer",
    )
    graph.add_edge(
        start_key="generate_initial_answer",
        end_key=END,
    )

    return graph


# from langgraph_sdk import get_client

# client = get_client(url="http://localhost:8000")
# # Using the graph deployed with the name "agent"
# assistant_id = "agent"
# # create thread
# thread = await client.threads.create()
# print(thread)
# # create input
# input = {
#     "messages": [
#         {
#             "role": "user",
#             "content": "What's the weather in SF?",
#         }
#     ]
# }

# # stream events
# async for chunk in client.runs.stream(
#     thread_id=thread["thread_id"],
#     assistant_id=assistant_id,
#     input=input,
#     stream_mode="events",
# ):
#     print(f"Receiving new event of type: {chunk.event}...")
#     print(chunk.data)
#     print("\n\n")

if __name__ == "__main__":
    from onyx.db.engine import get_session_context_manager
    from onyx.llm.factory import get_default_llms
    from onyx.context.search.models import SearchRequest

    graph = main_graph_builder()
    compiled_graph = graph.compile()
    primary_llm, fast_llm = get_default_llms()
    search_request = SearchRequest(
        query="what can you do with onyx or danswer?",
    )
    with get_session_context_manager() as db_session:
        inputs = MainInput(
            search_request=search_request,
            primary_llm=primary_llm,
            fast_llm=fast_llm,
            db_session=db_session,
        )
        for thing in compiled_graph.stream(
            input=inputs,
            stream_mode="messages",
            # subgraphs=True,
        ):
            print(thing)
            # print()
        print("done")
