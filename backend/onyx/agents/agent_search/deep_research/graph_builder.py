import random
from datetime import datetime
from json import JSONDecodeError
from pprint import pprint
from typing import cast

from langchain.globals import set_debug
from langchain.globals import set_verbose
from langchain_core.messages import AIMessage
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from langgraph.types import Send
from langgraph.types import StreamWriter

from onyx.agents.agent_search.deep_research.configuration import (
    DeepPlannerConfiguration,
)
from onyx.agents.agent_search.deep_research.configuration import (
    DeepResearchConfiguration,
)
from onyx.agents.agent_search.deep_research.prompts import answer_instructions
from onyx.agents.agent_search.deep_research.prompts import COMPANY_CONTEXT
from onyx.agents.agent_search.deep_research.prompts import COMPANY_NAME
from onyx.agents.agent_search.deep_research.prompts import get_current_date
from onyx.agents.agent_search.deep_research.prompts import planner_prompt
from onyx.agents.agent_search.deep_research.prompts import query_writer_instructions
from onyx.agents.agent_search.deep_research.prompts import reflection_instructions
from onyx.agents.agent_search.deep_research.prompts import replanner_prompt
from onyx.agents.agent_search.deep_research.prompts import task_completion_prompt
from onyx.agents.agent_search.deep_research.prompts import task_to_query_prompt
from onyx.agents.agent_search.deep_research.states import OnyxSearchState
from onyx.agents.agent_search.deep_research.states import OverallState
from onyx.agents.agent_search.deep_research.states import PlanExecute
from onyx.agents.agent_search.deep_research.states import QueryGenerationState
from onyx.agents.agent_search.deep_research.states import ReflectionState
from onyx.agents.agent_search.deep_research.tools_and_schemas import Act
from onyx.agents.agent_search.deep_research.tools_and_schemas import json_to_pydantic
from onyx.agents.agent_search.deep_research.tools_and_schemas import Plan
from onyx.agents.agent_search.deep_research.tools_and_schemas import Reflection
from onyx.agents.agent_search.deep_research.tools_and_schemas import Response
from onyx.agents.agent_search.deep_research.tools_and_schemas import SearchQueryList
from onyx.agents.agent_search.deep_research.utils import collate_messages
from onyx.agents.agent_search.deep_research.utils import get_research_topic
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import AgentAnswerPiece
from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import CitationConfig
from onyx.chat.models import DocumentPruningConfig
from onyx.chat.models import PromptConfig
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.models import InferenceSection
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import Persona
from onyx.llm.factory import get_default_llms
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.natural_language_processing.utils import tokenizer_trim_content
from onyx.tools.models import SearchToolOverrideKwargs
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.utils.logger import setup_logger

logger = setup_logger()

test_mode = False
IS_DEBUG = False
IS_VERBOSE = False
MAX_RETRIEVED_DOCS = 10


def mock_do_onyx_search(query: str) -> str:
    random_answers = [
        "Onyx is a startup founded by Yuhong Sun and Chris Weaver.",
        "Chris Weaver was born in the country of Wakanda",
        "Yuhong Sun is the CEO of Onyx",
        "Yuhong Sun was born in the country of Valhalla",
    ]
    return {"text": random.choice(random_answers)}


def do_onyx_search(query: str) -> dict[str, str]:
    """
    Perform a search using the SearchTool and return the results.

    Args:
        query: The search query string

    Returns:
        Dictionary containing the search results text
    """
    retrieved_docs: list[InferenceSection] = []
    primary_llm, fast_llm = get_default_llms()
    try:
        with get_session_with_current_tenant() as db_session:
            # Create a default persona with basic settings
            default_persona = Persona(
                name="default",
                chunks_above=2,
                chunks_below=2,
                description="Default persona for search",
            )

            search_tool = SearchTool(
                db_session=db_session,
                user=None,
                persona=default_persona,
                retrieval_options=None,
                prompt_config=PromptConfig(
                    system_prompt="You are a helpful assistant.",
                    task_prompt="Answer the user's question based on the provided context.",
                    datetime_aware=True,
                    include_citations=True,
                ),
                llm=primary_llm,
                fast_llm=fast_llm,
                pruning_config=DocumentPruningConfig(),
                answer_style_config=AnswerStyleConfig(
                    citation_config=CitationConfig(
                        include_citations=True, citation_style="inline"
                    )
                ),
                evaluation_type=LLMEvaluationType.SKIP,
            )

            for tool_response in search_tool.run(
                query=query,
                override_kwargs=SearchToolOverrideKwargs(
                    force_no_rerank=True,
                    alternate_db_session=db_session,
                    retrieved_sections_callback=None,
                    skip_query_analysis=False,
                ),
            ):
                if tool_response.id == SEARCH_RESPONSE_SUMMARY_ID:
                    response = cast(SearchResponseSummary, tool_response.response)
                    retrieved_docs = response.top_sections
                    break

        # Combine the retrieved documents into a single text
        combined_text = "\n\n".join(
            [doc.combined_content for doc in retrieved_docs[:MAX_RETRIEVED_DOCS]]
        )
        return {"text": combined_text}
    except Exception as e:
        logger.error(f"Error in do_onyx_search: {e}")
        return {"text": "Error in search, no results returned"}


def generate_query(state: OverallState, config: RunnableConfig) -> QueryGenerationState:
    """
    LangGraph node that generates a search queries based on the User's question.

    Uses an LLM to create an optimized search query for onyx research based on
    the User's question.

    Args:
        state: Current graph state containing the User's question
        config: Configuration for the runnable

    Returns:
        Dictionary with state update, including search_query key containing the generated query
    """
    configurable = DeepResearchConfiguration.from_runnable_config(config)

    # check for custom initial search query count
    if state.get("initial_search_query_count") is None:
        state["initial_search_query_count"] = configurable.number_of_initial_queries

    primary_llm, fast_llm = get_default_llms()
    llm = primary_llm if configurable.query_generator_model == "primary" else fast_llm

    # Format the prompt
    current_date = get_current_date()
    formatted_prompt = query_writer_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        number_queries=state["initial_search_query_count"],
        company_name=COMPANY_NAME,
        company_context=COMPANY_CONTEXT,
        user_context=collate_messages(state["messages"]),
    )

    # Get the LLM response and extract its content
    llm_response = llm.invoke(formatted_prompt)
    try:
        result = json_to_pydantic(llm_response.content, SearchQueryList)
        return {"query_list": result.query}
    except JSONDecodeError:
        return {"query_list": [llm_response.content]}


def continue_to_onyx_research(state: QueryGenerationState) -> OverallState:
    """
    LangGraph node that sends the search queries to the onyx research node.

    This is used to spawn n number of onyx research nodes, one for each search query.
    """
    return [
        Send("onyx_research", {"search_query": search_query, "id": int(idx)})
        for idx, search_query in enumerate(state["query_list"])
    ]


def onyx_research(state: OnyxSearchState, config: RunnableConfig) -> OverallState:
    """LangGraph node that performs onyx research using onyx search interface.

    Executes an onyx search in combination with an llm.

    Args:
        state: Current graph state containing the search query and research loop count
        config: Configuration for the runnable, including any search API settings or llm settings

    Returns:
        Dictionary with state update, including sources_gathered, research_loop_count, and web_research_results
    """
    # TODO: think about whether we should use any filtered returned results in addition to the final text answer
    response = do_onyx_search(state["search_query"])

    text = response["text"]
    sources_gathered = []

    return {
        "sources_gathered": sources_gathered,
        "search_query": [state["search_query"]],
        "onyx_research_result": [text],
    }


def get_combined_summaries(state: OverallState, llm=None) -> str:
    if llm is None:
        _, llm = get_default_llms()

    # Calculate tokens and trim if needed
    tokenizer = get_tokenizer(
        provider_type=llm.config.model_provider, model_name=llm.config.model_name
    )

    # Combine summaries and check token count
    combined_summaries = "\n\n---\n\n".join(state["onyx_research_result"])
    combined_summaries = tokenizer_trim_content(
        content=combined_summaries, desired_length=10000, tokenizer=tokenizer
    )
    return combined_summaries


def reflection(state: OverallState, config: RunnableConfig) -> ReflectionState:
    """LangGraph node that identifies knowledge gaps and generates potential follow-up queries.

    Analyzes the current summary to identify areas for further research and generates
    potential follow-up queries. Uses structured output to extract
    the follow-up query in JSON format.

    Args:
        state: Current graph state containing the running summary and research topic
        config: Configuration for the runnable, including LLM settings

    Returns:
        Dictionary with state update, including search_query key containing the generated follow-up query
    """
    configurable = DeepResearchConfiguration.from_runnable_config(config)
    # Increment the research loop count and get the reasoning model
    state["research_loop_count"] = state.get("research_loop_count", 0) + 1

    # Get the LLM to use for token counting
    primary_llm, fast_llm = get_default_llms()
    llm = primary_llm if configurable.reflection_model == "primary" else fast_llm
    combined_summaries = get_combined_summaries(state, llm)

    # Format the prompt
    # First, collate the messages to give a historical context of the current conversation
    # Then, produce a concatenation of the onyx research results
    # Then, pass this to the reflection instructions
    # Then, the LLM will produce a JSON response with the following fields:
    # - is_sufficient: boolean indicating if the research is sufficient
    # - knowledge_gap: string describing the knowledge gap
    # - follow_up_queries: list of follow-up queries
    current_date = get_current_date()
    formatted_prompt = reflection_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        summaries=combined_summaries,
        company_name=COMPANY_NAME,
        company_context=COMPANY_CONTEXT,
    )

    # Get result from LLM
    result = json_to_pydantic(llm.invoke(formatted_prompt).content, Reflection)

    # TODO: convert to pydantic here
    return {
        "is_sufficient": result.is_sufficient,
        "knowledge_gap": result.knowledge_gap,
        "follow_up_queries": result.follow_up_queries,
        "research_loop_count": state["research_loop_count"],
        "number_of_ran_queries": len(state["search_query"]),
    }


def strtobool(val):
    """Convert a string representation of truth to true (1) or false (0).
    True values are 'y', 'yes', 't', 'true', 'on', and '1'; false values
    are 'n', 'no', 'f', 'false', 'off', and '0'.  Raises ValueError if
    'val' is anything else.
    """
    if isinstance(val, bool):
        return val
    val = val.lower()
    if val in ("y", "yes", "t", "true", "on", "1"):
        return 1
    elif val in ("n", "no", "f", "false", "off", "0"):
        return 0
    else:
        raise ValueError("invalid truth value %r" % (val,))


def evaluate_research(
    state: ReflectionState,
    config: RunnableConfig,
) -> OverallState:
    """LangGraph routing function that determines the next step in the research flow.

    Controls the research loop by deciding whether to continue gathering information
    or to finalize the summary based on the configured maximum number of research loops.

    Args:
        state: Current graph state containing the research loop count
        config: Configuration for the runnable, including max_research_loops setting

    Returns:
        String literal indicating the next node to visit ("onyx_research" or "finalize_summary")
    """
    configurable = DeepResearchConfiguration.from_runnable_config(config)
    max_research_loops = (
        state.get("max_research_loops")
        if state.get("max_research_loops") is not None
        else configurable.max_research_loops
    )
    if (
        strtobool(state["is_sufficient"]) is True
        or state["research_loop_count"] >= max_research_loops
    ):
        return "finalize_answer"
    else:
        return [
            Send(
                "onyx_research",
                {
                    "search_query": follow_up_query,
                    "id": state["number_of_ran_queries"] + int(idx),
                },
            )
            for idx, follow_up_query in enumerate(state["follow_up_queries"])
        ]


def finalize_answer(state: OverallState, config: RunnableConfig):
    """LangGraph node that finalizes the research summary.

    Prepares the final result based on the onyx research results.

    Args:
        state: Current graph state containing the running summary and sources gathered

    Returns:
        Dictionary with state update, including running_summary key containing the formatted final summary with sources
    """
    configurable = DeepResearchConfiguration.from_runnable_config(config)
    answer_model = state.get("answer_model") or configurable.answer_model

    # get the LLM to generate the final answer
    primary_llm, fast_llm = get_default_llms()
    llm = primary_llm if answer_model == "primary" else fast_llm
    combined_summaries = get_combined_summaries(state, llm)

    # Format the prompt
    current_date = get_current_date()
    formatted_prompt = answer_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        summaries=combined_summaries,
        company_name=COMPANY_NAME,
        company_context=COMPANY_CONTEXT,
        user_context=collate_messages(state["messages"]),
    )

    result = llm.invoke(formatted_prompt)
    unique_sources = []
    return {
        "messages": [AIMessage(content=result.content)],
        "sources_gathered": unique_sources,
    }


def deep_research_graph_builder(test_mode: bool = False) -> StateGraph:
    """
    LangGraph graph builder for deep research process.
    """

    graph = StateGraph(
        OverallState,
        config_schema=DeepResearchConfiguration,
    )

    ### Add nodes ###

    graph.add_node("generate_query", generate_query)
    graph.add_node("onyx_research", onyx_research)
    graph.add_node("reflection", reflection)
    graph.add_node("finalize_answer", finalize_answer)

    # Set the entrypoint as `generate_query`
    graph.add_edge(START, "generate_query")
    # Add conditional edge to continue with search queries in a parallel branch
    graph.add_conditional_edges(
        "generate_query", continue_to_onyx_research, ["onyx_research"]
    )
    # Reflect on the onyx research
    graph.add_edge("onyx_research", "reflection")
    # Evaluate the research
    graph.add_conditional_edges(
        "reflection", evaluate_research, ["onyx_research", "finalize_answer"]
    )
    # Finalize the answer
    graph.add_edge("finalize_answer", END)

    return graph


def translate_task_to_query(
    task: str,
    context=None,
    company_name=COMPANY_NAME,
    company_context=COMPANY_CONTEXT,
    initial_question=None,
) -> str:
    """
    LangGraph node that translates a task to a query.
    """
    _, fast_llm = get_default_llms()

    formatted_prompt = task_to_query_prompt.format(
        initial_question=initial_question,
        task=task,
        context=context,
        company_name=company_name,
        company_context=company_context,
    )
    return fast_llm.invoke(formatted_prompt).content


def is_search_query(query: str) -> bool:
    terms = [
        "search",
        "query",
        "find",
        "look up",
        "look for",
        "find out",
        "find information",
        "find data",
        "find facts",
        "find statistics",
        "find trends",
        "find insights",
        "find trends",
        "find insights",
        "find trends",
        "find insights",
        "gather",
        "gather information",
        "gather data",
        "gather facts",
        "gather statistics",
        "gather trends",
        "gather insights",
    ]
    query = query.lower()
    for term in terms:
        if term in query:
            return True
    return False


def execute_step(
    state: PlanExecute, config: RunnableConfig, writer: StreamWriter = lambda _: None
):
    """
    LangGraph node that plans the deep research process.
    """
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.prompt_builder.raw_user_query
    plan = state["plan"]
    task = plan[0]
    step_count = state.get("step_count", 0) + 1
    if is_search_query(task):
        query = translate_task_to_query(
            plan[0], context=state["past_steps"], initial_question=question
        )
        write_custom_event(
            "refined_agent_answer",
            AgentAnswerPiece(
                answer_piece="  executing a search query with Onyx...",
                level=0,
                level_question_num=0,
                answer_type="agent_level_answer",
            ),
            writer,
        )
        graph = deep_research_graph_builder()
        compiled_graph = graph.compile(debug=IS_DEBUG)
        # TODO: use this input_state for the deep research graph
        # input_state = DeepResearchInput(log_messages=[])

        initial_state = {
            "messages": [HumanMessage(content=query)],
            "search_query": [],
            "onyx_research_result": [],
            "sources_gathered": [],
            "initial_search_query_count": 3,  # Default value from Configuration
            "max_research_loops": 2,  # State does not seem to pick up this value
            "research_loop_count": 0,
            "reasoning_model": "primary",
        }

        result = compiled_graph.invoke(initial_state)

        return {
            "past_steps": [(task, query, result["messages"][-1].content)],
            "step_count": step_count,
        }
    else:
        primary_llm, _ = get_default_llms()
        formatted_prompt = task_completion_prompt.format(
            task=task,
            plan=state["plan"],
            past_steps=state["past_steps"],
            company_name=COMPANY_NAME,
            company_context=COMPANY_CONTEXT,
        )
        write_custom_event(
            "refined_agent_answer",
            AgentAnswerPiece(
                answer_piece="  accomplishing the planned task...",
                level=0,
                level_question_num=0,
                answer_type="agent_level_answer",
            ),
            writer,
        )
        response = primary_llm.invoke(formatted_prompt).content
        return {
            "past_steps": [(task, "task: " + task, response)],
            "step_count": step_count,
        }


def plan_step(
    state: PlanExecute, config: RunnableConfig, writer: StreamWriter = lambda _: None
):
    """
    LangGraph node that replans the deep research process.
    """
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.prompt_builder.raw_user_query

    formatted_prompt = planner_prompt.format(
        input=question, company_name=COMPANY_NAME, company_context=COMPANY_CONTEXT
    )
    primary_llm, _ = get_default_llms()
    response = primary_llm.invoke(formatted_prompt).content
    plan = json_to_pydantic(response, Plan)
    write_custom_event(
        "refined_agent_answer",
        AgentAnswerPiece(
            answer_piece="Generating a plan to answer the user's question... ",
            level=0,
            level_question_num=0,
            answer_type="agent_level_answer",
        ),
        writer,
    )
    return {"plan": plan.steps}


def replan_step(
    state: PlanExecute, config: RunnableConfig, writer: StreamWriter = lambda _: None
):
    """
    LangGraph node that determines if the deep research process should end.
    """
    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.prompt_builder.raw_user_query

    formatted_prompt = replanner_prompt.format(
        input=question,
        plan=state["plan"],
        past_steps=state["past_steps"],
        company_name=COMPANY_NAME,
        company_context=COMPANY_CONTEXT,
    )
    primary_llm, _ = get_default_llms()
    response = primary_llm.invoke(formatted_prompt).content
    output = json_to_pydantic(response, Act)
    # TODO: add a check for time limit too
    if isinstance(output.action, Response):
        # Check for canned response, if so, return the answer from the last step
        if output.action.response == "The final answer to the user's question":
            return {
                "response": state["past_steps"][-1][2],
            }
        else:
            return {"response": output.action.response}
    elif state["step_count"] >= state.get("max_steps", 5):
        return {
            "response": f"I've reached the maximum number of step, my best guess is {state['past_steps'][-1][2]}."
        }
    else:
        write_custom_event(
            "refined_agent_answer",
            AgentAnswerPiece(
                answer_piece="    moving on to the next step...",
                level=0,
                level_question_num=0,
                answer_type="agent_level_answer",
            ),
            writer,
        )

        return {"plan": output.action.steps}


def should_end(
    state: PlanExecute, config: RunnableConfig, writer: StreamWriter = lambda _: None
):
    if "response" in state and state["response"]:
        write_custom_event(
            "refined_agent_answer",
            AgentAnswerPiece(
                answer_piece=state["response"],
                level=0,
                level_question_num=0,
                answer_type="agent_level_answer",
            ),
            writer,
        )
        return END
    else:
        return "agent"


def deep_planner_graph_builder(test_mode: bool = False) -> StateGraph:
    """
    LangGraph graph builder for deep planner process.
    """
    workflow = StateGraph(PlanExecute, config_schema=DeepPlannerConfiguration)

    # Add the plan node
    workflow.add_node("planner", plan_step)

    # Add the execution step
    workflow.add_node("agent", execute_step)

    # Add a replan node
    workflow.add_node("replan", replan_step)

    workflow.add_edge(START, "planner")

    # From plan we go to agent
    workflow.add_edge("planner", "agent")

    # From agent, we replan
    workflow.add_edge("agent", "replan")

    workflow.add_conditional_edges(
        "replan",
        should_end,
        ["agent", END],
    )
    return workflow


if __name__ == "__main__":
    # Initialize the SQLAlchemy engine first
    from onyx.db.engine import SqlEngine

    SqlEngine.init_engine(
        pool_size=5,  # You can adjust these values based on your needs
        max_overflow=10,
        app_name="graph_builder",
    )

    # Set the debug and verbose flags for Langchain/Langgraph
    set_debug(IS_DEBUG)
    set_verbose(IS_VERBOSE)

    # Compile the graph
    query_start_time = datetime.now()
    logger.debug(f"Start at {query_start_time}")
    graph = deep_planner_graph_builder()
    compiled_graph = graph.compile(debug=IS_DEBUG)
    query_end_time = datetime.now()
    logger.debug(f"Graph compiled in {query_end_time - query_start_time} seconds")

    queries = [
        "What is the capital of France?",
        "What is Onyx?",
        "Who are the founders of Onyx?",
        "Who is the CEO of Onyx?",
        "Where was the CEO of Onyx born?",
        "What is the highest contract value for last month?",
        "What is the most expensive component of our technical pipeline so far?",
        "Who are top 5 competitors who are not US based?",
        "What companies should we focus on to maximize our revenue?",
        "What are some of the biggest problems for our customers and their potential solutions?",
    ]

    hard_queries = [
        "Where was the CEO of Onyx born?",
        "Who are top 5 competitors who are not US based?",
        "What companies should we focus on to maximize our revenue?",
        "What are some of the biggest problems for our customers and their potential solutions?",
    ]

    for query in hard_queries:
        # Create the initial state with all required fields
        initial_state = {
            "input": [HumanMessage(content=query)],
            "plan": [],
            "past_steps": [],
            "response": "",
            "max_steps": 10,
            "step_count": 0,
        }

        result = compiled_graph.invoke(initial_state)
        print("Max planning loops: ", result["max_steps"])
        print("Steps: ", result["step_count"])
        print("Past steps: ")
        pprint(result["past_steps"], indent=4)
        print("Question: ", query)
        print("Answer: ", result["response"])
        print("--------------------------------")
        # from pdb import set_trace
        # set_trace()
