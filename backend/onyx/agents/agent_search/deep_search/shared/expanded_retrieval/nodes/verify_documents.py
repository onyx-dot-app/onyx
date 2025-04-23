from datetime import datetime
from typing import cast

from langchain_core.messages import BaseMessage
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
    binary_string_test,
)
from onyx.agents.agent_search.shared_graph_utils.agent_prompt_ops import (
    trim_prompt_piece,
)
from onyx.agents.agent_search.shared_graph_utils.constants import (
    AGENT_POSITIVE_VALUE_STR,
)
from onyx.agents.agent_search.shared_graph_utils.models import LLMNodeErrorStrings
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_langgraph_node_log_string,
)
from onyx.configs.agent_configs import AGENT_MAX_TOKENS_VALIDATION
from onyx.configs.agent_configs import AGENT_TIMEOUT_CONNECT_LLM_DOCUMENT_VERIFICATION
from onyx.configs.agent_configs import AGENT_TIMEOUT_LLM_DOCUMENT_VERIFICATION
from onyx.llm.chat_llm import LLMRateLimitError
from onyx.llm.chat_llm import LLMTimeoutError
from onyx.prompts.agent_search import (
    DOCUMENT_VERIFICATION_PROMPT,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_with_timeout
from onyx.utils.timing import log_function_time

logger = setup_logger()

_llm_node_error_strings = LLMNodeErrorStrings(
    timeout="The LLM timed out. The document could not be verified. The document will be treated as 'relevant'",
    rate_limit="The LLM encountered a rate limit. The document could not be verified. The document will be treated as 'relevant'",
    general_error="The LLM encountered an error. The document could not be verified. The document will be treated as 'relevant'",
)


@log_function_time(print_only=True)
def verify_documents(
    state: DocVerificationInput, config: RunnableConfig
) -> DocVerificationUpdate:
    """
    LangGraph node to check whether the document is relevant for the original user question

    Args:
        state (DocVerificationInput): The current state
        config (RunnableConfig): Configuration containing AgentSearchConfig

    Updates:
        verified_documents: list[InferenceSection]
    """

    node_start_time = datetime.now()

    question = state.question
    retrieved_document_to_verify = state.retrieved_document_to_verify
    document_content = retrieved_document_to_verify.combined_content

    graph_config = cast(GraphConfig, config["metadata"]["config"])
    fast_llm = graph_config.tooling.fast_llm

    document_content = trim_prompt_piece(
        config=fast_llm.config,
        prompt_piece=document_content,
        reserved_str=DOCUMENT_VERIFICATION_PROMPT + question,
    )

    msg = [
        HumanMessage(
            content=DOCUMENT_VERIFICATION_PROMPT.format(
                question=question, document_content=document_content
            )
        )
    ]

    response: BaseMessage | None = None

    verified_documents = [
        retrieved_document_to_verify
    ]  # default is to treat document as relevant

    try:
        response = run_with_timeout(
            AGENT_TIMEOUT_LLM_DOCUMENT_VERIFICATION,
            fast_llm.invoke,
            prompt=msg,
            timeout_override=AGENT_TIMEOUT_CONNECT_LLM_DOCUMENT_VERIFICATION,
            max_tokens=AGENT_MAX_TOKENS_VALIDATION,
        )

        assert isinstance(response.content, str)
        if not binary_string_test(
            text=response.content, positive_value=AGENT_POSITIVE_VALUE_STR
        ):
            verified_documents = []

    except (LLMTimeoutError, TimeoutError):
        # In this case, we decide to continue and don't raise an error, as
        # little harm in letting some docs through that are less relevant.
        logger.error("LLM Timeout Error - verify documents")

    except LLMRateLimitError:
        # In this case, we decide to continue and don't raise an error, as
        # little harm in letting some docs through that are less relevant.
        logger.error("LLM Rate Limit Error - verify documents")

    return DocVerificationUpdate(
        verified_documents=verified_documents,
        log_messages=[
            get_langgraph_node_log_string(
                graph_component="shared - expanded retrieval",
                node_name="verify documents",
                node_start_time=node_start_time,
            )
        ],
    )
