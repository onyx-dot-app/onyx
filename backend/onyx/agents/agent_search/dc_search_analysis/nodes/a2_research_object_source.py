from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dc_search_analysis.ops import extract_section
from onyx.agents.agent_search.dc_search_analysis.ops import research
from onyx.agents.agent_search.dc_search_analysis.states import ObjectSourceInput
from onyx.agents.agent_search.dc_search_analysis.states import (
    ObjectSourceResearchUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.prompts.agents.dc_prompts import DC_OBJECT_SOURCE_RESEARCH_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def research_object_source(
    state: ObjectSourceInput,
    config: RunnableConfig,
    writer: StreamWriter = lambda _: None,
) -> ObjectSourceResearchUpdate:
    """
    LangGraph node to start the agentic search process.
    """
    datetime.now()

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    search_tool = graph_config.tooling.search_tool
    question = graph_config.inputs.prompt_builder.raw_user_query
    object, document_source = state.object_source_combination

    if search_tool is None or graph_config.inputs.persona is None:
        raise ValueError("Search tool and persona must be provided for DivCon search")

    try:
        instructions = graph_config.inputs.persona.system_prompt or ""

        agent_2_instructions = extract_section(
            instructions, "Agent Step 2:", "Agent Step 3:"
        )
        if agent_2_instructions is None:
            raise ValueError("Agent 2 instructions not found")

        agent_2_task = extract_section(
            agent_2_instructions, "Task:", "Independent Research Sources:"
        )
        if agent_2_task is None:
            raise ValueError("Agent 2 task not found")

        agent_2_time_cutoff = extract_section(
            agent_2_instructions, "Time Cutoff:", "Research Topics:"
        )

        agent_2_research_topics = extract_section(
            agent_2_instructions, "Research Topics:", "Output Objective"
        )

        agent_2_output_objective = extract_section(
            agent_2_instructions, "Output Objective:"
        )
        if agent_2_output_objective is None:
            raise ValueError("Agent 2 output objective not found")

    except Exception:
        raise ValueError(
            "Agent 1 instructions not found or not formatted correctly: {e}"
        )

    # Populate prompt

    # Retrieve chunks for objects

    if agent_2_time_cutoff is not None and agent_2_time_cutoff.strip() != "":
        if agent_2_time_cutoff.strip().endswith("d"):
            try:
                days = int(agent_2_time_cutoff.strip()[:-1])
                agent_2_source_start_time = datetime.now(timezone.utc) - timedelta(
                    days=days
                )
            except ValueError:
                raise ValueError(
                    f"Invalid time cutoff format: {agent_2_time_cutoff}. Expected format: '<number>d'"
                )
        else:
            raise ValueError(
                f"Invalid time cutoff format: {agent_2_time_cutoff}. Expected format: '<number>d'"
            )
    else:
        agent_2_source_start_time = None

    document_sources = [document_source] if document_source else None

    if len(question.strip()) > 0:
        research_area = f"{question} for {object}"
    elif agent_2_research_topics and len(agent_2_research_topics.strip()) > 0:
        research_area = f"{agent_2_research_topics} for {object}"
    else:
        research_area = object

    retrieved_docs = research(
        question=research_area,
        search_tool=search_tool,
        document_sources=document_sources,
        time_cutoff=agent_2_source_start_time,
    )

    # Generate document text

    document_texts_list = []
    for doc_num, doc in enumerate(retrieved_docs):
        chunk_text = "Document " + str(doc_num) + ":\n" + doc.content
        document_texts_list.append(chunk_text)

    document_texts = "\n\n".join(document_texts_list)

    # Built prompt

    today = datetime.now().strftime("%A, %Y-%m-%d")

    dc_object_source_research_prompt = (
        DC_OBJECT_SOURCE_RESEARCH_PROMPT.format(
            today=today,
            question=question,
            task=agent_2_task,
            document_text=document_texts,
            format=agent_2_output_objective,
        )
        .replace("---object---", object)
        .replace("---source---", document_source.value)
    )

    # Run LLM

    msg = [
        HumanMessage(
            content=trim_prompt_piece(
                config=graph_config.tooling.primary_llm.config,
                prompt_piece=dc_object_source_research_prompt,
                reserved_str="",
            ),
        )
    ]
    primary_llm = graph_config.tooling.primary_llm
    # Grader
    try:
        llm_response = run_with_timeout(
            30,
            primary_llm.invoke,
            prompt=msg,
            timeout_override=30,
            max_tokens=300,
        )

        cleaned_response = str(llm_response.content).replace("```json\n", "")
        cleaned_response = cleaned_response.split("RESEARCH RESULTS:")[1]
        object_research_results = {
            "object": object,
            "source": document_source.value,
            "research_result": cleaned_response,
        }

    except Exception as e:
        raise ValueError(f"Error in research_object_source: {e}")

    logger.debug("DivCon Step A2 - Object Source Research - completed for an object")

    return ObjectSourceResearchUpdate(
        object_source_research_results=[object_research_results],
        log_messages=["Agent Step 2 done for one object"],
    )
