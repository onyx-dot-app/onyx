import re

from onyx.context.search.models import ContextExpansionType
from onyx.llm.interfaces import LLM
from onyx.llm.message_types import UserMessage
from onyx.prompts.search_prompts import DOCUMENT_CONTEXT_SELECTION_PROMPT
from onyx.utils.logger import setup_logger

logger = setup_logger()


def classify_section_relevance(
    section_text: str,
    user_query: str,
    llm: LLM,
    section_above_text: str | None,
    section_below_text: str | None,
) -> ContextExpansionType:
    """Use LLM to classify section relevance and determine context expansion type.

    Args:
        section_text: The text content of the section to classify
        user_query: The user's search query
        llm: LLM instance to use for classification
        section_above_text: Text content from chunks above the section
        section_below_text: Text content from chunks below the section

    Returns:
        ContextExpansionType indicating how the section should be expanded
    """
    # Build the prompt
    prompt_text = DOCUMENT_CONTEXT_SELECTION_PROMPT.format(
        main_section=section_text,
        section_above=section_above_text if section_above_text else "N/A",
        section_below=section_below_text if section_below_text else "N/A",
        user_query=user_query,
    )

    user_msg: UserMessage = {
        "role": "user",
        "content": prompt_text,
    }

    messages = [user_msg]

    # Default to MAIN_SECTION_ONLY
    default_classification = ContextExpansionType.MAIN_SECTION_ONLY

    # Call LLM for classification
    try:
        response = llm.invoke(prompt=messages)
        llm_response = response.choice.message.content

        if not llm_response:
            logger.warning(
                "LLM returned empty response for context selection, defaulting to MAIN_SECTION_ONLY"
            )
            classification = default_classification
        else:
            # Parse the response to extract the situation number (1-4)
            numbers = re.findall(r"\b[1-4]\b", llm_response)
            if numbers:
                situation = int(numbers[-1])
                # Map situation number to ContextExpansionType
                situation_to_type = {
                    1: ContextExpansionType.NOT_RELEVANT,
                    2: ContextExpansionType.MAIN_SECTION_ONLY,
                    3: ContextExpansionType.INCLUDE_ADJACENT_SECTIONS,
                    4: ContextExpansionType.FULL_DOCUMENT,
                }
                classification = situation_to_type.get(
                    situation, default_classification
                )
                logger.debug(
                    f"LLM classified section as {classification.value} (situation {situation}): {llm_response[:100]}"
                )
            else:
                logger.warning(
                    f"Could not parse situation number from LLM response: {llm_response[:100]}"
                )
                classification = default_classification

    except Exception as e:
        logger.error(f"Error calling LLM for context selection: {e}")
        classification = default_classification

    # To save some effort down the line, if there is nothing surrounding, don't allow a classification of adjacent or whole doc
    if (
        not section_above_text
        and not section_below_text
        and classification != ContextExpansionType.NOT_RELEVANT
    ):
        classification = ContextExpansionType.MAIN_SECTION_ONLY

    return classification
