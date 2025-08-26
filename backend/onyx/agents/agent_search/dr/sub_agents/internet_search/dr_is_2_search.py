from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.enums import DRPath
from onyx.agents.agent_search.dr.models import IterationAnswer
from onyx.agents.agent_search.dr.models import WebSearchAnswer
from onyx.agents.agent_search.dr.sub_agents.internet_search.providers import (
    get_default_provider,
)
from onyx.agents.agent_search.dr.sub_agents.internet_search.providers import (
    InternetSearchResult,
)
from onyx.agents.agent_search.dr.sub_agents.states import BranchInput
from onyx.agents.agent_search.dr.sub_agents.states import BranchUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.agents.agent_search.utils import create_question_prompt
from onyx.utils.logger import setup_logger

logger = setup_logger()


def web_search(
    state: BranchInput, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> BranchUpdate:
    """
    LangGraph node to perform internet search and decide which URLs to fetch.
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

    logger.debug(
        f"Search start for Internet Search {iteration_nr}.{parallelization_nr} at {datetime.now()}"
    )

    if graph_config.inputs.persona is None:
        raise ValueError("persona is not set")

    provider = get_default_provider()
    if not provider:
        raise ValueError("No internet search provider found")

    # Step 1: Perform search
    search_results: list[InternetSearchResult] = []
    try:
        search_results = provider.search(search_query)
    except Exception as e:
        logger.error(f"Error performing search: {e}")

    if not search_results:
        logger.warning("No search results found")

    # Step 2: Agent decides which URLs to open
    search_results_text = "\n\n".join(
        [
            f"{i+1}. {result.title}\n   URL: {result.link}\n"
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
}}

Guidelines:
- Select relevant URLs to open
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
        schema=WebSearchAnswer,
        timeout_override=30,
    )

    return BranchUpdate(
        branch_iteration_responses=[
            IterationAnswer(
                tool=DRPath.INTERNET_SEARCH.value,
                tool_id=1,  # TODO Remove magic number
                iteration_nr=iteration_nr,
                parallelization_nr=parallelization_nr,
                question=search_query,
                answer="",
                claims=[],
                cited_documents={},
                reasoning="",
                additional_data=None,
                urls_to_open=agent_decision.urls_to_open,
            )
        ],
        urls_to_open=agent_decision.urls_to_open,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="internet_search",
                node_name="searching",
                node_start_time=node_start_time,
            )
        ],
    )
