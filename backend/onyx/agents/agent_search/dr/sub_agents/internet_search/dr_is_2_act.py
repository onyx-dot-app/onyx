from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import SearchAnswer
from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import BranchUpdate
from onyx.agents.agent_search.dr.utils import convert_inference_sections_to_search_docs
from onyx.agents.agent_search.dr.utils import extract_document_citations
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.agents.agent_search.utils import create_question_prompt
from onyx.chat.models import LlmDoc
from onyx.context.search.models import InferenceSection
from onyx.prompts.dr_prompts import INTERNAL_SEARCH_PROMPTS
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    INTERNET_SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    InternetSearchTool,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.utils.logger import setup_logger

logger = setup_logger()


def internet_search(
    state: BranchInput, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> BranchUpdate:
    """
    LangGraph node to perform a internet search as part of the DR process.
    """

    node_start_time = datetime.now()
    iteration_nr = state.iteration_nr
    parallelization_nr = state.parallelization_nr
    current_step_nr = state.current_step_nr

    if not current_step_nr:
        raise ValueError("Current step number is not set. This should not happen.")

    assistant_system_prompt = state.assistant_system_prompt
    assistant_task_prompt = state.assistant_task_prompt

    search_query = state.branch_question
    if not search_query:
        raise ValueError("search_query is not set")

    # Write the query to the stream. The start is handled in dr_is_1_branch.py.
    write_custom_event(
        current_step_nr,
        SearchToolDelta(
            queries=[search_query],
            documents=[],
        ),
        writer,
    )

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = graph_config.inputs.prompt_builder.raw_user_query
    research_type = graph_config.behavior.research_type

    logger.debug(
        f"Search start for Internet Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    if graph_config.inputs.persona is None:
        raise ValueError("persona is not set")

    if not state.available_tools:
        raise ValueError("available_tools is not set")

    is_tool_info = state.available_tools[state.tools_used[-1]]
    internet_search_tool = cast(InternetSearchTool, is_tool_info.tool_object)

    if internet_search_tool.provider is None:
        raise ValueError(
            "internet_search_tool.provider is not set. This should not happen."
        )

    # Update search parameters
    internet_search_tool.max_chunks = 10
    internet_search_tool.provider.num_results = 10

    retrieved_docs: list[InferenceSection] = []

    for tool_response in internet_search_tool.run(internet_search_query=search_query):
        # get retrieved docs to send to the rest of the graph
        if tool_response.id == INTERNET_SEARCH_RESPONSE_SUMMARY_ID:
            response = cast(SearchResponseSummary, tool_response.response)
            retrieved_docs = response.top_sections
            break

    document_texts_list = []

    for doc_num, retrieved_doc in enumerate(retrieved_docs[:15]):
        if not isinstance(retrieved_doc, (InferenceSection, LlmDoc)):
            raise ValueError(f"Unexpected document type: {type(retrieved_doc)}")
        chunk_text = build_document_context(retrieved_doc, doc_num + 1)
        document_texts_list.append(chunk_text)

    document_texts = "\n\n".join(document_texts_list)

    logger.debug(
        f"Search end/LLM start for Internet Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    # Built prompt

    if research_type == ResearchType.DEEP:
        search_prompt = INTERNAL_SEARCH_PROMPTS[research_type].build(
            search_query=search_query,
            base_question=base_question,
            document_text=document_texts,
        )

        # Run LLM

        search_answer_json = invoke_llm_json(
            llm=graph_config.tooling.primary_llm,
            prompt=create_question_prompt(
                assistant_system_prompt, search_prompt + (assistant_task_prompt or "")
            ),
            schema=SearchAnswer,
            timeout_override=40,
            # max_tokens=3000,
        )

        logger.debug(
            f"LLM/all done for Internet Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
        )

        # get cited documents
        answer_string = search_answer_json.answer
        claims = search_answer_json.claims or []
        reasoning = search_answer_json.reasoning or ""

        (
            citation_numbers,
            answer_string,
            claims,
        ) = extract_document_citations(answer_string, claims)
        cited_documents = {
            citation_number: retrieved_docs[citation_number - 1]
            for citation_number in citation_numbers
        }

    else:
        answer_string = ""
        claims = []
        reasoning = ""
        cited_documents = {
            doc_num + 1: retrieved_doc
            for doc_num, retrieved_doc in enumerate(retrieved_docs[:15])
        }

    write_custom_event(
        current_step_nr,
        SearchToolDelta(
            queries=[],
            documents=convert_inference_sections_to_search_docs(
                retrieved_docs, is_internet=True
            ),
        ),
        writer,
    )

    return BranchUpdate(
        branch_iteration_responses=[
            IterationAnswer(
                tool=is_tool_info.llm_path,
                tool_id=is_tool_info.tool_id,
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=search_query,
                answer=answer_string,
                claims=claims,
                cited_documents=cited_documents,
                reasoning=reasoning,
                additional_data=None,
            )
        ],
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="internet_search",
                node_name="searching",
                node_start_time=node_start_time,
            )
        ],
    )
