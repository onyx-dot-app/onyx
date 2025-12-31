from datetime import datetime
from typing import cast

from langchain_core.messages import BaseMessage

from onyx.configs.constants import DocumentSource
from onyx.prompts.chat_prompts import ADDITIONAL_INFO
from onyx.prompts.chat_prompts import ALT_CITATION_GUIDANCE_REPLACEMENT_PAT
from onyx.prompts.chat_prompts import ALT_DATETIME_REPLACEMENT_PAT
from onyx.prompts.chat_prompts import CITATION_GUIDANCE_REPLACEMENT_PAT
from onyx.prompts.chat_prompts import COMPANY_DESCRIPTION_BLOCK
from onyx.prompts.chat_prompts import COMPANY_NAME_BLOCK
from onyx.prompts.chat_prompts import DATETIME_REPLACEMENT_PAT
from onyx.prompts.chat_prompts import REQUIRE_CITATION_GUIDANCE
from onyx.prompts.constants import CODE_BLOCK_PAT
from onyx.server.settings.store import load_settings
from onyx.utils.logger import setup_logger


logger = setup_logger()


_BASIC_TIME_STR = "The current date is {datetime_info}."


def get_current_llm_day_time(
    include_day_of_week: bool = True,
    full_sentence: bool = True,
    include_hour_min: bool = False,
) -> str:
    current_datetime = datetime.now()
    # Format looks like: "October 16, 2023 14:30" if include_hour_min, otherwise "October 16, 2023"
    formatted_datetime = (
        current_datetime.strftime("%B %d, %Y %H:%M")
        if include_hour_min
        else current_datetime.strftime("%B %d, %Y")
    )
    day_of_week = current_datetime.strftime("%A")
    if full_sentence:
        return f"The current day and time is {day_of_week} {formatted_datetime}"
    if include_day_of_week:
        return f"{day_of_week} {formatted_datetime}"
    return f"{formatted_datetime}"


def replace_current_datetime_tag(
    prompt_str: str,
    *,
    full_sentence: bool = False,
    include_day_of_week: bool = True,
) -> str:
    datetime_str = get_current_llm_day_time(
        full_sentence=full_sentence,
        include_day_of_week=include_day_of_week,
    )

    # Check and replace both patterns: {{CURRENT_DATETIME}} and [[CURRENT_DATETIME]]
    if DATETIME_REPLACEMENT_PAT in prompt_str:
        prompt_str = prompt_str.replace(DATETIME_REPLACEMENT_PAT, datetime_str)
    if ALT_DATETIME_REPLACEMENT_PAT in prompt_str:
        prompt_str = prompt_str.replace(ALT_DATETIME_REPLACEMENT_PAT, datetime_str)

    return prompt_str


def replace_citation_guidance_tag(
    prompt_str: str,
    *,
    should_cite_documents: bool = False,
    include_all_guidance: bool = False,
) -> tuple[str, bool]:
    """
    Replace {{CITATION_GUIDANCE}} or [[CITATION_GUIDANCE]] placeholder with citation guidance if needed.

    Returns:
        tuple[str, bool]: (prompt_with_replacement, should_append_fallback)
        - prompt_with_replacement: The prompt with placeholder replaced (or unchanged if not present)
        - should_append_fallback: True if citation guidance should be appended
            (placeholder is not present and citations are needed)
    """
    # Check for both patterns: {{CITATION_GUIDANCE}} and [[CITATION_GUIDANCE]]
    has_primary_pattern = CITATION_GUIDANCE_REPLACEMENT_PAT in prompt_str
    has_alt_pattern = ALT_CITATION_GUIDANCE_REPLACEMENT_PAT in prompt_str
    placeholder_was_present = has_primary_pattern or has_alt_pattern

    if not placeholder_was_present:
        # Placeholder not present - caller should append if citations are needed
        should_append = (
            should_cite_documents or include_all_guidance
        ) and REQUIRE_CITATION_GUIDANCE not in prompt_str
        return prompt_str, should_append

    citation_guidance = (
        REQUIRE_CITATION_GUIDANCE
        if should_cite_documents or include_all_guidance
        else ""
    )

    # Replace both patterns if present
    if has_primary_pattern:
        prompt_str = prompt_str.replace(
            CITATION_GUIDANCE_REPLACEMENT_PAT,
            citation_guidance,
        )
    if has_alt_pattern:
        prompt_str = prompt_str.replace(
            ALT_CITATION_GUIDANCE_REPLACEMENT_PAT,
            citation_guidance,
        )

    return prompt_str, False


def handle_onyx_date_awareness(
    prompt_str: str,
    # We always replace the pattern {{CURRENT_DATETIME}} or [[CURRENT_DATETIME]] if it shows up
    # but if it doesn't show up and the prompt is datetime aware, add it to the prompt at the end.
    datetime_aware: bool = False,
) -> str:
    """
    If there is a {{CURRENT_DATETIME}} or [[CURRENT_DATETIME]] tag, replace it with the current
    date and time no matter what.
    If the prompt is datetime aware, and there are no datetime tags, add it to the prompt.
    Do nothing otherwise.
    This can later be expanded to support other tags.
    """

    prompt_with_datetime = replace_current_datetime_tag(
        prompt_str,
        full_sentence=False,
        include_day_of_week=True,
    )
    if prompt_with_datetime != prompt_str:
        return prompt_with_datetime

    if datetime_aware:
        return prompt_str + ADDITIONAL_INFO.format(
            datetime_info=_BASIC_TIME_STR.format(
                datetime_info=get_current_llm_day_time()
            )
        )

    return prompt_str


def get_company_context() -> str | None:
    prompt_str = None
    try:
        workspace_settings = load_settings()
        company_name = workspace_settings.company_name
        company_description = workspace_settings.company_description

        if not company_name and not company_description:
            return None

        prompt_str = ""
        if company_name:
            prompt_str += COMPANY_NAME_BLOCK.format(company_name=company_name)
        if company_description:
            prompt_str += COMPANY_DESCRIPTION_BLOCK.format(
                company_description=company_description
            )
        return prompt_str
    except Exception as e:
        logger.error(f"Error handling company awareness: {e}")
        return None


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


_PER_MESSAGE_TOKEN_BUFFER = 7


def find_last_index(lst: list[int], max_prompt_tokens: int) -> int:
    """From the back, find the index of the last element to include
    before the list exceeds the maximum"""
    running_sum = 0

    if not lst:
        logger.warning("Empty message history passed to find_last_index")
        return 0

    last_ind = 0
    for i in range(len(lst) - 1, -1, -1):
        running_sum += lst[i] + _PER_MESSAGE_TOKEN_BUFFER
        if running_sum > max_prompt_tokens:
            last_ind = i + 1
            break

    if last_ind >= len(lst):
        logger.error(
            f"Last message alone is too large! max_prompt_tokens: {max_prompt_tokens}, message_token_counts: {lst}"
        )
        raise ValueError("Last message alone is too large!")

    return last_ind


def drop_messages_history_overflow(
    messages_with_token_cnts: list[tuple[BaseMessage, int]],
    max_allowed_tokens: int,
) -> list[BaseMessage]:
    """As message history grows, messages need to be dropped starting from the furthest in the past.
    The System message should be kept if at all possible and the latest user input which is inserted in the
    prompt template must be included"""

    final_messages: list[BaseMessage] = []
    messages, token_counts = cast(
        tuple[list[BaseMessage], list[int]], zip(*messages_with_token_cnts)
    )
    system_msg = (
        final_messages[0]
        if final_messages and final_messages[0].type == "system"
        else None
    )

    history_msgs = messages[:-1]
    final_msg = messages[-1]
    if final_msg.type != "human":
        if final_msg.type != "tool":
            raise ValueError("Last message must be user input OR a tool result")
        else:
            final_msgs = messages[-3:]
            history_msgs = messages[:-3]
    else:
        final_msgs = [final_msg]

    # Start dropping from the history if necessary
    ind_prev_msg_start = find_last_index(
        token_counts, max_prompt_tokens=max_allowed_tokens
    )

    if system_msg and ind_prev_msg_start <= len(history_msgs):
        final_messages.append(system_msg)

    final_messages.extend(history_msgs[ind_prev_msg_start:])
    final_messages.extend(final_msgs)

    return final_messages
