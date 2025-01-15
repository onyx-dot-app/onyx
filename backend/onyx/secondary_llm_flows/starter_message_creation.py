import json
import re
from typing import Any
from typing import cast
from typing import Dict
from typing import List

from litellm import get_supported_openai_params
from sqlalchemy.orm import Session

from onyx.configs.chat_configs import NUM_PERSONA_PROMPT_GENERATION_CHUNKS
from onyx.configs.chat_configs import NUM_PERSONA_PROMPTS
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.postprocessing.postprocessing import cleanup_chunks
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.db.document_set import get_document_sets_by_ids
from onyx.db.models import StarterMessageModel as StarterMessage
from onyx.db.models import User
from onyx.document_index.document_index_utils import get_both_index_names
from onyx.document_index.factory import get_default_document_index
from onyx.llm.factory import get_default_llms
from onyx.prompts.starter_messages import PERSONA_CATEGORY_GENERATION_PROMPT
from onyx.prompts.starter_messages import PERSONA_STARTER_MESSAGE_CREATION_PROMPT
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import FunctionCall
from onyx.utils.threadpool_concurrency import run_functions_in_parallel

logger = setup_logger()


def get_random_chunks_from_doc_sets(
    doc_sets: List[str], db_session: Session, user: User | None = None
) -> List[InferenceChunk]:
    """
    Retrieves random chunks from the specified document sets.
    """
    curr_ind_name, sec_ind_name = get_both_index_names(db_session)
    document_index = get_default_document_index(curr_ind_name, sec_ind_name)

    acl_filters = build_access_filters_for_user(user, db_session)
    filters = IndexFilters(document_set=doc_sets, access_control_list=acl_filters)

    chunks = document_index.random_retrieval(
        filters=filters, num_to_retrieve=NUM_PERSONA_PROMPT_GENERATION_CHUNKS
    )
    return cleanup_chunks(chunks)


def parse_categories(content: str) -> List[str]:
    """
    Parses the JSON array of categories from the LLM response.
    """
    # Clean the response to remove code fences and extra whitespace
    content = content.strip().strip("```").strip()
    if content.startswith("json"):
        content = content[4:].strip()

    try:
        categories = json.loads(content)
        if not isinstance(categories, list):
            logger.error("Categories are not a list.")
            return []
        return categories
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse categories: {e}")
        return []


def generate_start_message_prompts(
    name: str,
    description: str,
    instructions: str,
    categories: List[str],
    chunk_contents: str,
    supports_structured_output: bool,
    fast_llm: Any,
) -> List[FunctionCall]:
    """
    Generates the list of FunctionCall objects for starter message generation.
    """
    functions = []
    for category in categories:
        # Create a prompt specific to the category
        start_message_generation_prompt = (
            PERSONA_STARTER_MESSAGE_CREATION_PROMPT.format(
                name=name,
                description=description,
                instructions=instructions,
                category=category,
            )
        )

        if chunk_contents:
            start_message_generation_prompt += (
                "\n\nExample content this assistant has access to:\n"
                "'''\n"
                f"{chunk_contents}"
                "\n'''"
            )

        if supports_structured_output:
            functions.append(
                FunctionCall(
                    fast_llm.invoke,
                    (start_message_generation_prompt, None, None, StarterMessage),
                )
            )
        else:
            functions.append(
                FunctionCall(
                    fast_llm.invoke,
                    (start_message_generation_prompt,),
                )
            )
    return functions


def parse_unstructured_output(output: str) -> Dict[str, str]:
    """
    Parses the assistant's unstructured output into a dictionary with keys:
    - 'name' (Title)
    - 'message' (Message)
    """

    # Debug output
    logger.debug(f"LLM Output for starter message creation: {output}")

    # Patterns to match
    title_pattern = r"(?i)^\**Title\**\s*:\s*(.+)"
    message_pattern = r"(?i)^\**Message\**\s*:\s*(.+)"

    # Initialize the response dictionary
    response_dict = {}

    # Split the output into lines
    lines = output.strip().split("\n")

    # Variables to keep track of the current key being processed
    current_key = None
    current_value_lines = []

    for line in lines:
        # Check for title
        title_match = re.match(title_pattern, line.strip())
        if title_match:
            # Save previous key-value pair if any
            if current_key and current_value_lines:
                response_dict[current_key] = " ".join(current_value_lines).strip()
                current_value_lines = []
            current_key = "name"
            current_value_lines.append(title_match.group(1).strip())
            continue

        # Check for message
        message_match = re.match(message_pattern, line.strip())
        if message_match:
            if current_key and current_value_lines:
                response_dict[current_key] = " ".join(current_value_lines).strip()
                current_value_lines = []
            current_key = "message"
            current_value_lines.append(message_match.group(1).strip())
            continue

        # If the line doesn't match a new key, append it to the current value
        if current_key:
            current_value_lines.append(line.strip())

    # Add the last key-value pair
    if current_key and current_value_lines:
        response_dict[current_key] = " ".join(current_value_lines).strip()

    # Validate that the necessary keys are present
    if not all(k in response_dict for k in ["name", "message"]):
        raise ValueError("Failed to parse the assistant's response.")

    return response_dict


def generate_starter_messages(
    name: str,
    description: str,
    instructions: str,
    document_set_ids: List[int],
    db_session: Session,
    user: User | None,
) -> List[StarterMessage]:
    """
    Generates starter messages by first obtaining categories and then generating messages for each category.
    On failure, returns an empty list (or list with processed starter messages if some messages are processed successfully).
    """
    _, fast_llm = get_default_llms(temperature=0.5)

    provider = fast_llm.config.model_provider
    model = fast_llm.config.model_name

    params = get_supported_openai_params(model=model, custom_llm_provider=provider)
    supports_structured_output = (
        isinstance(params, list) and "response_format" in params
    )

    # Generate categories
    category_generation_prompt = PERSONA_CATEGORY_GENERATION_PROMPT.format(
        name=name,
        description=description,
        instructions=instructions,
        num_categories=NUM_PERSONA_PROMPTS,
    )

    category_response = fast_llm.invoke(category_generation_prompt)
    categories = parse_categories(cast(str, category_response.content))

    if not categories:
        logger.error("No categories were generated.")
        return []

    # Fetch example content if document sets are provided
    if document_set_ids:
        document_sets = get_document_sets_by_ids(
            document_set_ids=document_set_ids,
            db_session=db_session,
        )

        chunks = get_random_chunks_from_doc_sets(
            doc_sets=[doc_set.name for doc_set in document_sets],
            db_session=db_session,
            user=user,
        )

        # Add example content context
        chunk_contents = "\n".join(chunk.content.strip() for chunk in chunks)
    else:
        chunk_contents = ""

    # Generate prompts for starter messages
    functions = generate_start_message_prompts(
        name,
        description,
        instructions,
        categories,
        chunk_contents,
        supports_structured_output,
        fast_llm,
    )

    # Run LLM calls in parallel
    if not functions:
        logger.error("No functions to execute for starter message generation.")
        return []

    results = run_functions_in_parallel(function_calls=functions)
    prompts = []

    for response in results.values():
        try:
            if supports_structured_output:
                response_dict = json.loads(response.content)
            else:
                response_dict = parse_unstructured_output(response.content)
            starter_message = StarterMessage(
                name=response_dict["name"],
                message=response_dict["message"],
            )
            prompts.append(starter_message)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse starter message: {e}")
            continue

    return prompts
