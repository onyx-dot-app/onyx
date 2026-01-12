import json
import re
from collections.abc import Callable
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
from onyx.chat.models import ChatLoadedFile
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import PersonaOverrideConfig
from onyx.chat.models import ThreadMessage
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.configs.constants import MessageType
from onyx.configs.constants import TMP_DRALPHA_PERSONA_NAME
from onyx.context.search.models import RerankingDetails
from onyx.context.search.models import RetrievalDetails
from onyx.db.chat import create_chat_session
from onyx.db.chat import get_chat_messages_by_session
from onyx.db.chat import get_or_create_root_message
from onyx.db.kg_config import get_kg_config_settings
from onyx.db.kg_config import is_kg_config_settings_enabled_valid
from onyx.db.llm import fetch_existing_doc_sets
from onyx.db.llm import fetch_existing_tools
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.db.models import Persona
from onyx.db.models import SearchDoc as DbSearchDoc
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.projects import check_project_ownership
from onyx.db.search_settings import get_current_search_settings
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import FileDescriptor
from onyx.kg.models import KGException
from onyx.kg.setup.kg_default_entity_definitions import (
    populate_missing_default_entity_types__commit,
)
from onyx.llm.override_models import LLMOverride
from onyx.natural_language_processing.utils import BaseTokenizer
from onyx.prompts.chat_prompts import ADDITIONAL_CONTEXT_PROMPT
from onyx.prompts.chat_prompts import TOOL_CALL_RESPONSE_CROSS_MESSAGE
from onyx.prompts.tool_prompts import TOOL_CALL_FAILURE_PROMPT
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.server.query_and_chat.models import MessageOrigin
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.tools.models import ToolCallKickoff
from onyx.tools.tool_implementations.custom.custom_tool import (
    build_custom_tools_from_openapi_schema_and_headers,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time


logger = setup_logger()


def create_chat_session_from_request(
    chat_session_request: ChatSessionCreationRequest,
    user_id: UUID | None,
    db_session: Session,
) -> ChatSession:
    """Create a chat session from a ChatSessionCreationRequest.

    Includes project ownership validation when project_id is provided.

    Args:
        chat_session_request: The request containing persona_id, description, and project_id
        user_id: The ID of the user creating the session (can be None for anonymous)
        db_session: The database session

    Returns:
        The newly created ChatSession

    Raises:
        ValueError: If user lacks access to the specified project
        Exception: If the persona is invalid
    """
    project_id = chat_session_request.project_id
    if project_id:
        if not check_project_ownership(project_id, user_id, db_session):
            raise ValueError("User does not have access to project")

    return create_chat_session(
        db_session=db_session,
        description=chat_session_request.description or "",
        user_id=user_id,
        persona_id=chat_session_request.persona_id,
        project_id=chat_session_request.project_id,
    )


def prepare_chat_message_request(
    message_text: str,
    user: User | None,
    persona_id: int | None,
    # Does the question need to have a persona override
    persona_override_config: PersonaOverrideConfig | None,
    message_ts_to_respond_to: str | None,
    retrieval_details: RetrievalDetails | None,
    rerank_settings: RerankingDetails | None,
    db_session: Session,
    skip_gen_ai_answer_generation: bool = False,
    llm_override: LLMOverride | None = None,
    allowed_tool_ids: list[int] | None = None,
    forced_tool_ids: list[int] | None = None,
    origin: MessageOrigin | None = None,
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
        # Can always override the persona for the single query, if it's a normal persona
        # then it will be treated the same
        persona_override_config=persona_override_config,
        search_doc_ids=None,
        retrieval_options=retrieval_details,
        rerank_settings=rerank_settings,
        skip_gen_ai_answer_generation=skip_gen_ai_answer_generation,
        llm_override=llm_override,
        allowed_tool_ids=allowed_tool_ids,
        forced_tool_ids=forced_tool_ids,
        origin=origin or MessageOrigin.UNKNOWN,
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


def create_chat_history_chain(
    chat_session_id: UUID,
    db_session: Session,
    prefetch_top_two_level_tool_calls: bool = True,
    # Optional id at which we finish processing
    stop_at_message_id: int | None = None,
) -> list[ChatMessage]:
    """Build the linear chain of messages without including the root message"""
    mainline_messages: list[ChatMessage] = []

    all_chat_messages = get_chat_messages_by_session(
        chat_session_id=chat_session_id,
        user_id=None,
        db_session=db_session,
        skip_permission_check=True,
        prefetch_top_two_level_tool_calls=prefetch_top_two_level_tool_calls,
    )

    if not all_chat_messages:
        root_message = get_or_create_root_message(
            chat_session_id=chat_session_id, db_session=db_session
        )
    else:
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
        current_message = child_msg

        if (
            current_message.message_type == MessageType.ASSISTANT
            and previous_message is not None
            and previous_message.message_type == MessageType.ASSISTANT
            and mainline_messages
        ):
            # Note that 2 user messages in a row is fine since this is often used for
            # adding custom prompts and reminders
            raise RuntimeError(
                "Invalid message chain, cannot have two assistant messages in a row"
            )
        else:
            mainline_messages.append(current_message)

        previous_message = current_message

    return mainline_messages


def combine_message_chain(
    messages: list[ChatMessage],
    token_limit: int,
    msg_limit: int | None = None,
) -> str:
    """Used for secondary LLM flows that require the chat history,"""
    message_strs: list[str] = []
    total_token_count = 0

    if msg_limit is not None:
        messages = messages[-msg_limit:]

    for message in cast(list[ChatMessage], reversed(messages)):
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
                iter([c for c in citations if c.citation_number == int(citation_num)]),
                None,
            )
            if matching_citation is None:
                continue

            new_citation_info[citation_num] = CitationInfo(
                citation_number=len(new_citation_info) + 1,
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
                link_text = new_citation_info[citation_num].citation_number
        except Exception:
            pass

        link_url = match.group(2)
        return f"[[{link_text}]]({link_url})"

    # Substitute all matches in the input text
    new_answer = re.sub(pattern, slack_link_format, answer)

    # if any citations weren't parsable, just add them back to be safe
    for citation in citations:
        if citation.citation_number not in new_citation_info:
            new_citation_info[citation.citation_number] = citation

    return new_answer, list(new_citation_info.values())


def build_citation_map_from_infos(
    citations_list: list[CitationInfo], db_docs: list[DbSearchDoc]
) -> dict[int, int]:
    """Translate a list of streaming CitationInfo objects into a mapping of
    citation number -> saved search doc DB id.

    Always cites the first instance of a document_id and assumes db_docs are
    ordered as shown to the user (display order).
    """
    doc_id_to_saved_doc_id_map: dict[str, int] = {}
    for db_doc in db_docs:
        if db_doc.document_id not in doc_id_to_saved_doc_id_map:
            doc_id_to_saved_doc_id_map[db_doc.document_id] = db_doc.id

    citation_to_saved_doc_id_map: dict[int, int] = {}
    for citation in citations_list:
        if citation.citation_number not in citation_to_saved_doc_id_map:
            saved_id = doc_id_to_saved_doc_id_map.get(citation.document_id)
            if saved_id is not None:
                citation_to_saved_doc_id_map[citation.citation_number] = saved_id

    return citation_to_saved_doc_id_map


def build_citation_map_from_numbers(
    cited_numbers: list[int] | set[int], db_docs: list[DbSearchDoc]
) -> dict[int, int]:
    """Translate parsed citation numbers (e.g., from [[n]]) into a mapping of
    citation number -> saved search doc DB id by positional index.
    """
    citation_to_saved_doc_id_map: dict[int, int] = {}
    for num in sorted(set(cited_numbers)):
        idx = num - 1
        if 0 <= idx < len(db_docs):
            citation_to_saved_doc_id_map[num] = db_docs[idx].id

    return citation_to_saved_doc_id_map


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
        # Use the first prompt from the override config for embedded prompt fields
        first_prompt = persona_config.prompts[0]
        persona.system_prompt = first_prompt.system_prompt
        persona.task_prompt = first_prompt.task_prompt
        persona.datetime_aware = first_prompt.datetime_aware

    persona.tools = []
    if persona_config.custom_tools_openapi:
        from onyx.chat.emitter import get_default_emitter

        for schema in persona_config.custom_tools_openapi:
            tools = cast(
                list[Tool],
                build_custom_tools_from_openapi_schema_and_headers(
                    tool_id=0,  # dummy tool id
                    openapi_schema=schema,
                    emitter=get_default_emitter(),
                ),
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
    if not persona_name.startswith(TMP_DRALPHA_PERSONA_NAME):
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


@log_function_time(print_only=True)
def load_chat_file(
    file_descriptor: FileDescriptor, db_session: Session
) -> ChatLoadedFile:
    file_io = get_default_file_store().read_file(file_descriptor["id"], mode="b")
    content = file_io.read()

    # Extract text content if it's a text file type (not an image)
    content_text = None
    # `FileDescriptor` is often JSON-roundtripped (e.g. JSONB / API), so `type`
    # may arrive as a raw string value instead of a `ChatFileType`.
    file_type = ChatFileType(file_descriptor["type"])

    if file_type.is_text_file():
        try:
            content_text = extract_file_text(
                file=file_io,
                file_name=file_descriptor.get("name") or "",
                break_on_unprocessable=False,
            )
        except Exception as e:
            logger.warning(
                f"Failed to retrieve content for file {file_descriptor['id']}: {str(e)}"
            )

    # Get token count from UserFile if available
    token_count = 0
    user_file_id_str = file_descriptor.get("user_file_id")
    if user_file_id_str:
        try:
            user_file_id = UUID(user_file_id_str)
            user_file = (
                db_session.query(UserFile).filter(UserFile.id == user_file_id).first()
            )
            if user_file and user_file.token_count:
                token_count = user_file.token_count
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Failed to get token count for file {file_descriptor['id']}: {e}"
            )

    return ChatLoadedFile(
        file_id=file_descriptor["id"],
        content=content,
        file_type=file_type,
        filename=file_descriptor.get("name"),
        content_text=content_text,
        token_count=token_count,
    )


def load_all_chat_files(
    chat_messages: list[ChatMessage],
    db_session: Session,
) -> list[ChatLoadedFile]:
    # TODO There is likely a more efficient/standard way to load the files here.
    file_descriptors_for_history: list[FileDescriptor] = []
    for chat_message in chat_messages:
        if chat_message.files:
            file_descriptors_for_history.extend(chat_message.files)

    files = cast(
        list[ChatLoadedFile],
        run_functions_tuples_in_parallel(
            [
                (load_chat_file, (file, db_session))
                for file in file_descriptors_for_history
            ]
        ),
    )
    return files


def convert_chat_history(
    chat_history: list[ChatMessage],
    files: list[ChatLoadedFile],
    project_image_files: list[ChatLoadedFile],
    additional_context: str | None,
    token_counter: Callable[[str], int],
    tool_id_to_name_map: dict[int, str],
) -> list[ChatMessageSimple]:
    """Convert ChatMessage history to ChatMessageSimple format.

    For user messages: includes attached files (images attached to message, text files as separate messages)
    For assistant messages: includes tool calls followed by the assistant response
    """
    simple_messages: list[ChatMessageSimple] = []

    # Create a mapping of file IDs to loaded files for quick lookup
    file_map = {str(f.file_id): f for f in files}

    # Find the index of the last USER message
    last_user_message_idx = None
    for i in range(len(chat_history) - 1, -1, -1):
        if chat_history[i].message_type == MessageType.USER:
            last_user_message_idx = i
            break

    for idx, chat_message in enumerate(chat_history):
        if chat_message.message_type == MessageType.USER:
            # Process files attached to this message
            text_files: list[ChatLoadedFile] = []
            image_files: list[ChatLoadedFile] = []

            if chat_message.files:
                for file_descriptor in chat_message.files:
                    file_id = file_descriptor["id"]
                    loaded_file = file_map.get(file_id)
                    if loaded_file:
                        if loaded_file.file_type == ChatFileType.IMAGE:
                            image_files.append(loaded_file)
                        else:
                            # Text files (DOC, PLAIN_TEXT, CSV) are added as separate messages
                            text_files.append(loaded_file)

            # Add text files as separate messages before the user message
            for text_file in text_files:
                file_text = text_file.content_text or ""
                filename = text_file.filename
                message = (
                    f"File: {filename}\n{file_text}\nEnd of File"
                    if filename
                    else file_text
                )
                simple_messages.append(
                    ChatMessageSimple(
                        message=message,
                        token_count=text_file.token_count,
                        message_type=MessageType.USER,
                        image_files=None,
                    )
                )

            # Sum token counts from image files (excluding project image files)
            image_token_count = (
                sum(img.token_count for img in image_files) if image_files else 0
            )

            # Add the user message with image files attached
            # If this is the last USER message, also include project_image_files
            # Note: project image file tokens are NOT counted in the token count
            if idx == last_user_message_idx:
                if project_image_files:
                    image_files.extend(project_image_files)

                if additional_context:
                    simple_messages.append(
                        ChatMessageSimple(
                            message=ADDITIONAL_CONTEXT_PROMPT.format(
                                additional_context=additional_context
                            ),
                            token_count=token_counter(additional_context),
                            message_type=MessageType.USER,
                            image_files=None,
                        )
                    )

            simple_messages.append(
                ChatMessageSimple(
                    message=chat_message.message,
                    token_count=chat_message.token_count + image_token_count,
                    message_type=MessageType.USER,
                    image_files=image_files if image_files else None,
                )
            )

        elif chat_message.message_type == MessageType.ASSISTANT:
            # Add tool calls if present
            # Tool calls should be ordered by turn_number, then by tool_id within each turn
            if chat_message.tool_calls:
                # Group tool calls by turn number
                tool_calls_by_turn: dict[int, list] = {}
                for tool_call in chat_message.tool_calls:
                    if tool_call.turn_number not in tool_calls_by_turn:
                        tool_calls_by_turn[tool_call.turn_number] = []
                    tool_calls_by_turn[tool_call.turn_number].append(tool_call)

                # Sort turns and process each turn
                for turn_number in sorted(tool_calls_by_turn.keys()):
                    turn_tool_calls = tool_calls_by_turn[turn_number]
                    # Sort by tool_id within the turn for consistent ordering
                    turn_tool_calls.sort(key=lambda tc: tc.tool_id)

                    # Add each tool call as a separate message with the tool arguments
                    for tool_call in turn_tool_calls:
                        # Create a message containing the tool call information
                        tool_name = tool_id_to_name_map.get(
                            tool_call.tool_id, "unknown"
                        )
                        tool_call_data = {
                            "function_name": tool_name,
                            "arguments": tool_call.tool_call_arguments,
                        }
                        tool_call_message = json.dumps(tool_call_data)
                        simple_messages.append(
                            ChatMessageSimple(
                                message=tool_call_message,
                                token_count=tool_call.tool_call_tokens,
                                message_type=MessageType.TOOL_CALL,
                                image_files=None,
                                tool_call_id=tool_call.tool_call_id,
                            )
                        )

                        simple_messages.append(
                            ChatMessageSimple(
                                message=TOOL_CALL_RESPONSE_CROSS_MESSAGE,
                                token_count=20,  # Tiny overestimate
                                message_type=MessageType.TOOL_CALL_RESPONSE,
                                image_files=None,
                                tool_call_id=tool_call.tool_call_id,
                            )
                        )

            # Add the assistant message itself
            simple_messages.append(
                ChatMessageSimple(
                    message=chat_message.message,
                    token_count=chat_message.token_count,
                    message_type=MessageType.ASSISTANT,
                    image_files=None,
                )
            )
        else:
            raise ValueError(
                f"Invalid message type when constructing simple history: {chat_message.message_type}"
            )

    return simple_messages


def get_custom_agent_prompt(persona: Persona, chat_session: ChatSession) -> str | None:
    """Get the custom agent prompt from persona or project instructions.

    Chat Sessions in Projects that are using a custom agent will retain the custom agent prompt.
    Priority: persona.system_prompt > chat_session.project.instructions > None

    Args:
        persona: The Persona object
        chat_session: The ChatSession object

    Returns:
        The custom agent prompt string, or None if neither persona nor project has one
    """
    # Not considered a custom agent if it's the default behavior persona
    if persona.id == DEFAULT_PERSONA_ID:
        return None

    if persona.system_prompt:
        return persona.system_prompt
    elif chat_session.project and chat_session.project.instructions:
        return chat_session.project.instructions
    else:
        return None


def is_last_assistant_message_clarification(chat_history: list[ChatMessage]) -> bool:
    """Check if the last assistant message in chat history was a clarification question.

    This is used in the deep research flow to determine whether to skip the
    clarification step when the user has already responded to a clarification.

    Args:
        chat_history: List of ChatMessage objects in chronological order

    Returns:
        True if the last assistant message has is_clarification=True, False otherwise
    """
    for message in reversed(chat_history):
        if message.message_type == MessageType.ASSISTANT:
            return message.is_clarification
    return False


def create_tool_call_failure_messages(
    tool_call: ToolCallKickoff, token_counter: Callable[[str], int]
) -> list[ChatMessageSimple]:
    """Create ChatMessageSimple objects for a failed tool call.

    Creates two messages:
    1. The tool call message itself
    2. A failure response message indicating the tool call failed

    Args:
        tool_call: The ToolCallKickoff object representing the failed tool call
        token_counter: Function to count tokens in a message string

    Returns:
        List containing two ChatMessageSimple objects: tool call message and failure response
    """
    tool_call_msg = ChatMessageSimple(
        message=tool_call.to_msg_str(),
        token_count=token_counter(tool_call.to_msg_str()),
        message_type=MessageType.TOOL_CALL,
        tool_call_id=tool_call.tool_call_id,
        image_files=None,
    )

    failure_response_msg = ChatMessageSimple(
        message=TOOL_CALL_FAILURE_PROMPT,
        token_count=token_counter(TOOL_CALL_FAILURE_PROMPT),
        message_type=MessageType.TOOL_CALL_RESPONSE,
        tool_call_id=tool_call.tool_call_id,
        image_files=None,
    )

    return [tool_call_msg, failure_response_msg]
