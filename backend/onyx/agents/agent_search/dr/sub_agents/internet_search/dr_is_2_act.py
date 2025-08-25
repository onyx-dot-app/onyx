from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import SearchAnswer
from onyx.agents.agent_search.dr.models import SurfaceSearchAnswer
from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import BranchUpdate
from onyx.agents.agent_search.dr.utils import extract_document_citations
from onyx.agents.agent_search.kb_search.graph_utils import build_document_context
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.utils import create_question_prompt
from onyx.chat.models import LlmDoc
from onyx.context.search.models import InferenceSection
from onyx.prompts.dr_prompts import INTERNAL_SEARCH_PROMPTS
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    InternetSearchOnlyTool,
)
from onyx.tools.tool_implementations.internet_search.internet_search_tool import (
    InternetUrlOpenTool,
)
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

    assistant_system_prompt = state.assistant_system_prompt
    assistant_task_prompt = state.assistant_task_prompt

    search_query = state.branch_question
    if not search_query:
        raise ValueError("search_query is not set")

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
    # Find the search and URL opening tools
    search_tool = None
    url_open_tool = None
    for tool_info in state.available_tools.values():
        if isinstance(tool_info.tool_object, InternetSearchOnlyTool):
            search_tool = cast(InternetSearchOnlyTool, tool_info.tool_object)
        elif isinstance(tool_info.tool_object, InternetUrlOpenTool):
            url_open_tool = cast(InternetUrlOpenTool, tool_info.tool_object)

    if search_tool is None:
        raise ValueError("search_tool is not set")
    if url_open_tool is None:
        raise ValueError("url_open_tool is not set")

    # Fetch search results (fetch more results, like 10)
    search_results = []
    try:
        for tool_response in search_tool.run(internet_search_query=search_query):
            if tool_response.id == "internet_search_results":
                search_results = tool_response.response["results"]
                break
    except Exception as e:
        logger.error(f"Error performing search: {e}")

    if not search_results:
        logger.warning("No search results found")

    # Step 2: Agent decides which URLs to open
    search_results_text = "\n\n".join(
        [
            f"{i+1}. {result['title']}\n   URL: {result['link']}\n"
            for i, result in enumerate(search_results)
        ]
    )
    agent_decision_prompt = f"""
You are an intelligent agent tasked with gathering information from the internet to answer: "{base_question}"

You have performed a search and received the following results:

{search_results_text}

Your task is to:
1. Analyze which URLs are most relevant to the original question
2. Decide how many URLs to open (consider time and relevance)
3. Determine if you need to perform additional searches with different queries

Based on the search results above, please make your decision and return a JSON object with this structure:

{{
    "urls_to_open": ["<url1>", "<url2>", "<url3>"],
    "need_additional_search": <true/false>,
    "additional_search_query": "<if need_additional_search is true, provide a refined search query>",
    "reasoning": "<overall reasoning for your decisions>"
}}

Guidelines:
- Select 2-4 most relevant URLs to open
- Only suggest additional searches if the current results don't seem sufficient
- Consider the title, snippet, and URL when making decisions
- Focus on quality over quantity
"""
    agent_decision = invoke_llm_json(
        llm=graph_config.tooling.primary_llm,
        prompt=create_question_prompt(
            assistant_system_prompt,
            agent_decision_prompt + (assistant_task_prompt or ""),
        ),
        schema=SurfaceSearchAnswer,
        timeout_override=30,
    )
    # Open URLs and fetch content
    retrieved_docs: list[InferenceSection] = []
    urls_to_open = agent_decision.urls_to_open
    for tool_response in url_open_tool.run(urls=",".join(urls_to_open)):
        if tool_response.id == "url_content":
            url_content = tool_response.response
            retrieved_docs = url_content["documents"]
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
