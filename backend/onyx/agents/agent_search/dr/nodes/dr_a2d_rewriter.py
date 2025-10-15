import re
from datetime import datetime
from typing import cast
from typing import List

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


def _find_citation_numbers_with_positions(text: str) -> List[int]:
    """
    Find all citation numbers with their positions in the text.

    Args:
        text: The input text to search for citations

    Returns:
        List of citation_numbers
    """
    pattern = r"\[\[(\d+)\]\]"

    results = []
    for match in re.finditer(pattern, text):
        citation_number = int(match.group(1))
        results.append(citation_number)

    return results


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

    final_answer = state.final_answer

    all_cited_documents = state.all_cited_documents

    claims: list[str] = []

    claims = []
    claim_dict = {}
    claim_supporting_cites = []
    for iteration_response_nr, iteration_response in enumerate(
        state.global_iteration_responses
    ):
        for iteration_claim_nr, iteration_claim in enumerate(
            iteration_response.claims or []
        ):
            claims.append(
                f"Claim Nr: {iteration_response_nr}-{iteration_claim_nr}\nClaim:\n{iteration_claim}"
            )
            claim_dict[f"{iteration_response_nr}-{iteration_claim_nr}"] = (
                iteration_claim
            )
            claim_supporting_cites.extend(
                _find_citation_numbers_with_positions(iteration_claim)
            )
    claim_str = "\n\n".join(claims)
    claim_supporting_cites = list(set(claim_supporting_cites))

    # get cite links
    # for cite in all_cited_documents:
    #    if cite.type == "file":

    claim_tension_prompt = CLAIM_CONTRADICTION_PROMPT.build(
        claim_str=claim_str,
    )

    claim_tension_response = invoke_llm_json(
        llm=graph_config.tooling.primary_llm,
        prompt=claim_tension_prompt,
        schema=ClaimTensionResponse,
    )

    contradictions = claim_tension_response.contradictions
    clarification_needs = claim_tension_response.clarification_needs

    web_sources = []
    internal_sources = []
    for cite_nr in claim_supporting_cites:
        cite = all_cited_documents[cite_nr - 1]
        if cite.type == "web":
            web_sources.append(cite.center_chunk.source_links[0])
        else:
            internal_sources.append(cite.center_chunk.source_links[0])

    # resolve:

    print(contradictions[0].description)
    print(clarification_needs[0].description)

    claim_supporting_cites = []
    for contradiction in contradictions:
        for claim_number in contradiction.claim_numbers:
            claim_dict[claim_number]
            claim_supporting_cites.append(claim_dict[claim_number])
    for clarification_need in clarification_needs:
        for claim_number in clarification_need.claim_numbers:
            claim_supporting_cites.append(claim_dict[claim_number])

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
