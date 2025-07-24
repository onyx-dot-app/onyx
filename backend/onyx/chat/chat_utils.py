import re
from typing import cast
from uuid import UUID

from fastapi import HTTPException
from fastapi.datastructures import Headers
from sqlalchemy.orm import Session

from onyx.auth.users import is_user_admin
from onyx.background.celery.tasks.kg_processing.kg_indexing import (
    try_creating_kg_processing_task,
)
from onyx.background.celery.tasks.kg_processing.kg_indexing import (
    try_creating_kg_source_reset_task,
)
from onyx.chat.models import CitationInfo
from onyx.chat.models import LlmDoc
from onyx.chat.models import PersonaOverrideConfig
from onyx.chat.models import ThreadMessage
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.configs.constants import MessageType
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import RerankingDetails
from onyx.context.search.models import RetrievalDetails
from onyx.db.chat import create_chat_session
from onyx.db.chat import get_chat_messages_by_session
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import is_kg_config_settings_enabled_valid
from onyx.db.llm import fetch_existing_doc_sets
from onyx.db.llm import fetch_existing_tools
from onyx.db.models import ChatMessage
from onyx.db.models import Persona
from onyx.db.models import Prompt
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.db.prompts import get_prompts_by_ids
from onyx.db.search_settings import get_current_search_settings
from onyx.kg.models import KGException
from onyx.kg.setup.kg_default_entity_definitions import (
    populate_missing_default_entity_types__commit,
)
from onyx.llm.models import PreviousMessage
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()


def prepare_chat_message_request(
    message_text: str,
    user: User | None,
    persona_id: int | None,
    # Does the question need to have a persona override
    persona_override_config: PersonaOverrideConfig | None,
    prompt: Prompt | None,
    message_ts_to_respond_to: str | None,
    retrieval_details: RetrievalDetails | None,
    rerank_settings: RerankingDetails | None,
    db_session: Session,
    use_agentic_search: bool = False,
    skip_gen_ai_answer_generation: bool = False,
) -> CreateChatMessageRequest:
    # Typically used for one shot flows like SlackBot or non-chat API endpoint use cases
    new_chat_session = create_chat_session(
        db_session=db_session,
        description=None,
        user_id=user.id if user else None,
        # If using an override, this id will be ignored later on
        persona_id=persona_id or DEFAULT_PERSONA_ID,
        onyxbot_flow=True,
        slack_thread_id=message_ts_to_respond_to,
    )

    return CreateChatMessageRequest(
        chat_session_id=new_chat_session.id,
        parent_message_id=None,  # It's a standalone chat session each time
        message=message_text,
        file_descriptors=[],  # Currently SlackBot/answer api do not support files in the context
        prompt_id=prompt.id if prompt else None,
        # Can always override the persona for the single query, if it's a normal persona
        # then it will be treated the same
        persona_override_config=persona_override_config,
        search_doc_ids=None,
        retrieval_options=retrieval_details,
        rerank_settings=rerank_settings,
        use_agentic_search=use_agentic_search,
        skip_gen_ai_answer_generation=skip_gen_ai_answer_generation,
    )


def llm_doc_from_inference_section(inference_section: InferenceSection) -> LlmDoc:
    return LlmDoc(
        document_id=inference_section.center_chunk.document_id,
        # This one is using the combined content of all the chunks of the section
        # In default settings, this is the same as just the content of base chunk
        content=inference_section.combined_content,
        blurb=inference_section.center_chunk.blurb,
        semantic_identifier=inference_section.center_chunk.semantic_identifier,
        source_type=inference_section.center_chunk.source_type,
        metadata=inference_section.center_chunk.metadata,
        updated_at=inference_section.center_chunk.updated_at,
        link=(
            inference_section.center_chunk.source_links[0]
            if inference_section.center_chunk.source_links
            else None
        ),
        source_links=inference_section.center_chunk.source_links,
        match_highlights=inference_section.center_chunk.match_highlights,
    )


def combine_message_thread(
    messages: list[ThreadMessage],
    max_tokens: int | None,
    llm_tokenizer: BaseTokenizer,
) -> str:
    """Used to create a single combined message context from threads"""
    if not messages:
        return ""

    message_strs: list[str] = []
    total_token_count = 0

    for message in reversed(messages):
        if message.role == MessageType.USER:
            role_str = message.role.value.upper()
            if message.sender:
                role_str += " " + message.sender
            else:
                # Since other messages might have the user identifying information
                # better to use Unknown for symmetry
                role_str += " Unknown"
        else:
            role_str = message.role.value.upper()

        msg_str = f"{role_str}:\n{message.message}"
        message_token_count = len(llm_tokenizer.encode(msg_str))

        if (
            max_tokens is not None
            and total_token_count + message_token_count > max_tokens
        ):
            break

        message_strs.insert(0, msg_str)
        total_token_count += message_token_count

    return "\n\n".join(message_strs)


def create_chat_chain(
    chat_session_id: UUID,
    db_session: Session,
    prefetch_tool_calls: bool = True,
    # Optional id at which we finish processing
    stop_at_message_id: int | None = None,
) -> tuple[ChatMessage, list[ChatMessage]]:
    """Build the linear chain of messages without including the root message"""
    mainline_messages: list[ChatMessage] = []

    all_chat_messages = get_chat_messages_by_session(
        chat_session_id=chat_session_id,
        user_id=None,
        db_session=db_session,
        skip_permission_check=True,
        prefetch_tool_calls=prefetch_tool_calls,
    )
    id_to_msg = {msg.id: msg for msg in all_chat_messages}

    if not all_chat_messages:
        raise RuntimeError("No messages in Chat Session")

    root_message = all_chat_messages[0]
    if root_message.parent_message is not None:
        raise RuntimeError(
            "Invalid root message, unable to fetch valid chat message sequence"
        )

    current_message: ChatMessage | None = root_message
    previous_message: ChatMessage | None = None
    while current_message is not None:
        child_msg = current_message.latest_child_message

        # Break if at the end of the chain
        # or have reached the `final_id` of the submitted message
        if not child_msg or (
            stop_at_message_id and current_message.id == stop_at_message_id
        ):
            break
        current_message = id_to_msg.get(child_msg)

        if current_message is None:
            raise RuntimeError(
                "Invalid message chain,"
                "could not find next message in the same session"
            )

        if (
            current_message.message_type == MessageType.ASSISTANT
            and previous_message is not None
            and previous_message.message_type == MessageType.ASSISTANT
            and mainline_messages
        ):
            if current_message.refined_answer_improvement:
                mainline_messages[-1] = current_message
        else:
            mainline_messages.append(current_message)

        previous_message = current_message

    if not mainline_messages:
        raise RuntimeError("Could not trace chat message history")

    return mainline_messages[-1], mainline_messages[:-1]


def combine_message_chain(
    messages: list[ChatMessage] | list[PreviousMessage],
    token_limit: int,
    msg_limit: int | None = None,
) -> str:
    """Used for secondary LLM flows that require the chat history,"""
    message_strs: list[str] = []
    total_token_count = 0

    if msg_limit is not None:
        messages = messages[-msg_limit:]

    for message in cast(list[ChatMessage] | list[PreviousMessage], reversed(messages)):
        message_token_count = message.token_count

        if total_token_count + message_token_count > token_limit:
            break

        role = message.message_type.value.upper()
        message_strs.insert(0, f"{role}:\n{message.message}")
        total_token_count += message_token_count

    return "\n\n".join(message_strs)


def reorganize_citations(
    answer: str, citations: list[CitationInfo]
) -> tuple[str, list[CitationInfo]]:
    """For a complete, citation-aware response, we want to reorganize the citations so that
    they are in the order of the documents that were used in the response. This just looks nicer / avoids
    confusion ("Why is there [7] when only 2 documents are cited?")."""

    # Regular expression to find all instances of [[x]](LINK)
    pattern = r"\[\[(.*?)\]\]\((.*?)\)"

    all_citation_matches = re.findall(pattern, answer)

    new_citation_info: dict[int, CitationInfo] = {}
    for citation_match in all_citation_matches:
        try:
            citation_num = int(citation_match[0])
            if citation_num in new_citation_info:
                continue

            matching_citation = next(
                iter([c for c in citations if c.citation_num == int(citation_num)]),
                None,
            )
            if matching_citation is None:
                continue

            new_citation_info[citation_num] = CitationInfo(
                citation_num=len(new_citation_info) + 1,
                document_id=matching_citation.document_id,
            )
        except Exception:
            pass

    # Function to replace citations with their new number
    def slack_link_format(match: re.Match) -> str:
        link_text = match.group(1)
        try:
            citation_num = int(link_text)
            if citation_num in new_citation_info:
                link_text = new_citation_info[citation_num].citation_num
        except Exception:
            pass

        link_url = match.group(2)
        return f"[[{link_text}]]({link_url})"

    # Substitute all matches in the input text
    new_answer = re.sub(pattern, slack_link_format, answer)

    # if any citations weren't parsable, just add them back to be safe
    for citation in citations:
        if citation.citation_num not in new_citation_info:
            new_citation_info[citation.citation_num] = citation

    return new_answer, list(new_citation_info.values())


def extract_headers(
    headers: dict[str, str] | Headers, pass_through_headers: list[str] | None
) -> dict[str, str]:
    """
    Extract headers specified in pass_through_headers from input headers.
    Handles both dict and FastAPI Headers objects, accounting for lowercase keys.

    Args:
        headers: Input headers as dict or Headers object.

    Returns:
        dict: Filtered headers based on pass_through_headers.
    """
    if not pass_through_headers:
        return {}

    extracted_headers: dict[str, str] = {}
    for key in pass_through_headers:
        if key in headers:
            extracted_headers[key] = headers[key]
        else:
            # fastapi makes all header keys lowercase, handling that here
            lowercase_key = key.lower()
            if lowercase_key in headers:
                extracted_headers[lowercase_key] = headers[lowercase_key]
    return extracted_headers


def create_temporary_persona(
    persona_config: PersonaOverrideConfig, db_session: Session, user: User | None = None
) -> Persona:
    if not is_user_admin(user):
        raise HTTPException(
            status_code=403,
            detail="User is not authorized to create a persona in one shot queries",
        )

    """Create a temporary Persona object from the provided configuration."""
    persona = Persona(
        name=persona_config.name,
        description=persona_config.description,
        num_chunks=persona_config.num_chunks,
        llm_relevance_filter=persona_config.llm_relevance_filter,
        llm_filter_extraction=persona_config.llm_filter_extraction,
        recency_bias=persona_config.recency_bias,
        llm_model_provider_override=persona_config.llm_model_provider_override,
        llm_model_version_override=persona_config.llm_model_version_override,
    )

    if persona_config.prompts:
        persona.prompts = [
            Prompt(
                name=p.name,
                description=p.description,
                system_prompt=p.system_prompt,
                task_prompt=p.task_prompt,
                include_citations=p.include_citations,
                datetime_aware=p.datetime_aware,
            )
            for p in persona_config.prompts
        ]
    elif persona_config.prompt_ids:
        persona.prompts = get_prompts_by_ids(
            db_session=db_session, prompt_ids=persona_config.prompt_ids
        )

    persona.tools = []
    if persona_config.custom_tools_openapi:
        for schema in persona_config.custom_tools_openapi:
            tools = cast(
                list[Tool],
                build_custom_tools_from_openapi_schema_and_headers(schema),
            )
            persona.tools.extend(tools)

    if persona_config.tools:
        tool_ids = [tool.id for tool in persona_config.tools]
        persona.tools.extend(
            fetch_existing_tools(db_session=db_session, tool_ids=tool_ids)
        )

    if persona_config.tool_ids:
        persona.tools.extend(
            fetch_existing_tools(
                db_session=db_session, tool_ids=persona_config.tool_ids
            )
        )

    fetched_docs = fetch_existing_doc_sets(
        db_session=db_session, doc_ids=persona_config.document_set_ids
    )
    persona.document_sets = fetched_docs

    return persona


def process_kg_commands(
    message: str, persona_name: str, tenant_id: str, db_session: Session
) -> None:
    # Temporarily, until we have a draft UI for the KG Operations/Management
    # TODO: move to api endpoint once we get frontend
    if not persona_name.startswith("KG Beta"):
        return

    kg_config_settings = get_kg_config_settings()
    if not is_kg_config_settings_enabled_valid(kg_config_settings):
        return

    # get Vespa index
    search_settings = get_current_search_settings(db_session)
    index_str = search_settings.index_name

    if message == "kg_p":
        success = try_creating_kg_processing_task(tenant_id)
        if success:
            raise KGException("KG processing scheduled")
        else:
            raise KGException(
                "Cannot schedule another KG processing if one is already running "
                "or there are no documents to process"
            )

    elif message.startswith("kg_rs_source"):
        msg_split = [x for x in message.split(":")]
        if len(msg_split) > 2:
            raise KGException("Invalid format for a source reset command")
        elif len(msg_split) == 2:
            source_name = msg_split[1].strip()
        elif len(msg_split) == 1:
            source_name = None
        else:
            raise KGException("Invalid format for a source reset command")

        success = try_creating_kg_source_reset_task(tenant_id, source_name, index_str)
        if success:
            source_name = source_name or "all"
            raise KGException(f"KG index reset for source '{source_name}' scheduled")
        else:
            raise KGException("Cannot reset index while KG processing is running")

    elif message == "kg_setup":
        populate_missing_default_entity_types__commit(db_session=db_session)
        raise KGException("KG setup done")
