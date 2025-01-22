from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    DocVerificationInput,
)
from onyx.agents.agent_search.deep_search_a.expanded_retrieval.states import (
    DocVerificationUpdate,
)
from onyx.agents.agent_search.models import AgentSearchConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.prompts import VERIFIER_PROMPT


def doc_verification(
    state: DocVerificationInput, config: RunnableConfig
) -> DocVerificationUpdate:
    """
    Check whether the document is relevant for the original user question

    Args:
        state (DocVerificationInput): The current state
        config (RunnableConfig): Configuration containing ProSearchConfig

    Updates:
        verified_documents: list[InferenceSection]
    """

    question = state.question
    doc_to_verify = state.doc_to_verify
    document_content = doc_to_verify.combined_content

    agent_a_config = cast(AgentSearchConfig, config["metadata"]["config"])
    fast_llm = agent_a_config.fast_llm

    document_content = trim_prompt_piece(
        fast_llm.config, document_content, VERIFIER_PROMPT + question
    )

    msg = [
        HumanMessage(
            content=VERIFIER_PROMPT.format(
                question=question, document_content=document_content
            )
        )
    ]

    response = fast_llm.invoke(msg)

    verified_documents = []
    if isinstance(response.content, str) and "yes" in response.content.lower():
        verified_documents.append(doc_to_verify)

    return DocVerificationUpdate(
        verified_documents=verified_documents,
    )
