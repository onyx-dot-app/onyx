from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dc_search_analysis.ops import extract_section
from onyx.agents.agent_search.dc_search_analysis.ops import research
from onyx.agents.agent_search.dc_search_analysis.states import MainState
from onyx.agents.agent_search.dc_search_analysis.states import (
    SearchSourcesObjectsUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.configs.constants import DocumentSource
from onyx.prompts.agents.dc_prompts import DC_OBJECT_NO_BASE_DATA_EXTRACTION_PROMPT
from onyx.prompts.agents.dc_prompts import DC_OBJECT_SEPARATOR
from onyx.prompts.agents.dc_prompts import DC_OBJECT_WITH_BASE_DATA_EXTRACTION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout

logger = setup_logger()


def search_objects(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> SearchSourcesObjectsUpdate:
    """
    LangGraph node to start the agentic search process.
    """

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    question = graph_config.inputs.prompt_builder.raw_user_query
    search_tool = graph_config.tooling.search_tool

    if search_tool is None or graph_config.inputs.persona is None:
        raise ValueError("Search tool and persona must be provided for DivCon search")

    try:
        instructions = graph_config.inputs.persona.system_prompt or ""

        agent_1_instructions = extract_section(
            instructions, "Agent Step 1:", "Agent Step 2:"
        )
        if agent_1_instructions is None:
            raise ValueError("Agent 1 instructions not found")

        agent_1_base_data = extract_section(instructions, "|Start Data|", "|End Data|")

        agent_1_task = extract_section(
            agent_1_instructions, "Task:", "Independent Research Sources:"
        )
        if agent_1_task is None:
            raise ValueError("Agent 1 task not found")

        agent_1_independent_sources_str = extract_section(
            agent_1_instructions, "Independent Research Sources:", "Output Objective:"
        )
        if agent_1_independent_sources_str is None:
            raise ValueError("Agent 1 Independent Research Sources not found")

        document_sources = [
            DocumentSource(x.strip().lower())
            for x in agent_1_independent_sources_str.split(DC_OBJECT_SEPARATOR)
        ]

        agent_1_output_objective = extract_section(
            agent_1_instructions, "Output Objective:"
        )
        if agent_1_output_objective is None:
            raise ValueError("Agent 1 output objective not found")

    except Exception as e:
        raise ValueError(
            f"Agent 1 instructions not found or not formatted correctly: {e}"
        )

    # Extract objects

    if agent_1_base_data is None:
        # Retrieve chunks for objects

        retrieved_docs = research(question, search_tool)[:10]

        document_texts_list = []
        for doc_num, doc in enumerate(retrieved_docs):
            chunk_text = "Document " + str(doc_num) + ":\n" + doc.content
            document_texts_list.append(chunk_text)

        document_texts = "\n\n".join(document_texts_list)

        dc_object_extraction_prompt = DC_OBJECT_NO_BASE_DATA_EXTRACTION_PROMPT.format(
            question=question,
            task=agent_1_task,
            document_text=document_texts,
            objects_of_interest=agent_1_output_objective,
        )
    else:
        dc_object_extraction_prompt = DC_OBJECT_WITH_BASE_DATA_EXTRACTION_PROMPT.format(
            question=question,
            task=agent_1_task,
            base_data=agent_1_base_data,
            objects_of_interest=agent_1_output_objective,
        )

    msg = [
        HumanMessage(
            content=trim_prompt_piece(
                config=graph_config.tooling.primary_llm.config,
                prompt_piece=dc_object_extraction_prompt,
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

        cleaned_response = (
            str(llm_response.content)
            .replace("```json\n", "")
            .replace("\n```", "")
            .replace("\n", "")
        )
        cleaned_response = cleaned_response.split("OBJECTS:")[1]
        object_list = [x.strip() for x in cleaned_response.split(";")]

    except Exception as e:
        raise ValueError(f"Error in search_objects: {e}")

    return SearchSourcesObjectsUpdate(
        analysis_objects=object_list,
        analysis_sources=document_sources,
        log_messages=["Agent 1 Task done"],
    )
