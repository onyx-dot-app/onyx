import re
import time
import traceback
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from typing import Protocol
from uuid import UUID

from agents import Model
from agents import ModelSettings
from redis.client import Redis
from sqlalchemy.orm import Session

from onyx.agents.agent_sdk.message_types import AgentSDKMessage
from onyx.chat.chat_milestones import process_multi_assistant_milestone
from onyx.chat.chat_utils import convert_chat_history
from onyx.chat.chat_utils import create_chat_history_chain
from onyx.chat.chat_utils import create_temporary_persona
from onyx.chat.chat_utils import get_custom_agent_prompt
from onyx.chat.chat_utils import load_all_chat_files
from onyx.chat.memories import get_memories
from onyx.chat.models import AnswerStream
from onyx.chat.models import ChatBasicResponse
from onyx.chat.models import ChatLoadedFile
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ExtractedProjectFiles
from onyx.chat.models import LlmDoc
from onyx.chat.models import MessageResponseIDInfo
from onyx.chat.models import MessageSpecificCitations
from onyx.chat.models import PromptConfig
from onyx.chat.models import QADocsResponse
from onyx.chat.models import StreamingError
from onyx.chat.prompt_builder.answer_prompt_builder import calculate_reserved_tokens
from onyx.chat.turn import fast_chat_turn
from onyx.chat.turn.infra.emitter import get_default_emitter
from onyx.chat.turn.models import ChatTurnDependencies
from onyx.configs.chat_configs import CHAT_TARGET_CHUNK_PERCENTAGE
from onyx.configs.chat_configs import MAX_CHUNKS_FED_TO_CHAT
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.context.search.models import SavedSearchDoc
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_chat_message
from onyx.db.chat import get_chat_session_by_id
from onyx.db.chat import get_or_create_root_message
from onyx.db.chat import reserve_message_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ChatMessage
from onyx.db.models import Persona
from onyx.db.models import SearchDoc as DbSearchDoc
from onyx.db.models import ToolCall
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.projects import get_project_token_count
from onyx.db.projects import get_user_files_from_project
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import FileDescriptor
from onyx.file_store.models import InMemoryChatFile
from onyx.file_store.utils import build_frontend_file_url
from onyx.file_store.utils import load_in_memory_chat_files
from onyx.file_store.utils import verify_user_files
from onyx.llm.factory import get_llm_tokenizer_encode_func
from onyx.llm.factory import get_llms_for_persona
from onyx.llm.interfaces import LLM
from onyx.llm.utils import litellm_exception_to_error_msg
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.utils import get_json_line
from onyx.tools.tool import Tool
from onyx.tools.tool_constructor import construct_tools
from onyx.tools.tool_constructor import CustomToolConfig
from onyx.tools.tool_constructor import SearchToolConfig
from onyx.utils.logger import setup_logger
from onyx.utils.long_term_log import LongTermLogger
from onyx.utils.timing import log_function_time
from onyx.utils.timing import log_generator_function_time
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()
ERROR_TYPE_CANCELLED = "cancelled"


class ToolCallException(Exception):
    """Exception raised for errors during tool calls."""


class PartialResponse(Protocol):
    def __call__(
        self,
        message: str,
        rephrased_query: str | None,
        reference_docs: list[DbSearchDoc] | None,
        files: list[FileDescriptor],
        token_count: int,
        citations: dict[int, int] | None,
        error: str | None,
        tool_call: ToolCall | None,
    ) -> ChatMessage: ...


def _build_project_llm_docs(
    project_file_ids: list[str] | None,
    in_memory_user_files: list[InMemoryChatFile] | None,
) -> list[LlmDoc]:
    """Construct `LlmDoc` objects for project-scoped user files for citation flow."""
    project_llm_docs: list[LlmDoc] = []
    if not project_file_ids or not in_memory_user_files:
        return project_llm_docs

    project_file_id_set = set(project_file_ids)

    def _strip_nuls(s: str) -> str:
        return s.replace("\x00", "") if s else s

    for f in in_memory_user_files:
        if project_file_id_set and (f.file_id in project_file_id_set):
            cleaned_filename = _strip_nuls(f.filename or str(f.file_id))

            if f.file_type.is_text_file():
                try:
                    text_content = f.content.decode("utf-8", errors="ignore")
                    text_content = _strip_nuls(text_content)
                except Exception:
                    text_content = ""

                # Build a short blurb from the file content for better UI display
                blurb = (
                    (text_content[:200] + "...")
                    if len(text_content) > 200
                    else text_content
                )
            else:
                # Non-text (e.g., images): do not decode bytes; keep empty content but allow citation
                text_content = ""
                blurb = f"[{f.file_type.value}] {cleaned_filename}"

            # Provide basic metadata to improve SavedSearchDoc display
            file_metadata: dict[str, str | list[str]] = {
                "filename": cleaned_filename,
                "file_type": f.file_type.value,
            }

            project_llm_docs.append(
                LlmDoc(
                    document_id=str(f.file_id),
                    content=text_content,
                    blurb=blurb,
                    semantic_identifier=cleaned_filename,
                    source_type=DocumentSource.USER_FILE,
                    metadata=file_metadata,
                    updated_at=None,
                    link=build_frontend_file_url(str(f.file_id)),
                    source_links=None,
                    match_highlights=None,
                )
            )

    return project_llm_docs


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

    if project_tokens == 0:
        project_as_filter = True

    project_file_texts: list[str] = []
    project_image_files: list[ChatLoadedFile] = []
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
    )


def _translate_citations(
    citations_list: list[CitationInfo], db_docs: list[DbSearchDoc]
) -> MessageSpecificCitations:
    """Always cites the first instance of the document_id, assumes the db_docs
    are sorted in the order displayed in the UI"""
    doc_id_to_saved_doc_id_map: dict[str, int] = {}
    for db_doc in db_docs:
        if db_doc.document_id not in doc_id_to_saved_doc_id_map:
            doc_id_to_saved_doc_id_map[db_doc.document_id] = db_doc.id

    citation_to_saved_doc_id_map: dict[int, int] = {}
    for citation in citations_list:
        if citation.citation_number not in citation_to_saved_doc_id_map:
            citation_to_saved_doc_id_map[citation.citation_number] = (
                doc_id_to_saved_doc_id_map[citation.document_id]
            )

    return MessageSpecificCitations(citation_map=citation_to_saved_doc_id_map)


def _get_persona_for_chat_session(
    new_msg_req: CreateChatMessageRequest,
    user: User | None,
    db_session: Session,
    default_persona: Persona,
) -> Persona:
    if new_msg_req.alternate_assistant_id is not None:
        # Allows users to specify a temporary persona (assistant) in the chat session
        # this takes highest priority since it's user specified
        persona = get_persona_by_id(
            new_msg_req.alternate_assistant_id,
            user=user,
            db_session=db_session,
            is_for_edit=False,
        )
    elif new_msg_req.persona_override_config:
        # Certain endpoints allow users to specify arbitrary persona settings
        # this should never conflict with the alternate_assistant_id
        persona = create_temporary_persona(
            db_session=db_session,
            persona_config=new_msg_req.persona_override_config,
            user=user,
        )
    else:
        persona = default_persona

    if not persona:
        raise RuntimeError("No persona specified or found for chat session")
    return persona


def _initialize_chat_session(
    message_text: str,
    files: list[FileDescriptor],
    llm_tokenizer_encode_func: Callable[[str], list[int]],
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
        token_count = len(llm_tokenizer_encode_func(message_text))

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
    # a string which represents the history of a conversation. Used in cases like
    # Slack threads where the conversation cannot be represented by a chain of User/Assistant
    # messages.
    # NOTE: is not stored in the database at all.
    single_message_history: str | None = None,
) -> AnswerStream:
    tenant_id = get_current_tenant_id()
    use_existing_user_message = new_msg_req.use_existing_user_message

    llm: LLM

    try:
        user_id = user.id if user is not None else None

        chat_session = get_chat_session_by_id(
            chat_session_id=new_msg_req.chat_session_id,
            user_id=user_id,
            db_session=db_session,
        )
        persona = chat_session.persona

        message_text = new_msg_req.message
        chat_session_id = new_msg_req.chat_session_id
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
        process_multi_assistant_milestone(
            user=user,
            assistant_id=persona.id,
            tenant_id=tenant_id,
            db_session=db_session,
        )

        if reference_doc_ids is None and retrieval_options is None:
            raise RuntimeError(
                "Must specify a set of documents for chat or specify search options"
            )

        llm, fast_llm = get_llms_for_persona(
            persona=persona,
            user=user,
            llm_override=new_msg_req.llm_override or chat_session.llm_override,
            additional_headers=litellm_additional_headers,
            long_term_logger=long_term_logger,
        )
        tokenizer_encode_func = get_llm_tokenizer_encode_func(llm)

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
            llm_tokenizer_encode_func=tokenizer_encode_func,
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
            tokenizer_encode_func=tokenizer_encode_func,
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

        # There are cases where the internal search tool should be disabled
        # If the user is in a project, it should not use other sources / generic search
        # If they are in a project but using a custom agent, it should use the agent setup
        # (which means it can use search)
        # However if in a project and there are more files than can fit in the context,
        # it should use the search tool with the project filter on
        disable_internal_search = bool(
            chat_session.project_id
            and persona.id is DEFAULT_PERSONA_ID
            and (
                extracted_project_files.project_file_texts
                or not extracted_project_files.project_as_filter
            )
        )

        # Construct tools based on the persona configurations
        tool_dict = construct_tools(
            persona=persona,
            db_session=db_session,
            user=user,
            llm=llm,
            fast_llm=fast_llm,
            search_tool_config=SearchToolConfig(
                user_selected_filters=user_selected_filters,
                project_id=(
                    chat_session.project_id
                    if extracted_project_files.project_as_filter
                    else None
                ),
                bypass_acl=bypass_acl,
                slack_context=new_msg_req.slack_context,
            ),
            custom_tool_config=CustomToolConfig(
                chat_session_id=chat_session_id,
                message_id=user_message.id if user_message else None,
                additional_headers=custom_tool_additional_headers,
            ),
            allowed_tool_ids=new_msg_req.allowed_tool_ids,
            disable_internal_search=disable_internal_search,
        )
        tools: list[Tool] = []
        for tool_list in tool_dict.values():
            tools.extend(tool_list)

        # TODO Once summarization is done, we don't need to load all the files from the beginning anymore.

        # TODO There is likely a more efficient/standard way to load the files here.
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

        # TODO this may not be needed by the frontend anymore, look into removing potentially
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
        )

        yield from run_agent_loop(
            simple_chat_history=simple_chat_history,
            tools=tools,
            custom_agent_prompt=custom_agent_prompt,
            project_files=extracted_project_files,
            persona=persona,
            memories=memories,
            llm=llm,
            fast_llm=fast_llm,
            tokenizer_func=tokenizer_encode_func,
            assistant_response=assistant_response,
            db_session=db_session,
        )

    except ValueError as e:
        logger.exception("Failed to process chat message.")

        error_msg = str(e)
        yield StreamingError(error=error_msg)
        db_session.rollback()
        return

    except Exception as e:
        logger.exception(f"Failed to process chat message due to {e}")
        error_msg = str(e)
        stack_trace = traceback.format_exc()

        if isinstance(e, ToolCallException):
            yield StreamingError(error=error_msg, stack_trace=stack_trace)
        elif llm:
            client_error_msg = litellm_exception_to_error_msg(e, llm)
            if llm.config.api_key and len(llm.config.api_key) > 2:
                client_error_msg = client_error_msg.replace(
                    llm.config.api_key, "[REDACTED_API_KEY]"
                )
                stack_trace = stack_trace.replace(
                    llm.config.api_key, "[REDACTED_API_KEY]"
                )

            yield StreamingError(error=client_error_msg, stack_trace=stack_trace)

        db_session.rollback()
        return


def run_agent_loop(
    simple_chat_history: list[ChatMessageSimple],
    tools: list[Tool],
    custom_agent_prompt: str | None,
    project_files: ExtractedProjectFiles,
    persona: Persona | None,
    memories: list[str] | None,
    llm: LLM,
    fast_llm: LLM,
    tokenizer_func: Callable[[str], list[int]],
    assistant_response: ChatMessage,
    db_session: Session,
) -> Generator[Packet, None, None]:
    # # The loop should happen in between here
    # reminder_text = None

    # # The section below calculates the available tokens for history a bit more accurately
    # # now that project files are loaded in.
    # if persona.replace_base_system_prompt:
    #     system_prompt = SystemMessage(content=persona.system_prompt)
    #     custom_agent_prompt = None
    # else:
    #     system_prompt = build_system_prompt(
    #         base_system_prompt=get_default_base_system_prompt(db_session),
    #         datetime_aware=persona.datetime_aware,
    #         memories=memories,
    #         # Tools may change over iterations but for this, it's ok
    #         tools=tools,
    #         # Not that many tokens, just keep it in
    #         should_cite_documents=True,
    #     )
    #     custom_agent_prompt = SystemMessage(content=custom_agent_prompt)

    # system_prompt_token_count = len(tokenizer_func(system_prompt.content))
    # custom_agent_prompt_token_count = len(tokenizer_func(custom_agent_prompt.content)) if custom_agent_prompt else 0
    # project_token_tokens = project_files.total_token_count

    # reserved_tokens = system_prompt_token_count + custom_agent_prompt_token_count + project_token_tokens
    # available_tokens = llm.config.max_input_tokens - reserved_tokens - 200 # approximate upper bound for reminder text

    # chat_messages = construct_message_history(
    #     simple_chat_history=simple_chat_history,
    #     project_files=project_files,
    #     available_tokens=available_tokens,
    # )
    raise NotImplementedError("Not implemented")


def _fast_message_stream(
    messages: list[AgentSDKMessage],
    tools: list[Tool],
    db_session: Session,
    redis_client: Redis,
    chat_session_id: UUID,
    reserved_message_id: int,
    prompt_config: PromptConfig,
    llm_model: Model,
    llm: LLM,  # TODO remove this duplication nonsense
    model_settings: ModelSettings,
    user_or_none: User | None,
) -> Generator[Packet, None, None]:
    # TODO: clean up this jank
    # is_responses_api = isinstance(llm_model, OpenAIResponsesModel)
    # prompt_builder = answer.graph_inputs.prompt_builder
    # primary_llm = answer.graph_tooling.primary_llm
    # if prompt_builder and primary_llm:
    #     _reserve_prompt_tokens_for_agent_overhead(
    #         prompt_builder, primary_llm, tools, prompt_config
    #     )
    # messages = base_messages_to_agent_sdk_msgs(
    #     answer.graph_inputs.prompt_builder.build(), is_responses_api=is_responses_api
    # )
    emitter = get_default_emitter()
    return fast_chat_turn.fast_chat_turn(
        messages=messages,
        # TODO: Maybe we can use some DI framework here?
        dependencies=ChatTurnDependencies(
            llm_model=llm_model,
            model_settings=model_settings,
            llm=llm,
            tools=tools,
            db_session=db_session,
            redis_client=redis_client,
            emitter=emitter,
            user_or_none=user_or_none,
            prompt_config=prompt_config,
        ),
        chat_session_id=chat_session_id,
        message_id=reserved_message_id,
        prompt_config=prompt_config,
        force_use_tool=None,
    )


@log_generator_function_time()
def stream_chat_message(
    new_msg_req: CreateChatMessageRequest,
    user: User | None,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    is_connected: Callable[[], bool] | None = None,
) -> Iterator[str]:
    start_time = time.time()
    with get_session_with_current_tenant() as db_session:
        objects = stream_chat_message_objects(
            new_msg_req=new_msg_req,
            user=user,
            db_session=db_session,
            litellm_additional_headers=litellm_additional_headers,
            custom_tool_additional_headers=custom_tool_additional_headers,
            is_connected=is_connected,
        )
        for obj in objects:
            # Check if this is a QADocsResponse with document results
            if isinstance(obj, QADocsResponse):
                document_retrieval_latency = time.time() - start_time
                logger.debug(f"First doc time: {document_retrieval_latency}")

            yield get_json_line(obj.model_dump())


def remove_answer_citations(answer: str) -> str:
    pattern = r"\s*\[\[\d+\]\]\(http[s]?://[^\s]+\)"

    return re.sub(pattern, "", answer)


@log_function_time()
def gather_stream(
    packets: AnswerStream,
) -> ChatBasicResponse:
    answer = ""
    citations: list[CitationInfo] = []
    error_msg: str | None = None
    message_id: int | None = None
    top_documents: list[SavedSearchDoc] = []

    for packet in packets:
        if isinstance(packet, Packet):
            # Handle the different packet object types
            if isinstance(packet.obj, AgentResponseStart):
                # AgentResponseStart contains the final documents
                if packet.obj.final_documents:
                    top_documents = packet.obj.final_documents
            elif isinstance(packet.obj, AgentResponseDelta):
                # AgentResponseDelta contains incremental content updates
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

    return ChatBasicResponse(
        answer=answer,
        answer_citationless=remove_answer_citations(answer),
        cited_documents={
            citation.citation_number: citation.document_id for citation in citations
        },
        message_id=message_id,
        error_msg=error_msg,
        top_documents=top_documents,
    )
