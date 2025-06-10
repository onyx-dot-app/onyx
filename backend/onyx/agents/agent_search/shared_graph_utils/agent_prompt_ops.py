from langchain.schema import AIMessage
from langchain.schema import HumanMessage
from langchain.schema import SystemMessage
from langchain_core.messages.tool import ToolMessage

from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.models import (
    AgentPromptEnrichmentComponents,
)
from onyx.agents.agent_search.shared_graph_utils.utils import format_docs
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_persona_agent_prompt_expressions,
)
from onyx.agents.agent_search.shared_graph_utils.utils import remove_document_citations
from onyx.agents.agent_search.shared_graph_utils.utils import summarize_history
from onyx.configs.agent_configs import AGENT_MAX_STATIC_HISTORY_WORD_LENGTH
from onyx.configs.constants import MessageType
from onyx.context.search.models import InferenceSection
from onyx.llm.interfaces import LLMConfig
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.natural_language_processing.utils import tokenizer_trim_content
from onyx.prompts.agent_search import HISTORY_FRAMING_PROMPT
from onyx.prompts.agent_search import SUB_QUESTION_RAG_PROMPT
from onyx.prompts.prompt_utils import build_date_time_string
from onyx.utils.logger import setup_logger

logger = setup_logger()


def build_sub_question_answer_prompt(
    question: str,
    original_question: str,
    docs: list[InferenceSection],
    persona_specification: str,
    config: LLMConfig,
) -> list[SystemMessage | HumanMessage | AIMessage | ToolMessage]:
    system_message = SystemMessage(
        content=persona_specification,
    )

    date_str = build_date_time_string()

    docs_str = format_docs(docs)

    docs_str = trim_prompt_piece(
        config=config,
        prompt_piece=docs_str,
        reserved_str=SUB_QUESTION_RAG_PROMPT + question + original_question + date_str,
    )
    human_message = HumanMessage(
        content=SUB_QUESTION_RAG_PROMPT.format(
            question=question,
            original_question=original_question,
            context=docs_str,
            date_prompt=date_str,
        )
    )

    return [system_message, human_message]


def trim_prompt_piece(config: LLMConfig, prompt_piece: str, reserved_str: str) -> str:
    # no need to trim if a conservative estimate of one token
    # per character is already less than the max tokens
    if len(prompt_piece) + len(reserved_str) < config.max_input_tokens:
        return prompt_piece

    llm_tokenizer = get_tokenizer(
        provider_type=config.model_provider,
        model_name=config.model_name,
    )

    # slightly conservative trimming
    return tokenizer_trim_content(
        content=prompt_piece,
        desired_length=config.max_input_tokens
        - len(llm_tokenizer.encode(reserved_str)),
        tokenizer=llm_tokenizer,
    )


def build_history_prompt(config: GraphConfig, question: str) -> str:
    prompt_builder = config.inputs.prompt_builder
    persona_base = get_persona_agent_prompt_expressions(
        config.inputs.persona
    ).base_prompt

    if prompt_builder is None:
        return ""

    if prompt_builder.single_message_history is not None:
        history = prompt_builder.single_message_history
    else:
        history_components = []
        previous_message_type = None
        for message in prompt_builder.raw_message_history:
            if message.message_type == MessageType.USER:
                history_components.append(f"User: {message.message}\n")
                previous_message_type = MessageType.USER
            elif message.message_type == MessageType.ASSISTANT:
                # Previously there could be multiple assistant messages in a row
                # Now this is handled at the message history construction
                assert previous_message_type is not MessageType.ASSISTANT
                history_components.append(f"You/Agent: {message.message}\n")
                previous_message_type = MessageType.ASSISTANT
            else:
                # Other message types are not included here, currently there should be no other message types
                logger.error(
                    f"Unhandled message type: {message.message_type} with message: {message.message}"
                )
                continue

        history = "\n".join(history_components)
        history = remove_document_citations(history)
        if len(history.split()) > AGENT_MAX_STATIC_HISTORY_WORD_LENGTH:
            history = summarize_history(
                history=history,
                question=question,
                persona_specification=persona_base,
                llm=config.tooling.fast_llm,
            )

    return HISTORY_FRAMING_PROMPT.format(history=history) if history else ""


def get_prompt_enrichment_components(
    config: GraphConfig,
) -> AgentPromptEnrichmentComponents:
    persona_prompts = get_persona_agent_prompt_expressions(config.inputs.persona)

    history = build_history_prompt(config, config.inputs.prompt_builder.raw_user_query)

    date_str = build_date_time_string()

    return AgentPromptEnrichmentComponents(
        persona_prompts=persona_prompts,
        history=history,
        date_str=date_str,
    )


def binary_string_test(text: str, positive_value: str = "yes") -> bool:
    """
    Tests if a string contains a positive value (case-insensitive).

    Args:
        text: The string to test
        positive_value: The value to look for (defaults to "yes")

    Returns:
        True if the positive value is found in the text
    """
    return positive_value.lower() in text.lower()


def binary_string_test_after_answer_separator(
    text: str, positive_value: str = "yes", separator: str = "Answer:"
) -> bool:
    """
    Tests if a string contains a positive value (case-insensitive).

    Args:
        text: The string to test
        positive_value: The value to look for (defaults to "yes")

    Returns:
        True if the positive value is found in the text
    """

    if separator not in text:
        return False
    relevant_text = text.split(f"{separator}")[-1]

    return binary_string_test(relevant_text, positive_value)
