from datetime import datetime
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.types import StreamWriter

from onyx.agents.agent_search.dr.models import ClaimTensionResponse
from onyx.agents.agent_search.dr.states import FinalUpdate
from onyx.agents.agent_search.dr.states import MainState
from onyx.agents.agent_search.dr.states import OrchestrationUpdate
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.llm import invoke_llm_json
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.prompts.dr_prompts import CLAIM_CONTRADICTION_PROMPT
from onyx.utils.logger import setup_logger


logger = setup_logger()

_SOURCE_MATERIAL_PROMPT = "Can yut please put together all of the supporting material?"


def rewriter(
    state: MainState, config: RunnableConfig, writer: StreamWriter = lambda _: None
) -> FinalUpdate | OrchestrationUpdate:
    """
    LangGraph node to close the DR process and finalize the answer.
    """

    node_start_time = datetime.now()
    # TODO: generate final answer using all the previous steps
    # (right now, answers from each step are concatenated onto each other)
    # Also, add missing fields once usage in UI is clear.

    state.current_step_nr

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    base_question = state.original_question
    if not base_question:
        raise ValueError("Question is required for closer")

    graph_config.behavior.research_type

    state.assistant_system_prompt
    state.assistant_task_prompt

    final_answer = state.final_answer

    all_cited_documents = state.all_cited_documents

    state.iteration_responses

    claims: list[str] = []

    claims = []
    for iteration_response_nr, iteration_response in enumerate(
        state.iteration_responses
    ):
        for iteration_claim_nr, iteration_claim in enumerate(
            iteration_response.claims or []
        ):
            claims.append(
                f"Claim Nr: {iteration_response_nr}-{iteration_claim_nr}\nClaim:\n{iteration_claim}"
            )
    claim_str = "\n\n".join(claims)

    print(claim_str)

    claim_tension_prompt = CLAIM_CONTRADICTION_PROMPT.build(
        claim_str=claim_str,
    )

    claim_tension_response = invoke_llm_json(
        llm=graph_config.tooling.primary_llm,
        prompt=claim_tension_prompt,
        max_tokens=graph_config.tooling.primary_llm.config.max_input_tokens,
        schema=ClaimTensionResponse,
    )

    contradictions = claim_tension_response.contradictions
    clarification_needs = claim_tension_response.clarification_needs

    print(contradictions[0].description)
    print(clarification_needs[0].description)

    return FinalUpdate(
        final_answer=final_answer,
        all_cited_documents=all_cited_documents,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="main",
                node_name="closer",
                node_start_time=node_start_time,
            )
        ],
    )
