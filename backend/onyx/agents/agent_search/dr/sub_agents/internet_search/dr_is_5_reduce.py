from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentMainState
from onyx.agents.agent_search.dr.sub_agents.states import SubAgentUpdate
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.context.search.models import InferenceSection
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.utils.logger import setup_logger


logger = setup_logger()


# # Process documents and build context
# document_texts_list = []
# for doc_num, retrieved_doc in enumerate(retrieved_docs):
#     if not isinstance(retrieved_doc, (InferenceSection, LlmDoc)):
#         raise ValueError(f"Unexpected document type: {type(retrieved_doc)}")
#     chunk_text = build_document_context(retrieved_doc, doc_num + 1)
#     document_texts_list.append(chunk_text)

# document_texts = "\n\n".join(document_texts_list)

# if research_type == ResearchType.DEEP:
#     search_prompt = INTERNAL_SEARCH_PROMPTS[research_type].build(
#         search_query=state.branch_question,
#         base_question=base_question,
#         document_text=document_texts,
#     )

#     search_answer_json = invoke_llm_json(
#         llm=graph_config.tooling.primary_llm,
#         prompt=create_question_prompt(
#             assistant_system_prompt, search_prompt + (assistant_task_prompt or "")
#         ),
#         schema=SearchAnswer,
#         timeout_override=40,
#     )

#     answer_string = search_answer_json.answer
#     claims = search_answer_json.claims or []
#     reasoning = search_answer_json.reasoning or ""

#     (
#         citation_numbers,
#         answer_string,
#         claims,
#     ) = extract_document_citations(answer_string, claims)
#     cited_documents = {
#         citation_number: retrieved_docs[citation_number - 1]
#         for citation_number in citation_numbers
#     }

# else:
#     answer_string = ""
#     claims = []
#     reasoning = ""
#     cited_documents = {
#         doc_num + 1: retrieved_doc
#         for doc_num, retrieved_doc in enumerate(retrieved_docs[:15])
#     }


# return BranchUpdate(
#     branch_iteration_responses=[
#         IterationAnswer(
#             tool=is_tool_info.llm_path,
#             tool_id=is_tool_info.tool_id,
#             iteration_nr=iteration_nr,
#             parallelization_nr=parallelization_nr,
#             question=state.branch_question,
#             answer=answer_string,
#             claims=claims,
#             cited_documents=cited_documents,
#             reasoning=reasoning,
#             additional_data=None,
#         )
#     ],
#     log_messages=[
#         get_langgraph_node_log_string(
#             graph_component="internet_search",
#             node_name="fetching",
#             node_start_time=node_start_time,
#         )
#     ],
# )
# pass content to orchestrator
def is_reducer(
    state: SubAgentMainState,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> SubAgentUpdate:
    """
    LangGraph node to perform a internet search as part of the DR process.
    """

    node_start_time = datetime.now()

    # build branch iterations from fetch inputs
    url_to_raw_document: dict[str, InferenceSection] = {}
    for raw_document in state.raw_documents:
        url_to_raw_document[raw_document.center_chunk.semantic_identifier] = (
            raw_document
        )

    current_iteration = state.iteration_nr
    current_step_nr = state.current_step_nr
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    research_type = graph_config.behavior.research_type

    new_updates: list[IterationAnswer] = []
    if research_type == ResearchType.DEEP:
        pass
    else:
        answer_string = ""
        reasoning = ""
        for branch_question, urls in state.branch_questions_to_urls.items():
            cited_raw_documents = [url_to_raw_document[url] for url in urls]
            cited_documents = {
                doc_num + 1: retrieved_doc
                for doc_num, retrieved_doc in enumerate(cited_raw_documents)
            }
            if not state.available_tools:
                raise ValueError("available_tools is not set")
            is_tool_info = state.available_tools[state.tools_used[-1]]
            new_updates.append(
                IterationAnswer(
                    tool=is_tool_info.llm_path,
                    tool_id=is_tool_info.tool_id,
                    iteration_nr=current_iteration,
                    parallelization_nr=0,
                    answer=answer_string,
                    claims=None,
                    reasoning=reasoning,
                    question=branch_question,
                    cited_documents=cited_documents,
                    additional_data=None,
                )
            )

    write_custom_event(
        current_step_nr,
        SectionEnd(),
        writer,
    )

    current_step_nr += 1

    return SubAgentUpdate(
        iteration_responses=new_updates,
        current_step_nr=current_step_nr,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="internet_search",
                node_name="consolidation",
                node_start_time=node_start_time,
            )
        ],
    )


def _create_document_texts(raw_documents: list[InferenceSection]) -> str:
    document_texts_list = []
    for doc_num, retrieved_doc in enumerate(raw_documents):
        if not isinstance(retrieved_doc, InferenceSection):
            raise ValueError(f"Unexpected document type: {type(retrieved_doc)}")
        chunk_text = build_document_context(retrieved_doc, doc_num + 1)
        document_texts_list.append(chunk_text)
    return "\n\n".join(document_texts_list)
