from typing import cast

from langchain_core.messages import HumanMessage
from langchain_core.runnables.config import RunnableConfig

from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    DocVerificationInput,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    DocVerificationUpdate,
)
from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.prompts.agent_search import (
    DOCUMENT_VERIFICATION_PROMPT,
)


def verify_documents(
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
    retrieved_document_to_verify = state.retrieved_document_to_verify
    document_content = retrieved_document_to_verify.combined_content

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    fast_llm = graph_config.tooling.fast_llm

    document_content = trim_prompt_piece(
        fast_llm.config, document_content, DOCUMENT_VERIFICATION_PROMPT + question
    )

    msg = [
        HumanMessage(
            content=DOCUMENT_VERIFICATION_PROMPT.format(
                question=question, document_content=document_content
            )
        )
    ]

    response = fast_llm.invoke(msg)

    verified_documents = []
    if isinstance(response.content, str) and "yes" in response.content.lower():
        verified_documents.append(retrieved_document_to_verify)

    return DocVerificationUpdate(
        verified_documents=verified_documents,
    )
