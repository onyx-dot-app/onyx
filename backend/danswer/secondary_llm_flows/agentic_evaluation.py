import re

from danswer.chat.models import RelevanceChunk
from danswer.llm.interfaces import LLM
from danswer.llm.utils import dict_based_prompt_to_langchain_prompt
from danswer.llm.utils import message_to_string
from danswer.prompts.agentic_evaluation import AGENTIC_SEARCH_SYSTEM_PROMPT
from danswer.prompts.agentic_evaluation import AGENTIC_SEARCH_USER_PROMPT
from danswer.search.models import InferenceSection
from danswer.utils.logger import setup_logger

logger = setup_logger()


def _get_agent_eval_messages(
    title: str, content: str, query: str
) -> list[dict[str, str]]:
    messages = [
        {
            "role": "system",
            "content": AGENTIC_SEARCH_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": AGENTIC_SEARCH_USER_PROMPT.format(
                title=title, content=content, query=query
            ),
        },
    ]
    return messages


def evaluate_inference_section(
    document: InferenceSection, query: str, llm: LLM
) -> dict[str, RelevanceChunk]:
    results = {}

    document_id = document.center_chunk.document_id
    semantic_id = document.center_chunk.semantic_identifier
    contents = document.combined_content
    chunk_id = document.center_chunk.chunk_id

    messages = _get_agent_eval_messages(
        title=semantic_id, content=contents, query=query
    )
    filled_llm_prompt = dict_based_prompt_to_langchain_prompt(messages)
    model_output = message_to_string(llm.invoke(filled_llm_prompt))

    # Search for the "Useful Analysis" section in the model output
    # This regex looks for "2. Useful Analysis" (case-insensitive) followed by an optional colon,
    # then any text up to "3. Final Relevance"
    # The (?i) flag makes it case-insensitive, and re.DOTALL allows the dot to match newlines
    # If no match is found, the entire model output is used as the analysis
    analysis_match = re.search(
        r"(?i)2\.\s*useful analysis:?\s*(.+?)\n\n3\.\s*final relevance",
        model_output,
        re.DOTALL,
    )
    analysis = analysis_match.group(1).strip() if analysis_match else model_output

    # Get the last non-empty line
    last_line = next(
        (line for line in reversed(model_output.split("\n")) if line.strip()), ""
    )
    relevant = last_line.strip().lower().startswith("true")

    results[f"{document_id}-{chunk_id}"] = RelevanceChunk(
        relevant=relevant, content=analysis
    )
    return results
