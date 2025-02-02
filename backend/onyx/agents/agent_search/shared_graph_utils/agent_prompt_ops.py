from langchain.schema import AIMessage
from langchain.schema import HumanMessage
from langchain.schema import SystemMessage
from langchain_core.messages.tool import ToolMessage

from onyx.agents.agent_search.models import GraphConfig
from onyx.agents.agent_search.shared_graph_utils.models import (
    AgentPromptEnrichmentComponents,
)
from onyx.agents.agent_search.shared_graph_utils.utils import (
    get_persona_agent_prompt_expressions,
)
from onyx.agents.agent_search.shared_graph_utils.utils import remove_document_citations
from onyx.agents.agent_search.shared_graph_utils.utils import summarize_history
from onyx.configs.agent_configs import AGENT_MAX_STATIC_HISTORY_WORD_LENGTH
from onyx.context.search.models import InferenceSection
from onyx.llm.interfaces import LLMConfig
from onyx.llm.utils import get_max_input_tokens
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.natural_language_processing.utils import tokenizer_trim_content
from onyx.prompts.agent_search import HISTORY_FRAMING_PROMPT
from onyx.prompts.agent_search import SUB_QUESTION_RAG_PROMPT
from onyx.prompts.prompt_utils import build_date_time_string


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

    docs_format_list = [
        f"""Document Number: [D{doc_num + 1}]\n
                             Content: {doc.combined_content}\n\n"""
        for doc_num, doc in enumerate(docs)
    ]

    docs_str = "\n\n".join(docs_format_list)

    docs_str = trim_prompt_piece(
        config,
        docs_str,
        SUB_QUESTION_RAG_PROMPT + question + original_question + date_str,
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
    # TODO: save the max input tokens in LLMConfig
    max_tokens = get_max_input_tokens(
        model_provider=config.model_provider,
        model_name=config.model_name,
    )

    # no need to trim if a conservative estimate of one token
    # per character is already less than the max tokens
    if len(prompt_piece) + len(reserved_str) < max_tokens:
        return prompt_piece

    llm_tokenizer = get_tokenizer(
        provider_type=config.model_provider,
        model_name=config.model_name,
    )

    # slightly conservative trimming
    return tokenizer_trim_content(
        content=prompt_piece,
        desired_length=max_tokens - len(llm_tokenizer.encode(reserved_str)),
        tokenizer=llm_tokenizer,
    )


def build_history_prompt(config: GraphConfig, question: str) -> str:
    prompt_builder = config.inputs.prompt_builder
    model = config.tooling.fast_llm
    persona_base = get_persona_agent_prompt_expressions(
        config.inputs.search_request.persona
    ).base_prompt

    if prompt_builder is None:
        return ""

    if prompt_builder.single_message_history is not None:
        history = prompt_builder.single_message_history
    else:
        history_components = []
        previous_message_type = None
        for message in prompt_builder.raw_message_history:
            if "user" in message.message_type:
                history_components.append(f"User: {message.message}\n")
                previous_message_type = "user"
            elif "assistant" in message.message_type:
                # only use the last agent answer for the history
                if previous_message_type != "assistant":
                    history_components.append(f"You/Agent: {message.message}\n")
                else:
                    history_components = history_components[:-1]
                    history_components.append(f"You/Agent: {message.message}\n")
                previous_message_type = "assistant"
            else:
                continue
        history = "\n".join(history_components)
        history = remove_document_citations(history)
        if len(history.split()) > AGENT_MAX_STATIC_HISTORY_WORD_LENGTH:
            history = summarize_history(history, question, persona_base, model)

    return HISTORY_FRAMING_PROMPT.format(history=history) if history else ""


def get_prompt_enrichment_components(
    config: GraphConfig,
) -> AgentPromptEnrichmentComponents:
    persona_prompts = get_persona_agent_prompt_expressions(
        config.inputs.search_request.persona
    )

    history = build_history_prompt(config, config.inputs.search_request.query)

    date_str = build_date_time_string()

    return AgentPromptEnrichmentComponents(
        persona_prompts=persona_prompts,
        history=history,
        date_str=date_str,
    )
