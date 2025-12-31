"""
IMPORTANT: familiarize yourself with the design concepts prior to contributing to this file.
An overview can be found in the README.md file in this directory.
"""

import re
import traceback
from collections.abc import Callable
from collections.abc import Iterator
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_state import run_chat_loop_with_state_containers
from onyx.chat.chat_utils import convert_chat_history
from onyx.chat.chat_utils import create_chat_history_chain
from onyx.chat.chat_utils import get_custom_agent_prompt
from onyx.chat.chat_utils import is_last_assistant_message_clarification
from onyx.chat.chat_utils import load_all_chat_files
from onyx.chat.emitter import get_default_emitter
from onyx.chat.llm_loop import run_llm_loop
from onyx.chat.models import AnswerStream
from onyx.chat.models import ChatBasicResponse
from onyx.chat.models import ChatLoadedFile
from onyx.chat.models import ExtractedProjectFiles
from onyx.chat.models import MessageResponseIDInfo
from onyx.chat.models import ProjectFileMetadata
from onyx.chat.models import StreamingError
from onyx.chat.prompt_utils import calculate_reserved_tokens
from onyx.chat.save_chat import save_chat_turn
from onyx.chat.stop_signal_checker import is_connected as check_stop_signal
from onyx.chat.stop_signal_checker import reset_cancel_status
from onyx.configs.chat_configs import CHAT_TARGET_CHUNK_PERCENTAGE
from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.configs.constants import MessageType
from onyx.configs.constants import MilestoneRecordType
from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.models import CitationDocInfo
from onyx.context.search.models import SearchDoc
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_chat_message
from onyx.db.chat import get_chat_session_by_id
from onyx.db.chat import get_or_create_root_message
from onyx.db.chat import reserve_message_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.memory import get_memories
from onyx.db.models import ChatMessage
from onyx.db.models import User
from onyx.db.projects import get_project_token_count
from onyx.db.projects import get_user_files_from_project
from onyx.db.tools import get_tools
from onyx.deep_research.dr_loop import run_deep_research_llm_loop
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import FileDescriptor
from onyx.file_store.utils import load_in_memory_chat_files
from onyx.file_store.utils import verify_user_files
from onyx.llm.factory import get_llm_for_persona
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.utils import litellm_exception_to_error_msg
from onyx.onyxbot.slack.models import SlackContext
from onyx.redis.redis_pool import get_redis_client
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.utils import get_json_line
from onyx.tools.constants import SEARCH_TOOL_ID
from onyx.tools.interface import Tool
from onyx.tools.tool_constructor import construct_tools
from onyx.tools.tool_constructor import CustomToolConfig
from onyx.tools.tool_constructor import SearchToolConfig
from onyx.tools.tool_constructor import SearchToolUsage
from onyx.utils.logger import setup_logger
from onyx.utils.long_term_log import LongTermLogger
from onyx.utils.telemetry import mt_cloud_telemetry
from onyx.utils.timing import log_function_time
from onyx.utils.timing import log_generator_function_time
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()
ERROR_TYPE_CANCELLED = "cancelled"


class ToolCallException(Exception):
    """Exception raised for errors during tool calls."""

    def __init__(self, message: str, tool_name: str | None = None):
        super().__init__(message)
        self.tool_name = tool_name


def _extract_project_file_texts_and_images(
    project_id: int | None,
    user_id: UUID | None,
    llm_max_context_window: int,
    reserved_token_count: int,
    db_session: Session,
    # Because the tokenizer is a generic tokenizer, the token count may be incorrect.
    # to account for this, the maximum context that is allowed for this function is
    # 60% of the LLM's max context window. The other benefit is that for projects with
    # more files, this makes it so that we don't throw away the history too quickly every time.
    max_llm_context_percentage: float = 0.6,
) -> ExtractedProjectFiles:
    """Extract text content from project files if they fit within the context window.

    Args:
        project_id: The project ID to load files from
        user_id: The user ID for authorization
        llm_max_context_window: Maximum tokens allowed in the LLM context window
        reserved_token_count: Number of tokens to reserve for other content
        db_session: Database session
        max_llm_context_percentage: Maximum percentage of the LLM context window to use.

    Returns:
        ExtractedProjectFiles containing:
        - List of text content strings from project files (text files only)
        - List of image files from project (ChatLoadedFile objects)
        - Project id if the the project should be provided as a filter in search or None if not.
        - Total token count of all extracted files
    """
    # TODO I believe this is not handling all file types correctly.
    project_as_filter = False
    if not project_id:
        return ExtractedProjectFiles(
            project_file_texts=[],
            project_image_files=[],
            project_as_filter=False,
            total_token_count=0,
            project_file_metadata=[],
        )

    max_actual_tokens = (
        llm_max_context_window - reserved_token_count
    ) * max_llm_context_percentage

    # Calculate total token count for all user files in the project
    project_tokens = get_project_token_count(
        project_id=project_id,
        user_id=user_id,
        db_session=db_session,
    )

    project_file_texts: list[str] = []
    project_image_files: list[ChatLoadedFile] = []
    project_file_metadata: list[ProjectFileMetadata] = []
    total_token_count = 0
    if project_tokens < max_actual_tokens:
        # Load project files into memory using cached plaintext when available
        project_user_files = get_user_files_from_project(
            project_id=project_id,
            user_id=user_id,
            db_session=db_session,
        )
        if project_user_files:
            # Create a mapping from file_id to UserFile for token count lookup
            user_file_map = {str(file.id): file for file in project_user_files}

            project_file_ids = [file.id for file in project_user_files]
            in_memory_project_files = load_in_memory_chat_files(
                user_file_ids=project_file_ids,
                db_session=db_session,
            )

            # Extract text content from loaded files
            for file in in_memory_project_files:
                if file.file_type.is_text_file():
                    try:
                        text_content = file.content.decode("utf-8", errors="ignore")
                        # Strip null bytes
                        text_content = text_content.replace("\x00", "")
                        if text_content:
                            project_file_texts.append(text_content)
                            # Add metadata for citation support
                            project_file_metadata.append(
                                ProjectFileMetadata(
                                    file_id=str(file.file_id),
                                    filename=file.filename or f"file_{file.file_id}",
                                    file_content=text_content,
                                )
                            )
                            # Add token count for text file
                            user_file = user_file_map.get(str(file.file_id))
                            if user_file and user_file.token_count:
                                total_token_count += user_file.token_count
                    except Exception:
                        # Skip files that can't be decoded
                        pass
                elif file.file_type == ChatFileType.IMAGE:
                    # Convert InMemoryChatFile to ChatLoadedFile
                    user_file = user_file_map.get(str(file.file_id))
                    token_count = (
                        user_file.token_count
                        if user_file and user_file.token_count
                        else 0
                    )
                    total_token_count += token_count
                    chat_loaded_file = ChatLoadedFile(
                        file_id=file.file_id,
                        content=file.content,
                        file_type=file.file_type,
                        filename=file.filename,
                        content_text=None,  # Images don't have text content
                        token_count=token_count,
                    )
                    project_image_files.append(chat_loaded_file)
    else:
        project_as_filter = True

    return ExtractedProjectFiles(
        project_file_texts=project_file_texts,
        project_image_files=project_image_files,
        project_as_filter=project_as_filter,
        total_token_count=total_token_count,
        project_file_metadata=project_file_metadata,
    )


def _get_project_search_availability(
    project_id: int | None,
    persona_id: int | None,
    has_project_file_texts: bool,
    forced_tool_ids: list[int] | None,
    search_tool_id: int | None,
) -> SearchToolUsage:
    """Determine search tool availability based on project context.

    Args:
        project_id: The project ID if the user is in a project
        persona_id: The persona ID to check if it's the default persona
        has_project_file_texts: Whether project files are loaded in context
        forced_tool_ids: List of forced tool IDs (may be mutated to remove search tool)
        search_tool_id: The search tool ID to check against

    Returns:
        SearchToolUsage setting indicating how search should be used
    """
    # There are cases where the internal search tool should be disabled
    # If the user is in a project, it should not use other sources / generic search
    # If they are in a project but using a custom agent, it should use the agent setup
    # (which means it can use search)
    # However if in a project and there are more files than can fit in the context,
    # it should use the search tool with the project filter on
    # If no files are uploaded, search should remain enabled
    search_usage_forcing_setting = SearchToolUsage.AUTO
    if project_id:
        if bool(persona_id is DEFAULT_PERSONA_ID and has_project_file_texts):
            search_usage_forcing_setting = SearchToolUsage.DISABLED
            # Remove search tool from forced_tool_ids if it's present
            if forced_tool_ids and search_tool_id and search_tool_id in forced_tool_ids:
                forced_tool_ids[:] = [
                    tool_id for tool_id in forced_tool_ids if tool_id != search_tool_id
                ]
        elif forced_tool_ids and search_tool_id and search_tool_id in forced_tool_ids:
            search_usage_forcing_setting = SearchToolUsage.ENABLED
    return search_usage_forcing_setting


def _initialize_chat_session(
    message_text: str,
    files: list[FileDescriptor],
    token_counter: Callable[[str], int],
    parent_id: int | None,
    user_id: UUID | None,
    chat_session_id: UUID,
    db_session: Session,
    use_existing_user_message: bool = False,
) -> ChatMessage:
    root_message = get_or_create_root_message(
        chat_session_id=chat_session_id, db_session=db_session
    )

    if parent_id is None:
        parent_message = root_message
    else:
        parent_message = get_chat_message(
            chat_message_id=parent_id,
            user_id=user_id,
            db_session=db_session,
        )

    # For seeding, the parent message points to the message that is supposed to be the last
    # user message.
    if use_existing_user_message:
        if parent_message.parent_message is None:
            raise RuntimeError("No parent message found for seeding")
        if parent_message.message_type != MessageType.USER:
            raise RuntimeError(
                "Parent message is not a user message, needed for seeded flow."
            )
        message_text = parent_message.message
        token_count = parent_message.token_count
        parent_message = parent_message.parent_message
    else:
        token_count = token_counter(message_text)

    # Flushed for ID but not committed yet
    user_message = create_new_chat_message(
        chat_session_id=chat_session_id,
        parent_message=parent_message,
        message=message_text,
        token_count=token_count,
        message_type=MessageType.USER,
        files=files,
        db_session=db_session,
        commit=False,
    )
    return user_message


def stream_chat_message_objects(
    new_msg_req: CreateChatMessageRequest,
    user: User | None,
    db_session: Session,
    # Needed to translate persona num_chunks to tokens to the LLM
    default_num_chunks: float = MAX_CHUNKS_FED_TO_CHAT,
    # For flow with search, don't include as many chunks as possible since we need to leave space
    # for the chat history, for smaller models, we likely won't get MAX_CHUNKS_FED_TO_CHAT chunks
    max_document_percentage: float = CHAT_TARGET_CHUNK_PERCENTAGE,
    # if specified, uses the last user message and does not create a new user message based
    # on the `new_msg_req.message`. Currently, requires a state where the last message is a
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    is_connected: Callable[[], bool] | None = None,
    enforce_chat_session_id_for_search_docs: bool = True,
    bypass_acl: bool = False,
    # Additional context that should be included in the chat history, for example:
    # Slack threads where the conversation cannot be represented by a chain of User/Assistant
    # messages.
    # NOTE: is not stored in the database, only passed in to the LLM as context
    additional_context: str | None = None,
    # Slack context for federated Slack search
    slack_context: SlackContext | None = None,
) -> AnswerStream:
    tenant_id = get_current_tenant_id()
    use_existing_user_message = new_msg_req.use_existing_user_message

    llm: LLM | None = None

    try:
        user_id = user.id if user is not None else None
        llm_user_identifier = (
            user.email
            if user is not None and getattr(user, "email", None)
            else (str(user_id) if user_id else "anonymous_user")
        )

        chat_session = get_chat_session_by_id(
            chat_session_id=new_msg_req.chat_session_id,
            user_id=user_id,
            db_session=db_session,
        )
        persona = chat_session.persona

        message_text = new_msg_req.message
        chat_session_id = new_msg_req.chat_session_id
        user_identity = LLMUserIdentity(
            user_id=llm_user_identifier, session_id=str(chat_session_id)
        )
        parent_id = new_msg_req.parent_message_id
        reference_doc_ids = new_msg_req.search_doc_ids
        retrieval_options = new_msg_req.retrieval_options
        new_msg_req.alternate_assistant_id
        user_selected_filters = retrieval_options.filters if retrieval_options else None

        # permanent "log" store, used primarily for debugging
        long_term_logger = LongTermLogger(
            metadata={"user_id": str(user_id), "chat_session_id": str(chat_session_id)}
        )

        # Milestone tracking, most devs using the API don't need to understand this
        mt_cloud_telemetry(
            tenant_id=tenant_id,
            distinct_id=user.email if user else tenant_id,
            event=MilestoneRecordType.MULTIPLE_ASSISTANTS,
        )

        if reference_doc_ids is None and retrieval_options is None:
            raise RuntimeError(
                "Must specify a set of documents for chat or specify search options"
            )

        llm = get_llm_for_persona(
            persona=persona,
            user=user,
            llm_override=new_msg_req.llm_override or chat_session.llm_override,
            additional_headers=litellm_additional_headers,
            long_term_logger=long_term_logger,
        )
        token_counter = get_llm_token_counter(llm)

        # Verify that the user specified files actually belong to the user
        verify_user_files(
            user_files=new_msg_req.file_descriptors,
            user_id=user_id,
            db_session=db_session,
            project_id=chat_session.project_id,
        )

        # Makes sure that the chat session has the right message nodes
        # and that the latest user message is created (not yet committed)
        user_message = _initialize_chat_session(
            message_text=message_text,
            files=new_msg_req.file_descriptors,
            token_counter=token_counter,
            parent_id=parent_id,
            user_id=user_id,
            chat_session_id=chat_session_id,
            db_session=db_session,
            use_existing_user_message=use_existing_user_message,
        )

        # re-create linear history of messages
        chat_history = create_chat_history_chain(
            chat_session_id=chat_session_id, db_session=db_session
        )

        last_chat_message = chat_history[-1]

        if last_chat_message.id != user_message.id:
            db_session.rollback()
            raise RuntimeError(
                "The new message was not on the mainline. "
                "Chat message history tree is not correctly built."
            )

        # At this point we can save the user message as it's validated and final
        db_session.commit()

        memories = get_memories(user, db_session)

        custom_agent_prompt = get_custom_agent_prompt(persona, chat_session)

        reserved_token_count = calculate_reserved_tokens(
            db_session=db_session,
            persona_system_prompt=custom_agent_prompt or "",
            token_counter=token_counter,
            files=last_chat_message.files,
            memories=memories,
        )

        # Process projects, if all of the files fit in the context, it doesn't need to use RAG
        extracted_project_files = _extract_project_file_texts_and_images(
            project_id=chat_session.project_id,
            user_id=user_id,
            llm_max_context_window=llm.config.max_input_tokens,
            reserved_token_count=reserved_token_count,
            db_session=db_session,
        )

        # Build a mapping of tool_id to tool_name for history reconstruction
        all_tools = get_tools(db_session)
        tool_id_to_name_map = {tool.id: tool.name for tool in all_tools}

        search_tool_id = next(
            (tool.id for tool in all_tools if tool.in_code_tool_id == SEARCH_TOOL_ID),
            None,
        )

        # This may also mutate the new_msg_req.forced_tool_ids
        # This logic is specifically for projects
        search_usage_forcing_setting = _get_project_search_availability(
            project_id=chat_session.project_id,
            persona_id=persona.id,
            has_project_file_texts=bool(extracted_project_files.project_file_texts),
            forced_tool_ids=new_msg_req.forced_tool_ids,
            search_tool_id=search_tool_id,
        )

        # TODO: Remove this with the rework of the API - this forces search tool
        # when retrieval_options.run_search is set to ALWAYS
        if (
            retrieval_options
            and retrieval_options.run_search == OptionalSearchSetting.ALWAYS
            and search_tool_id is not None
        ):
            if new_msg_req.forced_tool_ids is None:
                new_msg_req.forced_tool_ids = [search_tool_id]
            elif search_tool_id not in new_msg_req.forced_tool_ids:
                new_msg_req.forced_tool_ids.insert(0, search_tool_id)

        emitter = get_default_emitter()

        # Construct tools based on the persona configurations
        tool_dict = construct_tools(
            persona=persona,
            db_session=db_session,
            emitter=emitter,
            user=user,
            llm=llm,
            search_tool_config=SearchToolConfig(
                user_selected_filters=user_selected_filters,
                project_id=(
                    chat_session.project_id
                    if extracted_project_files.project_as_filter
                    else None
                ),
                bypass_acl=bypass_acl,
                slack_context=slack_context,
            ),
            custom_tool_config=CustomToolConfig(
                chat_session_id=chat_session_id,
                message_id=user_message.id if user_message else None,
                additional_headers=custom_tool_additional_headers,
            ),
            allowed_tool_ids=new_msg_req.allowed_tool_ids,
            search_usage_forcing_setting=search_usage_forcing_setting,
        )
        tools: list[Tool] = []
        for tool_list in tool_dict.values():
            tools.extend(tool_list)

        # TODO Once summarization is done, we don't need to load all the files from the beginning anymore.
        # load all files needed for this chat chain in memory
        files = load_all_chat_files(chat_history, db_session)

        # TODO Need to think of some way to support selected docs from the sidebar

        # Reserve a message id for the assistant response for frontend to track packets
        assistant_response = reserve_message_id(
            db_session=db_session,
            chat_session_id=chat_session_id,
            parent_message=user_message.id,
            message_type=MessageType.ASSISTANT,
        )

        yield MessageResponseIDInfo(
            user_message_id=user_message.id,
            reserved_assistant_message_id=assistant_response.id,
        )

        # Convert the chat history into a simple format that is free of any DB objects
        # and is easy to parse for the agent loop
        simple_chat_history = convert_chat_history(
            chat_history=chat_history,
            files=files,
            project_image_files=extracted_project_files.project_image_files,
            additional_context=additional_context,
            token_counter=token_counter,
            tool_id_to_name_map=tool_id_to_name_map,
        )

        redis_client = get_redis_client()

        reset_cancel_status(
            chat_session_id,
            redis_client,
        )

        def check_is_connected() -> bool:
            return check_stop_signal(chat_session_id, redis_client)

        # Create state container for accumulating partial results
        state_container = ChatStateContainer()

        # Run the LLM loop with explicit wrapper for stop signal handling
        # The wrapper runs run_llm_loop in a background thread and polls every 300ms
        # for stop signals. run_llm_loop itself doesn't know about stopping.
        # Note: DB session is not thread safe but nothing else uses it and the
        # reference is passed directly so it's ok.
        if new_msg_req.deep_research:
            if chat_session.project_id:
                raise RuntimeError("Deep research is not supported for projects")

            # Skip clarification if the last assistant message was a clarification
            # (user has already responded to a clarification question)
            skip_clarification = is_last_assistant_message_clarification(chat_history)

            yield from run_chat_loop_with_state_containers(
                run_deep_research_llm_loop,
                is_connected=check_is_connected,
                emitter=emitter,
                state_container=state_container,
                simple_chat_history=simple_chat_history,
                tools=tools,
                custom_agent_prompt=custom_agent_prompt,
                llm=llm,
                token_counter=token_counter,
                db_session=db_session,
                skip_clarification=skip_clarification,
                user_identity=user_identity,
                chat_session_id=str(chat_session_id),
            )
        else:
            yield from run_chat_loop_with_state_containers(
                run_llm_loop,
                is_connected=check_is_connected,  # Not passed through to run_llm_loop
                emitter=emitter,
                state_container=state_container,
                simple_chat_history=simple_chat_history,
                tools=tools,
                custom_agent_prompt=custom_agent_prompt,
                project_files=extracted_project_files,
                persona=persona,
                memories=memories,
                llm=llm,
                token_counter=token_counter,
                db_session=db_session,
                forced_tool_id=(
                    new_msg_req.forced_tool_ids[0]
                    if new_msg_req.forced_tool_ids
                    else None
                ),
                user_identity=user_identity,
                chat_session_id=str(chat_session_id),
            )

        # Determine if stopped by user
        completed_normally = check_is_connected()
        if not completed_normally:
            logger.debug(f"Chat session {chat_session_id} stopped by user")

        # Build final answer based on completion status
        if completed_normally:
            if state_container.answer_tokens is None:
                raise RuntimeError(
                    "LLM run completed normally but did not return an answer."
                )
            final_answer = state_container.answer_tokens
        else:
            # Stopped by user - append stop message
            if state_container.answer_tokens:
                final_answer = (
                    state_container.answer_tokens
                    + " ... The generation was stopped by the user here."
                )
            else:
                final_answer = "The generation was stopped by the user."

        # Build citation_docs_info from accumulated citations in state container
        citation_docs_info: list[CitationDocInfo] = []
        seen_citation_nums: set[int] = set()
        for citation_num, search_doc in state_container.citation_to_doc.items():
            if citation_num not in seen_citation_nums:
                seen_citation_nums.add(citation_num)
                citation_docs_info.append(
                    CitationDocInfo(
                        search_doc=search_doc,
                        citation_number=citation_num,
                    )
                )

        save_chat_turn(
            message_text=final_answer,
            reasoning_tokens=state_container.reasoning_tokens,
            citation_docs_info=citation_docs_info,
            tool_calls=state_container.tool_calls,
            db_session=db_session,
            assistant_message=assistant_response,
            is_clarification=state_container.is_clarification,
        )

    except ValueError as e:
        logger.exception("Failed to process chat message.")

        error_msg = str(e)
        yield StreamingError(
            error=error_msg,
            error_code="VALIDATION_ERROR",
            is_retryable=True,
        )
        db_session.rollback()
        return

    except Exception as e:
        logger.exception(f"Failed to process chat message due to {e}")
        error_msg = str(e)
        stack_trace = traceback.format_exc()

        if isinstance(e, ToolCallException):
            yield StreamingError(
                error=error_msg,
                stack_trace=stack_trace,
                error_code="TOOL_CALL_FAILED",
                is_retryable=True,
                details={"tool_name": e.tool_name} if e.tool_name else None,
            )
        elif llm:
            client_error_msg, error_code, is_retryable = litellm_exception_to_error_msg(
                e, llm
            )
            if llm.config.api_key and len(llm.config.api_key) > 2:
                client_error_msg = client_error_msg.replace(
                    llm.config.api_key, "[REDACTED_API_KEY]"
                )
                stack_trace = stack_trace.replace(
                    llm.config.api_key, "[REDACTED_API_KEY]"
                )

            yield StreamingError(
                error=client_error_msg,
                stack_trace=stack_trace,
                error_code=error_code,
                is_retryable=is_retryable,
                details={
                    "model": llm.config.model_name,
                    "provider": llm.config.model_provider,
                },
            )
        else:
            # LLM was never initialized - early failure
            yield StreamingError(
                error="Failed to initialize the chat. Please check your configuration and try again.",
                stack_trace=stack_trace,
                error_code="INIT_FAILED",
                is_retryable=True,
            )

        db_session.rollback()
        return


@log_generator_function_time()
def stream_chat_message(
    new_msg_req: CreateChatMessageRequest,
    user: User | None,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
) -> Iterator[str]:
    with get_session_with_current_tenant() as db_session:
        objects = stream_chat_message_objects(
            new_msg_req=new_msg_req,
            user=user,
            db_session=db_session,
            litellm_additional_headers=litellm_additional_headers,
            custom_tool_additional_headers=custom_tool_additional_headers,
        )
        for obj in objects:
            yield get_json_line(obj.model_dump())


def remove_answer_citations(answer: str) -> str:
    pattern = r"\s*\[\[\d+\]\]\(http[s]?://[^\s]+\)"

    return re.sub(pattern, "", answer)


@log_function_time()
def gather_stream(
    packets: AnswerStream,
) -> ChatBasicResponse:
    answer: str | None = None
    citations: list[CitationInfo] = []
    error_msg: str | None = None
    message_id: int | None = None
    top_documents: list[SearchDoc] = []

    for packet in packets:
        if isinstance(packet, Packet):
            # Handle the different packet object types
            if isinstance(packet.obj, AgentResponseStart):
                # AgentResponseStart contains the final documents
                if packet.obj.final_documents:
                    top_documents = packet.obj.final_documents
            elif isinstance(packet.obj, AgentResponseDelta):
                # AgentResponseDelta contains incremental content updates
                if answer is None:
                    answer = ""
                if packet.obj.content:
                    answer += packet.obj.content
            elif isinstance(packet.obj, CitationInfo):
                # CitationInfo contains citation information
                citations.append(packet.obj)
        elif isinstance(packet, StreamingError):
            error_msg = packet.error
        elif isinstance(packet, MessageResponseIDInfo):
            message_id = packet.reserved_assistant_message_id

    if message_id is None:
        raise ValueError("Message ID is required")

    if answer is None:
        # This should never be the case as these non-streamed flows do not have a stop-generation signal
        raise RuntimeError("Answer was not generated")

    return ChatBasicResponse(
        answer=answer,
        answer_citationless=remove_answer_citations(answer),
        citation_info=citations,
        message_id=message_id,
        error_msg=error_msg,
        top_documents=top_documents,
    )
