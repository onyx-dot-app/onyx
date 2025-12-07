import copy
import json
from collections import defaultdict
from datetime import datetime
from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.exploration_2.dr_experimentation_prompts import (
    EXTRACTION_SYSTEM_PROMPT_TEMPLATE,
)
from onyx.agents.agent_search.exploration_2.enums import DRPath
from onyx.agents.agent_search.exploration_2.states import CSUpdate
from onyx.agents.agent_search.exploration_2.states import MainState
from onyx.agents.agent_search.exploration_2.utils import aggregate_context
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_raw
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.utils.logger import setup_logger

logger = setup_logger()


def cs_changes(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> CSUpdate:
    """
    LangGraph node to close the DR process and finalize the answer.
    """

    datetime.now()
    # TODO: generate final answer using all the previous steps
    # (right now, answers from each step are concatenated onto each other)
    # Also, add missing fields once usage in UI is clear.

    current_step_nr = state.current_step_nr
    _EXPLORATION_TEST_USE_DC = state.use_dc

    if _EXPLORATION_TEST_USE_DC:
        base_cheat_sheet_context = (
            copy.deepcopy(state.original_cheat_sheet_context) or {}
        )

        graph_config = cast(GraphConfig, config["metadata"]["config"])
        base_question = state.original_question
        if not base_question:
            raise ValueError("Question is required for closer")

        aggregated_context = aggregate_context(
            state.iteration_responses, include_documents=True
        )

        aggregated_context.cited_documents

        aggregated_context.is_internet_marker_dict

        final_answer = state.final_answer or ""
        llm_provider = graph_config.tooling.primary_llm.config.model_provider
        llm_model_name = graph_config.tooling.primary_llm.config.model_name

        llm_tokenizer = get_tokenizer(
            model_name=llm_model_name,
            provider_type=llm_provider,
        )
        len(llm_tokenizer.encode(final_answer or ""))

        write_custom_event(current_step_nr, OverallStop(), writer)

        # build extraction context

        extracted_facts: list[str] = []
        for iteration_response in state.iteration_responses:
            if iteration_response.tool == DRPath.INTERNAL_SEARCH.value:
                extracted_facts.extend(iteration_response.claims)

        extraction_context = (
            "Extracted facts: \n  - "
            + "\n  - ".join(extracted_facts)
            + f"\n\nProvidede Answer: \n\n{final_answer}"
        )

        extraction_system_prompt_content = EXTRACTION_SYSTEM_PROMPT_TEMPLATE.replace(
            "---original_knowledge---", str(base_cheat_sheet_context)
        )

        extraction_system_prompt = SystemMessage(
            content=extraction_system_prompt_content
        )
        extraction_human_prompt = HumanMessage(content=extraction_context)
        extraction_prompt = [extraction_system_prompt, extraction_human_prompt]

        extraction_response = invoke_llm_raw(
            llm=graph_config.tooling.primary_llm,
            prompt=extraction_prompt,
            # schema=ExtractionResponse,
        )

        extraction_information = json.loads(extraction_response.content)

        consolidated_updates: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict[
            str, dict[str, list[tuple[str, str]]]
        ](
            lambda: defaultdict[str, list[tuple[str, str]]](list)
        )  # type: ignore[assignment]
        for area in ["user", "company", "search_strategy", "reasoning_strategy"]:
            consolidated_updates[area] = defaultdict(list)

        for area in ["user", "company", "search_strategy", "reasoning_strategy"]:
            update_knowledge: list[dict[str, str]] = extraction_information.get(
                area, []
            )
            base_area_knowledge = base_cheat_sheet_context.get(area, {})

            for update_info in update_knowledge:
                update_type = update_info.get("type", "n/a")

            if area not in base_cheat_sheet_context:
                base_cheat_sheet_context[area] = {}

            for update_info in update_knowledge:
                update_type = update_info.get("type", "n/a")
                change_type = update_info.get("change_type", "n/a")
                information = update_info.get("information", "n/a")

                if update_type in base_area_knowledge:
                    if change_type == "update":
                        consolidated_updates[area][update_type].append(
                            (base_area_knowledge.get(update_type, ""), information)
                        )

                    elif change_type == "delete":
                        del base_cheat_sheet_context.get(area, {})[update_type]
                    elif change_type == "add":
                        base_cheat_sheet_context.get(area, {})[
                            update_type
                        ] = information
                else:
                    base_cheat_sheet_context[area][update_type] = information

        return MainState(
            extended_base_knowledge=base_cheat_sheet_context,
            knowledge_update_pairs=consolidated_updates,
        )

    else:
        return MainState(
            extended_base_knowledge={},
            knowledge_update_pairs={},
        )
