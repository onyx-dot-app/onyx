from collections.abc import Sequence
from datetime import datetime

from danswer.chat.models import LlmDoc
from danswer.configs.chat_configs import MULTILINGUAL_QUERY_EXPANSION
from danswer.configs.constants import DocumentSource
from danswer.db.models import Prompt
from danswer.llm.answering.models import PromptConfig
from danswer.prompts.chat_prompts import CITATION_REMINDER
from danswer.prompts.constants import CODE_BLOCK_PAT
from danswer.prompts.direct_qa_prompts import LANGUAGE_HINT
from danswer.search.models import InferenceChunk


def get_current_llm_day_time() -> str:
    current_datetime = datetime.now()
    # Format looks like: "October 16, 2023 14:30"
    formatted_datetime = current_datetime.strftime("%B %d, %Y %H:%M")
    day_of_week = current_datetime.strftime("%A")
    return f"The current day and time is {day_of_week} {formatted_datetime}"


def build_task_prompt_reminders(
    prompt: Prompt | PromptConfig,
    use_language_hint: bool = bool(MULTILINGUAL_QUERY_EXPANSION),
    citation_str: str = CITATION_REMINDER,
    language_hint_str: str = LANGUAGE_HINT,
) -> str:
    base_task = prompt.task_prompt
    citation_or_nothing = citation_str if prompt.include_citations else ""
    language_hint_or_nothing = language_hint_str.lstrip() if use_language_hint else ""
    return base_task + citation_or_nothing + language_hint_or_nothing


# Maps connector enum string to a more natural language representation for the LLM
# If not on the list, uses the original but slightly cleaned up, see below
CONNECTOR_NAME_MAP = {
    "web": "Website",
    "requesttracker": "Request Tracker",
    "github": "GitHub",
    "file": "File Upload",
}


def clean_up_source(source_str: str) -> str:
    if source_str in CONNECTOR_NAME_MAP:
        return CONNECTOR_NAME_MAP[source_str]
    return source_str.replace("_", " ").title()


def build_doc_context_str(
    semantic_identifier: str,
    source_type: DocumentSource,
    content: str,
    metadata_dict: dict[str, str | list[str]],
    updated_at: datetime | None,
    ind: int,
    include_metadata: bool = True,
) -> str:
    context_str = ""
    if include_metadata:
        context_str += f"DOCUMENT {ind}: {semantic_identifier}\n"
        context_str += f"Source: {clean_up_source(source_type)}\n"

        for k, v in metadata_dict.items():
            if isinstance(v, list):
                v_str = ", ".join(v)
                context_str += f"{k.capitalize()}: {v_str}\n"
            else:
                context_str += f"{k.capitalize()}: {v}\n"

        if updated_at:
            update_str = updated_at.strftime("%B %d, %Y %H:%M")
            context_str += f"Updated: {update_str}\n"
    context_str += f"{CODE_BLOCK_PAT.format(content.strip())}\n\n\n"
    return context_str


def build_complete_context_str(
    context_docs: Sequence[LlmDoc | InferenceChunk],
    include_metadata: bool = True,
) -> str:
    context_str = ""
    for ind, doc in enumerate(context_docs, start=1):
        context_str += build_doc_context_str(
            semantic_identifier=doc.semantic_identifier,
            source_type=doc.source_type,
            content=doc.content,
            metadata_dict=doc.metadata,
            updated_at=doc.updated_at,
            ind=ind,
            include_metadata=include_metadata,
        )

    return context_str.strip()
