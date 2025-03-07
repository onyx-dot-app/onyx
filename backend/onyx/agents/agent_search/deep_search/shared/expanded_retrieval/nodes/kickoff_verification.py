from typing import Literal

from langchain_core.runnables.config import RunnableConfig
from langgraph.types import Command
from langgraph.types import Send

from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    DocVerificationInput,
)
from onyx.agents.agent_search.deep_search.shared.expanded_retrieval.states import (
    ExpandedRetrievalState,
)


def kickoff_verification(
    state: ExpandedRetrievalState,
    config: RunnableConfig,
) -> Command[Literal["verify_documents"]]:
    """
    LangGraph node (Command node!) that kicks off the verification process for the retrieved documents.
    Note that this is a Command node and does the routing as well. (At present, no state updates
    are done here, so this could be replaced with an edge. But we may choose to make state
    updates later.)
    """
    retrieved_documents = state.retrieved_documents
    verification_question = state.question

    sub_question_id = state.sub_question_id
    return Command(
        update={},
        goto=[
            Send(
                node="verify_documents",
                arg=DocVerificationInput(
                    retrieved_document_to_verify=document,
                    question=verification_question,
                    base_search=False,
                    sub_question_id=sub_question_id,
                    log_messages=[],
                ),
            )
            for document in retrieved_documents
        ],
    )
