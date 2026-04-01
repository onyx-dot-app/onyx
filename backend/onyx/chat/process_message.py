"""
IMPORTANT: familiarize yourself with the design concepts prior to contributing to this file.
An overview can be found in the README.md file in this directory.
"""

import contextvars
import functools
import io
import queue
import re
import threading
import traceback
from collections.abc import Callable
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextvars import Token
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import set_processing_status
from onyx.chat.chat_state import AvailableFiles
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_state import ChatTurnSetup
from onyx.chat.chat_utils import build_file_context
from onyx.chat.chat_utils import convert_chat_history
from onyx.chat.chat_utils import create_chat_history_chain
from onyx.chat.chat_utils import create_chat_session_from_request
from onyx.chat.chat_utils import get_custom_agent_prompt
from onyx.chat.chat_utils import is_last_assistant_message_clarification
from onyx.chat.chat_utils import load_all_chat_files
from onyx.chat.compression import calculate_total_history_tokens
from onyx.chat.compression import compress_chat_history
from onyx.chat.compression import find_summary_for_branch
from onyx.chat.compression import get_compression_params
from onyx.chat.emitter import Emitter
from onyx.chat.llm_loop import EmptyLLMResponseError
from onyx.chat.llm_loop import run_llm_loop
from onyx.chat.models import AnswerStream
from onyx.chat.models import AnswerStreamPart
from onyx.chat.models import ChatBasicResponse
from onyx.chat.models import ChatFullResponse
from onyx.chat.models import ChatLoadedFile
from onyx.chat.models import ChatMessageSimple
from onyx.chat.models import ContextFileMetadata
from onyx.chat.models import CreateChatSessionID
from onyx.chat.models import ExtractedContextFiles
from onyx.chat.models import FileToolMetadata
from onyx.chat.models import SearchParams
from onyx.chat.models import StreamingError
from onyx.chat.models import ToolCallResponse
from onyx.chat.prompt_utils import calculate_reserved_tokens
from onyx.chat.save_chat import save_chat_turn
from onyx.chat.stop_signal_checker import is_connected as check_stop_signal
from onyx.chat.stop_signal_checker import reset_cancel_status
from onyx.configs.app_configs import DISABLE_VECTOR_DB
from onyx.configs.app_configs import INTEGRATION_TESTS_MODE
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.configs.constants import MilestoneRecordType
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import SearchDoc
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_chat_session_by_id
from onyx.db.chat import get_or_create_root_message
from onyx.db.chat import reserve_message_id
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import HookPoint
from onyx.db.memory import get_memories
from onyx.db.memory import UserMemoryContext
from onyx.db.models import ChatMessage
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.projects import get_user_files_from_project
from onyx.db.tools import get_tools
from onyx.deep_research.dr_loop import run_deep_research_llm_loop
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import log_onyx_error
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_store.models import ChatFileType
from onyx.file_store.models import InMemoryChatFile
from onyx.file_store.utils import load_in_memory_chat_files
from onyx.file_store.utils import verify_user_files
from onyx.hooks.executor import execute_hook
from onyx.hooks.executor import HookSkipped
from onyx.hooks.executor import HookSoftFailed
from onyx.hooks.points.query_processing import QueryProcessingPayload
from onyx.hooks.points.query_processing import QueryProcessingResponse
from onyx.llm.factory import get_llm_for_persona
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.request_context import reset_llm_mock_response
from onyx.llm.request_context import set_llm_mock_response
from onyx.llm.utils import litellm_exception_to_error_msg
from onyx.onyxbot.slack.models import SlackContext
from onyx.server.query_and_chat.chat_utils import mime_type_to_chat_file_type
from onyx.server.query_and_chat.models import AUTO_PLACE_AFTER_LATEST_MESSAGE
from onyx.server.query_and_chat.models import MessageResponseIDInfo
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import AgentResponseDelta
from onyx.server.query_and_chat.streaming_models import AgentResponseStart
from onyx.server.query_and_chat.streaming_models import CitationInfo
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.usage_limits import check_llm_cost_limit_for_provider
from onyx.tools.constants import FILE_READER_TOOL_ID
from onyx.tools.constants import SEARCH_TOOL_ID
from onyx.tools.models import ChatFile
from onyx.tools.models import SearchToolUsage
from onyx.tools.tool_constructor import construct_tools
from onyx.tools.tool_constructor import CustomToolConfig
from onyx.tools.tool_constructor import FileReaderToolConfig
from onyx.tools.tool_constructor import SearchToolConfig
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import mt_cloud_telemetry
from onyx.utils.threadpool_concurrency import run_multiple_in_background
from onyx.utils.timing import log_function_time
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()
ERROR_TYPE_CANCELLED = "cancelled"

APPROX_CHARS_PER_TOKEN = 4


def _collect_available_file_ids(
    chat_history: list[ChatMessage],
    project_id: int | None,
    user_id: UUID | None,
    db_session: Session,
) -> AvailableFiles:
    """Collect all file IDs the FileReaderTool should be allowed to access.

    Returns *separate* lists for chat-attached files (``file_record`` IDs) and
    project/user files (``user_file`` IDs) so the tool can pick the right
    loader without a try/except fallback."""
    chat_file_ids: set[UUID] = set()
    user_file_ids: set[UUID] = set()

    for msg in chat_history:
        if not msg.files:
            continue
        for fd in msg.files:
            try:
                chat_file_ids.add(UUID(fd["id"]))
            except (ValueError, KeyError):
                pass

    if project_id:
        user_files = get_user_files_from_project(
            project_id=project_id,
            user_id=user_id,
            db_session=db_session,
        )
        for uf in user_files:
            user_file_ids.add(uf.id)

    return AvailableFiles(
        user_file_ids=list(user_file_ids),
        chat_file_ids=list(chat_file_ids),
    )


def _should_enable_slack_search(
    persona: Persona,
    filters: BaseFilters | None,
) -> bool:
    """Determine if Slack search should be enabled.

    Returns True if:
    - Source type filter exists and includes Slack, OR
    - Default persona with no source type filter
    """
    source_types = filters.source_type if filters else None
    return (source_types is not None and DocumentSource.SLACK in source_types) or (
        persona.id == DEFAULT_PERSONA_ID and source_types is None
    )


def _convert_loaded_files_to_chat_files(
    loaded_files: list[ChatLoadedFile],
) -> list[ChatFile]:
    """Convert ChatLoadedFile objects to ChatFile for tool usage (e.g., PythonTool).

    Args:
        loaded_files: List of ChatLoadedFile objects from the chat history

    Returns:
        List of ChatFile objects that can be passed to tools
    """
    chat_files = []
    for loaded_file in loaded_files:
        if len(loaded_file.content) > 0:
            chat_files.append(
                ChatFile(
                    filename=loaded_file.filename or f"file_{loaded_file.file_id}",
                    content=loaded_file.content,
                )
            )
    return chat_files


def resolve_context_user_files(
    persona: Persona,
    project_id: int | None,
    user_id: UUID | None,
    db_session: Session,
) -> list[UserFile]:
    """Apply the precedence rule to decide which user files to load.

    A custom persona fully supersedes the project.  When a chat uses a
    custom persona, the project is purely organisational — its files are
    never loaded and never made searchable.

    Custom persona → persona's own user_files (may be empty).
    Default persona inside a project → project files.
    Otherwise → empty list.
    """
    if persona.id != DEFAULT_PERSONA_ID:
        return list(persona.user_files) if persona.user_files else []
    if project_id:
        return get_user_files_from_project(
            project_id=project_id,
            user_id=user_id,
            db_session=db_session,
        )
    return []


def _empty_extracted_context_files() -> ExtractedContextFiles:
    return ExtractedContextFiles(
        file_texts=[],
        image_files=[],
        use_as_search_filter=False,
        total_token_count=0,
        file_metadata=[],
        uncapped_token_count=None,
    )


def _extract_text_from_in_memory_file(f: InMemoryChatFile) -> str | None:
    """Extract text content from an InMemoryChatFile.

    PLAIN_TEXT: the content is pre-extracted UTF-8 plaintext stored during
    ingestion — decode directly.
    DOC / CSV / other text types: the content is the original file bytes —
    use extract_file_text which handles encoding detection and format parsing.
    """
    try:
        if f.file_type == ChatFileType.PLAIN_TEXT:
            return f.content.decode("utf-8", errors="ignore").replace("\x00", "")
        return extract_file_text(
            file=io.BytesIO(f.content),
            file_name=f.filename or "",
            break_on_unprocessable=False,
        )
    except Exception:
        logger.warning(f"Failed to extract text from file {f.file_id}", exc_info=True)
        return None


def extract_context_files(
    user_files: list[UserFile],
    llm_max_context_window: int,
    reserved_token_count: int,
    db_session: Session,
    # Because the tokenizer is a generic tokenizer, the token count may be incorrect.
    # to account for this, the maximum context that is allowed for this function is
    # 60% of the LLM's max context window. The other benefit is that for projects with
    # more files, this makes it so that we don't throw away the history too quickly every time.
    max_llm_context_percentage: float = 0.6,
) -> ExtractedContextFiles:
    """Load user files into context if they fit; otherwise flag for search.

    The caller is responsible for deciding *which* user files to pass in
    (project files, persona files, etc.).  This function only cares about
    the all-or-nothing fit check and the actual content loading.

    Args:
        project_id: The project ID to load files from
        user_id: The user ID for authorization
        llm_max_context_window: Maximum tokens allowed in the LLM context window
        reserved_token_count: Number of tokens to reserve for other content
        db_session: Database session
        max_llm_context_percentage: Maximum percentage of the LLM context window to use.
    Returns:
        ExtractedContextFiles containing:
        - List of text content strings from context files (text files only)
        - List of image files from context (ChatLoadedFile objects)
        - Total token count of all extracted files
        - File metadata for context files
        - Uncapped token count of all extracted files
        - File metadata for files that don't fit in context and vector DB is disabled
    """
    # TODO(yuhong): I believe this is not handling all file types correctly.

    if not user_files:
        return _empty_extracted_context_files()

    # Aggregate tokens for the file content that will be added
    # Skip tokens for those with metadata only
    aggregate_tokens = sum(
        uf.token_count or 0 for uf in user_files if not mime_type_to_chat_file_type(uf.file_type).use_metadata_only()
    )
    max_actual_tokens = (llm_max_context_window - reserved_token_count) * max_llm_context_percentage

    if aggregate_tokens >= max_actual_tokens:
        use_as_search_filter = not DISABLE_VECTOR_DB
        if DISABLE_VECTOR_DB:
            overflow_tool_metadata = [_build_tool_metadata(uf) for uf in user_files]
        else:
            overflow_tool_metadata = [
                _build_tool_metadata(uf) for uf in user_files if mime_type_to_chat_file_type(uf.file_type).use_metadata_only()
            ]
        return ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=use_as_search_filter,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=aggregate_tokens,
            file_metadata_for_tool=overflow_tool_metadata,
        )

    # Files fit — load them into context
    user_file_map = {uf.file_id: uf for uf in user_files}
    in_memory_files = load_in_memory_chat_files(
        user_file_ids=[uf.id for uf in user_files],
        db_session=db_session,
    )

    file_texts: list[str] = []
    image_files: list[ChatLoadedFile] = []
    file_metadata: list[ContextFileMetadata] = []
    tool_metadata: list[FileToolMetadata] = []
    total_token_count = 0

    for f in in_memory_files:
        uf = user_file_map.get(str(f.file_id))
        filename = f.filename or f"file_{f.file_id}"

        if f.file_type.use_metadata_only():
            # Metadata-only files are not injected as full text.
            # Only the metadata is provided, with LLM using tools
            if not uf:
                logger.error(f"File with id={f.file_id} in metadata-only path with no associated user file")
                continue
            tool_metadata.append(_build_tool_metadata(uf))
        elif f.file_type.is_text_file():
            text_content = _extract_text_from_in_memory_file(f)
            if not text_content:
                continue
            if not uf:
                logger.warning(f"No user file for file_id={f.file_id}")
                continue
            file_texts.append(text_content)
            file_metadata.append(
                ContextFileMetadata(
                    file_id=str(uf.id),
                    filename=filename,
                    file_content=text_content,
                )
            )
            if uf.token_count:
                total_token_count += uf.token_count
        elif f.file_type == ChatFileType.IMAGE:
            token_count = uf.token_count if uf and uf.token_count else 0
            total_token_count += token_count
            image_files.append(
                ChatLoadedFile(
                    file_id=f.file_id,
                    content=f.content,
                    file_type=f.file_type,
                    filename=f.filename,
                    content_text=None,
                    token_count=token_count,
                )
            )

    return ExtractedContextFiles(
        file_texts=file_texts,
        image_files=image_files,
        use_as_search_filter=False,
        total_token_count=total_token_count,
        file_metadata=file_metadata,
        uncapped_token_count=aggregate_tokens,
        file_metadata_for_tool=tool_metadata,
    )


def _build_tool_metadata(user_file: UserFile) -> FileToolMetadata:
    """Build lightweight FileToolMetadata from a UserFile record.

    Delegates to ``build_file_context`` so that the file ID exposed to the
    LLM is always consistent with what FileReaderTool expects.
    """
    return build_file_context(
        tool_file_id=str(user_file.id),
        filename=user_file.name,
        file_type=mime_type_to_chat_file_type(user_file.file_type),
        approx_char_count=(user_file.token_count or 0) * APPROX_CHARS_PER_TOKEN,
    ).tool_metadata


def determine_search_params(
    persona_id: int,
    project_id: int | None,
    extracted_context_files: ExtractedContextFiles,
) -> SearchParams:
    """Decide which search filter IDs and search-tool usage apply for a chat turn.

    A custom persona fully supersedes the project — project files are never
    searchable and the search tool config is entirely controlled by the
    persona.  The project_id filter is only set for the default persona.

    For the default persona inside a project:
      - Files overflow  → ENABLED  (vector DB scopes to these files)
      - Files fit       → DISABLED (content already in prompt)
      - No files at all → DISABLED (nothing to search)
    """
    is_custom_persona = persona_id != DEFAULT_PERSONA_ID

    project_id_filter: int | None = None
    persona_id_filter: int | None = None
    if extracted_context_files.use_as_search_filter:
        if is_custom_persona:
            persona_id_filter = persona_id
        else:
            project_id_filter = project_id

    search_usage = SearchToolUsage.AUTO
    if not is_custom_persona and project_id:
        has_context_files = bool(extracted_context_files.uncapped_token_count)
        files_loaded_in_context = bool(extracted_context_files.file_texts)

        if extracted_context_files.use_as_search_filter:
            search_usage = SearchToolUsage.ENABLED
        elif files_loaded_in_context or not has_context_files:
            search_usage = SearchToolUsage.DISABLED

    return SearchParams(
        project_id_filter=project_id_filter,
        persona_id_filter=persona_id_filter,
        search_usage=search_usage,
    )


def _resolve_query_processing_hook_result(
    hook_result: QueryProcessingResponse | HookSkipped | HookSoftFailed,
    message_text: str,
) -> str:
    """Apply the Query Processing hook result to the message text.

    Returns the (possibly rewritten) message text, or raises OnyxError with
    QUERY_REJECTED if the hook signals rejection (query is null or empty).
    HookSkipped and HookSoftFailed are pass-throughs — the original text is
    returned unchanged.
    """
    if isinstance(hook_result, (HookSkipped, HookSoftFailed)):
        return message_text
    if not (hook_result.query and hook_result.query.strip()):
        raise OnyxError(
            OnyxErrorCode.QUERY_REJECTED,
            hook_result.rejection_message
            or "The hook extension for query processing did not return a valid query. No rejection reason was provided.",
        )
    return hook_result.query.strip()


def build_chat_turn(
    new_msg_req: SendMessageRequest,
    user: User,
    db_session: Session,
    *,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    bypass_acl: bool = False,
    # Slack context for federated Slack search
    slack_context: SlackContext | None = None,
    # Additional context to include in the chat history, e.g. Slack threads where the
    # conversation cannot be represented by a chain of User/Assistant messages.
    # NOTE: not stored in the database, only passed in to the LLM as context
    additional_context: str | None = None,
) -> Generator[AnswerStreamPart, None, ChatTurnSetup]:
    """Setup generator for a single-model chat turn.

    Yields the packet(s) the frontend needs for request tracking, then returns an
    immutable ``ChatTurnSetup`` containing everything the execution strategy needs.

    Callers use::

        setup = yield from build_chat_turn(new_msg_req, ...)

    to forward yielded packets upstream while receiving the return value locally.
    """
    tenant_id = get_current_tenant_id()

    user_id = user.id
    llm_user_identifier = "anonymous_user" if user.is_anonymous else (user.email or str(user_id))

    # ── Session resolution ───────────────────────────────────────────────────
    if not new_msg_req.chat_session_id:
        if not new_msg_req.chat_session_info:
            raise RuntimeError("Must specify a chat session id or chat session info")
        chat_session = create_chat_session_from_request(
            chat_session_request=new_msg_req.chat_session_info,
            user_id=user_id,
            db_session=db_session,
        )
        yield CreateChatSessionID(chat_session_id=chat_session.id)
        chat_session = get_chat_session_by_id(
            chat_session_id=chat_session.id,
            user_id=user_id,
            db_session=db_session,
            eager_load_persona=True,
        )
    else:
        chat_session = get_chat_session_by_id(
            chat_session_id=new_msg_req.chat_session_id,
            user_id=user_id,
            db_session=db_session,
            eager_load_persona=True,
        )

    persona = chat_session.persona
    message_text = new_msg_req.message

    user_identity = LLMUserIdentity(user_id=llm_user_identifier, session_id=str(chat_session.id))

    # Milestone tracking, most devs using the API don't need to understand this
    mt_cloud_telemetry(
        tenant_id=tenant_id,
        distinct_id=str(user.id) if not user.is_anonymous else tenant_id,
        event=MilestoneRecordType.MULTIPLE_ASSISTANTS,
    )
    mt_cloud_telemetry(
        tenant_id=tenant_id,
        distinct_id=str(user.id) if not user.is_anonymous else tenant_id,
        event=MilestoneRecordType.USER_MESSAGE_SENT,
        properties={
            "origin": new_msg_req.origin.value,
            "has_files": len(new_msg_req.file_descriptors) > 0,
            "has_project": chat_session.project_id is not None,
            "has_persona": persona is not None and persona.id != DEFAULT_PERSONA_ID,
            "deep_research": new_msg_req.deep_research,
        },
    )

    # Check LLM cost limits before using the LLM (only for Onyx-managed keys),
    # then build the LLM instance.
    primary_llm = get_llm_for_persona(
        persona=persona,
        user=user,
        llm_override=new_msg_req.llm_override or chat_session.llm_override,
        additional_headers=litellm_additional_headers,
    )
    check_llm_cost_limit_for_provider(
        db_session=db_session,
        tenant_id=tenant_id,
        llm_provider_api_key=primary_llm.config.api_key,
    )
    llms = [primary_llm]
    model_display_names = [""]
    token_counter = get_llm_token_counter(primary_llm)

    # Verify that the user-specified files actually belong to the user
    verify_user_files(
        user_files=new_msg_req.file_descriptors,
        user_id=user_id,
        db_session=db_session,
        project_id=chat_session.project_id,
    )

    # Re-create linear history of messages
    chat_history = create_chat_history_chain(chat_session_id=chat_session.id, db_session=db_session)

    # Determine the parent message based on the request:
    # - AUTO_PLACE_AFTER_LATEST_MESSAGE (-1): auto-place after latest message in chain
    # - None or root ID: regeneration from root (first message)
    # - positive int: place after that specific parent message
    root_message = get_or_create_root_message(chat_session_id=chat_session.id, db_session=db_session)

    if new_msg_req.parent_message_id == AUTO_PLACE_AFTER_LATEST_MESSAGE:
        parent_message = chat_history[-1] if chat_history else root_message
    elif new_msg_req.parent_message_id is None or new_msg_req.parent_message_id == root_message.id:
        # Regeneration from root — clear history so we start fresh
        parent_message = root_message
        chat_history = []
    else:
        parent_message = None
        for i in range(len(chat_history) - 1, -1, -1):
            if chat_history[i].id == new_msg_req.parent_message_id:
                parent_message = chat_history[i]
                # Truncate to only messages up to and including the parent
                chat_history = chat_history[: i + 1]
                break

    if parent_message is None:
        raise ValueError("The new message sent is not on the latest mainline of messages")

    # ── Query Processing hook + user message ─────────────────────────────────
    # Skipped on regeneration (parent is USER type): message already exists/was accepted.
    if parent_message.message_type == MessageType.USER:
        user_message = parent_message
    else:
        # New message — run the Query Processing hook before saving to DB.
        # Skipped on regeneration: the message already exists and was accepted previously.
        # Skip for empty/whitespace-only messages — no meaningful query to process,
        # and SendMessageRequest.message has no min_length guard.
        if message_text.strip():
            hook_result = execute_hook(
                db_session=db_session,
                hook_point=HookPoint.QUERY_PROCESSING,
                payload=QueryProcessingPayload(
                    query=message_text,
                    # Pass None for anonymous users or authenticated users without an email
                    # (e.g. some SSO flows). QueryProcessingPayload.user_email is str | None,
                    # so None is accepted and serialised as null in both cases.
                    user_email=None if user.is_anonymous else user.email,
                    chat_session_id=str(chat_session.id),
                ).model_dump(),
                response_type=QueryProcessingResponse,
            )
            message_text = _resolve_query_processing_hook_result(hook_result, message_text)

        user_message = create_new_chat_message(
            chat_session_id=chat_session.id,
            parent_message=parent_message,
            message=message_text,
            token_count=token_counter(message_text),
            message_type=MessageType.USER,
            files=new_msg_req.file_descriptors,
            db_session=db_session,
            commit=True,
        )
        chat_history.append(user_message)

    # Collect file IDs for the file reader tool *before* summary truncation so
    # that files attached to older (summarized-away) messages are still accessible
    # via the FileReaderTool.
    available_files = _collect_available_file_ids(
        chat_history=chat_history,
        project_id=chat_session.project_id,
        user_id=user_id,
        db_session=db_session,
    )

    # Find applicable summary for the current branch
    summary_message = find_summary_for_branch(db_session, chat_history)
    # Collect file metadata from messages that will be dropped by summary truncation.
    # These become "pre-summarized" file metadata so the forgotten-file mechanism can
    # still tell the LLM about them.
    summarized_file_metadata: dict[str, FileToolMetadata] = {}
    if summary_message and summary_message.last_summarized_message_id:
        cutoff_id = summary_message.last_summarized_message_id
        for msg in chat_history:
            if msg.id > cutoff_id or not msg.files:
                continue
            for fd in msg.files:
                file_id = fd.get("id")
                if not file_id:
                    continue
                summarized_file_metadata[file_id] = FileToolMetadata(
                    file_id=file_id,
                    filename=fd.get("name") or "unknown",
                    # We don't know the exact size without loading the file,
                    # but 0 signals "unknown" to the LLM.
                    approx_char_count=0,
                )
        # Filter chat_history to only messages after the cutoff
        chat_history = [m for m in chat_history if m.id > cutoff_id]

    # Compute skip-clarification flag for deep research path (cheap, always available)
    skip_clarification = is_last_assistant_message_clarification(chat_history)

    user_memory_context = get_memories(user, db_session)

    # This prompt may come from the Agent or Project. Fetched here (before run_llm_loop)
    # because the inner loop shouldn't need to access the DB-form chat history, but we
    # need it early for token reservation.
    custom_agent_prompt = get_custom_agent_prompt(persona, chat_session)

    # When use_memories is disabled, strip memories from the prompt context but keep
    # user info/preferences. The full context is still passed to the LLM loop for
    # memory tool persistence.
    prompt_memory_context = user_memory_context if user.use_memories else user_memory_context.without_memories()

    # ── Token reservation ────────────────────────────────────────────────────
    max_reserved_system_prompt_tokens_str = (persona.system_prompt or "") + (custom_agent_prompt or "")
    reserved_token_count = calculate_reserved_tokens(
        db_session=db_session,
        persona_system_prompt=max_reserved_system_prompt_tokens_str,
        token_counter=token_counter,
        files=new_msg_req.file_descriptors,
        user_memory_context=prompt_memory_context,
    )

    # Determine which user files to use. A custom persona fully supersedes the project —
    # project files are never loaded or searchable when a custom persona is in play.
    # Only the default persona inside a project uses the project's files.
    context_user_files = resolve_context_user_files(
        persona=persona,
        project_id=chat_session.project_id,
        user_id=user_id,
        db_session=db_session,
    )

    llm_max_context_window = llms[0].config.max_input_tokens

    extracted_context_files = extract_context_files(
        user_files=context_user_files,
        llm_max_context_window=llm_max_context_window,
        reserved_token_count=reserved_token_count,
        db_session=db_session,
    )

    search_params = determine_search_params(
        persona_id=persona.id,
        project_id=chat_session.project_id,
        extracted_context_files=extracted_context_files,
    )

    # Also grant access to persona-attached user files for FileReaderTool
    if persona.user_files:
        existing = set(available_files.user_file_ids)
        for uf in persona.user_files:
            if uf.id not in existing:
                available_files.user_file_ids.append(uf.id)

    all_tools = get_tools(db_session)
    tool_id_to_name_map = {tool.id: tool.name for tool in all_tools}

    search_tool_id = next((tool.id for tool in all_tools if tool.in_code_tool_id == SEARCH_TOOL_ID), None)

    forced_tool_id = new_msg_req.forced_tool_id
    if (
        search_params.search_usage == SearchToolUsage.DISABLED
        and forced_tool_id is not None
        and search_tool_id is not None
        and forced_tool_id == search_tool_id
    ):
        forced_tool_id = None

    # TODO(nmgarza5): Once summarization is done, we don't need to load all files from the beginning.
    # Load all files needed for this chat chain into memory.
    files = load_all_chat_files(chat_history, db_session)
    # Convert loaded files to ChatFile format for tools like PythonTool
    chat_files_for_tools = _convert_loaded_files_to_chat_files(files)

    # ── Reserve assistant message ID → yield to frontend ─────────────────────
    assistant_response = reserve_message_id(
        db_session=db_session,
        chat_session_id=chat_session.id,
        parent_message=user_message.id,
        message_type=MessageType.ASSISTANT,
    )
    reserved_messages = [assistant_response]
    yield MessageResponseIDInfo(
        user_message_id=user_message.id,
        reserved_assistant_message_id=assistant_response.id,
    )

    # Convert the chat history into a simple format that is free of any DB objects
    # and is easy to parse for the agent loop.
    has_file_reader_tool = any(tool.in_code_tool_id == FILE_READER_TOOL_ID for tool in persona.tools)

    chat_history_result = convert_chat_history(
        chat_history=chat_history,
        files=files,
        context_image_files=extracted_context_files.image_files,
        additional_context=additional_context or new_msg_req.additional_context,
        token_counter=token_counter,
        tool_id_to_name_map=tool_id_to_name_map,
    )
    simple_chat_history = chat_history_result.simple_messages

    # Metadata for every text file injected into the history. After context-window
    # truncation drops older messages, the LLM loop compares surviving file_id tags
    # against this map to discover "forgotten" files and provide their metadata to
    # FileReaderTool.
    all_injected_file_metadata: dict[str, FileToolMetadata] = (
        chat_history_result.all_injected_file_metadata if has_file_reader_tool else {}
    )

    # Merge in file metadata from messages dropped by summary truncation. These files
    # are no longer in simple_chat_history so they'd be invisible to the forgotten-file
    # mechanism — they'll always appear as "forgotten" since no surviving message carries
    # their file_id tag.
    if summarized_file_metadata:
        for fid, meta in summarized_file_metadata.items():
            all_injected_file_metadata.setdefault(fid, meta)

    if all_injected_file_metadata:
        logger.debug(f"FileReader: file metadata for LLM: {[(fid, m.filename) for fid, m in all_injected_file_metadata.items()]}")

    if summary_message is not None:
        summary_simple = ChatMessageSimple(
            message=summary_message.message,
            token_count=summary_message.token_count,
            message_type=MessageType.ASSISTANT,
        )
        simple_chat_history.insert(0, summary_simple)

    # ── Stop signal and processing status ────────────────────────────────────
    cache = get_cache_backend()
    reset_cancel_status(chat_session.id, cache)

    def check_is_connected() -> bool:
        return check_stop_signal(chat_session.id, cache)

    set_processing_status(
        chat_session_id=chat_session.id,
        cache=cache,
        value=True,
    )

    # Release any read transaction before the long-running LLM stream.
    # If commit fails here, reset the processing status before propagating —
    # otherwise the chat session appears stuck at "processing" permanently.
    try:
        db_session.commit()
    except Exception:
        set_processing_status(chat_session_id=chat_session.id, cache=cache, value=False)
        raise

    return ChatTurnSetup(
        new_msg_req=new_msg_req,
        chat_session=chat_session,
        persona=persona,
        user_message=user_message,
        user_identity=user_identity,
        llms=llms,
        model_display_names=model_display_names,
        simple_chat_history=simple_chat_history,
        extracted_context_files=extracted_context_files,
        reserved_messages=reserved_messages,
        reserved_token_count=reserved_token_count,
        search_params=search_params,
        all_injected_file_metadata=all_injected_file_metadata,
        available_files=available_files,
        tool_id_to_name_map=tool_id_to_name_map,
        forced_tool_id=forced_tool_id,
        files=files,
        chat_files_for_tools=chat_files_for_tools,
        custom_agent_prompt=custom_agent_prompt,
        user_memory_context=user_memory_context,
        skip_clarification=skip_clarification,
        check_is_connected=check_is_connected,
        cache=cache,
        bypass_acl=bypass_acl,
        slack_context=slack_context,
        custom_tool_additional_headers=custom_tool_additional_headers,
        mcp_headers=mcp_headers,
    )


# Sentinel placed on the merged queue when a model thread finishes.
_MODEL_DONE = object()


def _run_models(
    setup: ChatTurnSetup,
    user: User,
    db_session: Session,
    external_state_container: ChatStateContainer | None = None,
) -> AnswerStream:
    """Stream packets from one or more LLM loops running in parallel worker threads.

    Each model gets its own worker thread, DB session, and ``Emitter``. Threads write
    packets to a shared bounded queue as they are produced; the drain loop yields them
    in arrival order so the caller receives a single interleaved stream regardless of
    how many models are running.

    Single-model (N=1) and multi-model (N>1) use the same execution path. Every
    packet is tagged with ``model_index`` by the model's Emitter — ``0`` for N=1,
    ``0``/``1``/``2`` for multi-model.

    Args:
        setup: Fully constructed turn context — LLMs, persona, history, tool config.
        user: Authenticated user making the request.
        db_session: Caller's DB session (used for setup reads; each worker opens its own
            session because SQLAlchemy sessions are not thread-safe).
        external_state_container: Pre-constructed state container for the first model.
            Used by evals and the non-streaming API path so the caller can inspect
            accumulated state (tool calls, answer tokens, citations) after the stream
            is consumed. When ``None`` a fresh container is created automatically.

    Returns:
        Generator yielding ``Packet`` objects as they arrive from worker threads —
        answer tokens, tool output, citations — followed by a terminal ``Packet``
        containing ``OverallStop`` once all models complete (or one containing
        ``OverallStop(stop_reason="user_cancelled")`` if the connection drops).
    """
    n_models = len(setup.llms)

    merged_queue: queue.Queue[tuple[int, Packet | Exception | object]] = queue.Queue()

    state_containers: list[ChatStateContainer] = [
        (external_state_container if (external_state_container is not None and i == 0) else ChatStateContainer())
        for i in range(n_models)
    ]
    model_succeeded: list[bool] = [False] * n_models

    # Set when the drain loop exits early (HTTP disconnect / GeneratorExit).
    # Signals emitters to skip future puts and workers to self-complete.
    drain_done = threading.Event()

    def _run_model(model_idx: int) -> None:
        """Run one LLM loop inside a worker thread, writing packets to ``merged_queue``."""
        model_emitter = Emitter(
            model_idx=model_idx,
            merged_queue=merged_queue,
            drain_done=drain_done,
        )
        sc = state_containers[model_idx]
        model_llm = setup.llms[model_idx]

        try:
            # Each worker opens its own session — SQLAlchemy sessions are not thread-safe.
            # Do NOT write to the outer db_session (or any shared DB state) from here;
            # all DB writes in this thread must go through thread_db_session.
            with get_session_with_current_tenant() as thread_db_session:
                thread_tool_dict = construct_tools(
                    persona=setup.persona,
                    db_session=thread_db_session,
                    emitter=model_emitter,
                    user=user,
                    llm=model_llm,
                    search_tool_config=SearchToolConfig(
                        user_selected_filters=setup.new_msg_req.internal_search_filters,
                        project_id_filter=setup.search_params.project_id_filter,
                        persona_id_filter=setup.search_params.persona_id_filter,
                        bypass_acl=setup.bypass_acl,
                        slack_context=setup.slack_context,
                        enable_slack_search=_should_enable_slack_search(setup.persona, setup.new_msg_req.internal_search_filters),
                    ),
                    custom_tool_config=CustomToolConfig(
                        chat_session_id=setup.chat_session.id,
                        message_id=setup.user_message.id,
                        additional_headers=setup.custom_tool_additional_headers,
                        mcp_headers=setup.mcp_headers,
                    ),
                    file_reader_tool_config=FileReaderToolConfig(
                        user_file_ids=setup.available_files.user_file_ids,
                        chat_file_ids=setup.available_files.chat_file_ids,
                    ),
                    allowed_tool_ids=setup.new_msg_req.allowed_tool_ids,
                    search_usage_forcing_setting=setup.search_params.search_usage,
                )
                model_tools = [tool for tool_list in thread_tool_dict.values() for tool in tool_list]

                if setup.forced_tool_id and setup.forced_tool_id not in {tool.id for tool in model_tools}:
                    raise ValueError(f"Forced tool {setup.forced_tool_id} not found in tools")

                # Per-thread copy: run_llm_loop mutates simple_chat_history in-place.
                if n_models == 1 and setup.new_msg_req.deep_research:
                    if setup.chat_session.project_id:
                        raise RuntimeError("Deep research is not supported for projects")
                    run_deep_research_llm_loop(
                        emitter=model_emitter,
                        state_container=sc,
                        simple_chat_history=list(setup.simple_chat_history),
                        tools=model_tools,
                        custom_agent_prompt=setup.custom_agent_prompt,
                        llm=model_llm,
                        token_counter=get_llm_token_counter(model_llm),
                        db_session=thread_db_session,
                        skip_clarification=setup.skip_clarification,
                        user_identity=setup.user_identity,
                        chat_session_id=str(setup.chat_session.id),
                        all_injected_file_metadata=setup.all_injected_file_metadata,
                    )
                else:
                    run_llm_loop(
                        emitter=model_emitter,
                        state_container=sc,
                        simple_chat_history=list(setup.simple_chat_history),
                        tools=model_tools,
                        custom_agent_prompt=setup.custom_agent_prompt,
                        context_files=setup.extracted_context_files,
                        persona=setup.persona,
                        user_memory_context=setup.user_memory_context,
                        llm=model_llm,
                        token_counter=get_llm_token_counter(model_llm),
                        db_session=thread_db_session,
                        forced_tool_id=setup.forced_tool_id,
                        user_identity=setup.user_identity,
                        chat_session_id=str(setup.chat_session.id),
                        chat_files=setup.chat_files_for_tools,
                        include_citations=setup.new_msg_req.include_citations,
                        all_injected_file_metadata=setup.all_injected_file_metadata,
                        inject_memories_in_prompt=user.use_memories,
                    )

            model_succeeded[model_idx] = True

        except Exception as e:
            merged_queue.put((model_idx, e))

        finally:
            merged_queue.put((model_idx, _MODEL_DONE))

        # Self-completion on disconnect: if the drain loop exited early (drain_done is set),
        # the main thread will not call llm_loop_completion_handle for this model.
        # Open a fresh session and do it here so the response is persisted.
        if drain_done.is_set() and model_succeeded[model_idx]:
            try:
                with get_session_with_current_tenant() as self_complete_db:
                    assistant_message = self_complete_db.get(ChatMessage, setup.reserved_messages[model_idx].id)
                    if assistant_message is not None:
                        llm_loop_completion_handle(
                            state_container=state_containers[model_idx],
                            # model_succeeded[model_idx] is True here (guard above),
                            # so treat as connected — avoids "stopped by user" suffix.
                            is_connected=lambda: model_succeeded[model_idx],
                            db_session=self_complete_db,
                            assistant_message=assistant_message,
                            llm=setup.llms[model_idx],
                            reserved_tokens=setup.reserved_token_count,
                        )
            except Exception:
                logger.exception(
                    "model %d (%s): self-completion after disconnect failed",
                    model_idx,
                    setup.model_display_names[model_idx],
                )

    # Copy contextvars before submitting futures — ThreadPoolExecutor does NOT
    # auto-propagate contextvars in Python 3.11; threads would inherit a blank context.
    ctx = contextvars.copy_context()
    executor = ThreadPoolExecutor(max_workers=n_models, thread_name_prefix="multi-model")
    _completion_done: bool = False
    try:
        for i in range(n_models):
            executor.submit(ctx.run, _run_model, i)

        # ── Main thread: merge and yield packets ────────────────────────────
        models_remaining = n_models
        while models_remaining > 0:
            try:
                model_idx, item = merged_queue.get(timeout=0.05)
            except queue.Empty:
                # Check for user-initiated cancellation every 50 ms.
                if not setup.check_is_connected():
                    # Save state for every model before exiting. Models that already
                    # finished (model_succeeded[i]=True) get their full answer saved;
                    # models still in-flight get partial answer + "stopped by user".
                    for i in range(n_models):
                        try:
                            llm_loop_completion_handle(
                                state_container=state_containers[i],
                                # partial captures model_succeeded[i] by value at loop time, not by reference
                                is_connected=functools.partial(bool, model_succeeded[i]),
                                db_session=db_session,
                                assistant_message=setup.reserved_messages[i],
                                llm=setup.llms[i],
                                reserved_tokens=setup.reserved_token_count,
                            )
                        except Exception:
                            logger.exception(f"Failed completion for model {i} on disconnect ({setup.model_display_names[i]})")
                    yield Packet(
                        placement=Placement(turn_index=0),
                        obj=OverallStop(type="stop", stop_reason="user_cancelled"),
                    )
                    _completion_done = True
                    return
                continue
            else:
                if item is _MODEL_DONE:
                    models_remaining -= 1
                    continue

                if isinstance(item, Exception):
                    # Yield a tagged error for this model but keep the other models running.
                    # Do NOT decrement models_remaining — _run_model's finally always posts
                    # _MODEL_DONE, which is the sole completion signal.
                    error_msg = str(item)
                    stack_trace = "".join(traceback.format_exception(type(item), item, item.__traceback__))
                    model_llm = setup.llms[model_idx]
                    if model_llm.config.api_key and len(model_llm.config.api_key) > 2:
                        error_msg = error_msg.replace(model_llm.config.api_key, "[REDACTED_API_KEY]")
                        stack_trace = stack_trace.replace(model_llm.config.api_key, "[REDACTED_API_KEY]")
                    yield StreamingError(
                        error=error_msg,
                        stack_trace=stack_trace,
                        error_code="MODEL_ERROR",
                        is_retryable=True,
                        details={
                            "model": model_llm.config.model_name,
                            "provider": model_llm.config.model_provider,
                            "model_index": model_idx,
                        },
                    )
                    continue

                if isinstance(item, Packet):
                    # model_index already embedded by the model's Emitter in _run_model
                    yield item

        # ── Completion: save each successful model's response ───────────────
        # All model loops have completed (run_llm_loop returned) — no more writes
        # to state_containers. Worker threads may still be closing their own DB
        # sessions, but the main-thread db_session is unshared and safe to use.
        for i in range(n_models):
            if not model_succeeded[i]:
                continue
            try:
                llm_loop_completion_handle(
                    state_container=state_containers[i],
                    is_connected=setup.check_is_connected,
                    db_session=db_session,
                    assistant_message=setup.reserved_messages[i],
                    llm=setup.llms[i],
                    reserved_tokens=setup.reserved_token_count,
                )
            except Exception:
                logger.exception(f"Failed completion for model {i} ({setup.model_display_names[i]})")
        _completion_done = True

    finally:
        if _completion_done:
            # Normal exit or stop-button exit: completion already persisted.
            # Threads are done (normal path) or can finish in the background (stop-button).
            executor.shutdown(wait=False)
        else:
            # Early exit (GeneratorExit from raw HTTP disconnect, or unhandled
            # exception in the drain loop).
            # 1. Signal emitters to stop blocking — future emit() calls return immediately.
            drain_done.set()
            # 2. Drain buffered packets from memory — no consumer is running.
            while not merged_queue.empty():
                try:
                    merged_queue.get_nowait()
                except queue.Empty:
                    break
            # 3. Don't block the server thread — workers self-complete via drain_done.
            executor.shutdown(wait=False)


def _stream_chat_turn(
    new_msg_req: SendMessageRequest,
    user: User,
    db_session: Session,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    bypass_acl: bool = False,
    additional_context: str | None = None,
    slack_context: SlackContext | None = None,
    external_state_container: ChatStateContainer | None = None,
) -> AnswerStream:
    """Private implementation for single-model chat turn streaming.

    Builds the turn context via ``build_chat_turn``, then streams packets from
    ``_run_models`` back to the caller. Handles setup errors, LLM errors, and
    cancellation uniformly, saving whatever partial state has been accumulated
    before re-raising or yielding a terminal error packet.

    Not called directly — use ``handle_stream_message_objects`` as the public entrypoint.
    """
    if new_msg_req.mock_llm_response is not None and not INTEGRATION_TESTS_MODE:
        raise ValueError("mock_llm_response can only be used when INTEGRATION_TESTS_MODE=true")

    mock_response_token: Token[str | None] | None = None
    setup: ChatTurnSetup | None = None

    try:
        setup = yield from build_chat_turn(
            new_msg_req=new_msg_req,
            user=user,
            db_session=db_session,
            litellm_additional_headers=litellm_additional_headers,
            custom_tool_additional_headers=custom_tool_additional_headers,
            mcp_headers=mcp_headers,
            bypass_acl=bypass_acl,
            slack_context=slack_context,
            additional_context=additional_context,
        )

        # Set mock response token right before the LLM stream begins so that
        # run_in_background threads inherit the correct context.
        if new_msg_req.mock_llm_response is not None:
            mock_response_token = set_llm_mock_response(new_msg_req.mock_llm_response)

        yield from _run_models(
            setup=setup,
            user=user,
            db_session=db_session,
            external_state_container=external_state_container,
        )

    except OnyxError as e:
        if e.error_code is not OnyxErrorCode.QUERY_REJECTED:
            log_onyx_error(e)
        yield StreamingError(
            error=e.detail,
            error_code=e.error_code.code,
            is_retryable=e.status_code >= 500,
        )
        db_session.rollback()
        return

    except ValueError as e:
        logger.exception("Failed to process chat message.")
        yield StreamingError(
            error=str(e),
            error_code="VALIDATION_ERROR",
            is_retryable=True,
        )
        db_session.rollback()
        return

    except EmptyLLMResponseError as e:
        stack_trace = traceback.format_exc()
        logger.warning(f"LLM returned an empty response (provider={e.provider}, model={e.model}, tool_choice={e.tool_choice})")
        yield StreamingError(
            error=e.client_error_msg,
            stack_trace=stack_trace,
            error_code=e.error_code,
            is_retryable=e.is_retryable,
            details={
                "model": e.model,
                "provider": e.provider,
                "tool_choice": e.tool_choice.value,
            },
        )
        db_session.rollback()

    except Exception as e:
        logger.exception(f"Failed to process chat message due to {e}")
        stack_trace = traceback.format_exc()

        llm = setup.llms[0] if setup else None
        if llm:
            client_error_msg, error_code, is_retryable = litellm_exception_to_error_msg(e, llm)
            if llm.config.api_key and len(llm.config.api_key) > 2:
                client_error_msg = client_error_msg.replace(llm.config.api_key, "[REDACTED_API_KEY]")
                stack_trace = stack_trace.replace(llm.config.api_key, "[REDACTED_API_KEY]")
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
            yield StreamingError(
                error="Failed to initialize the chat. Please check your configuration and try again.",
                stack_trace=stack_trace,
                error_code="INIT_FAILED",
                is_retryable=True,
            )
        db_session.rollback()

    finally:
        if mock_response_token is not None:
            reset_llm_mock_response(mock_response_token)
        try:
            if setup is not None:
                set_processing_status(
                    chat_session_id=setup.chat_session.id,
                    cache=setup.cache,
                    value=False,
                )
        except Exception:
            logger.exception("Error in setting processing status")


def handle_stream_message_objects(
    new_msg_req: SendMessageRequest,
    user: User,
    db_session: Session,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    bypass_acl: bool = False,
    additional_context: str | None = None,
    slack_context: SlackContext | None = None,
    external_state_container: ChatStateContainer | None = None,
) -> AnswerStream:
    """Single-model streaming entrypoint. Delegates to ``_stream_chat_turn``."""
    yield from _stream_chat_turn(
        new_msg_req=new_msg_req,
        user=user,
        db_session=db_session,
        litellm_additional_headers=litellm_additional_headers,
        custom_tool_additional_headers=custom_tool_additional_headers,
        mcp_headers=mcp_headers,
        bypass_acl=bypass_acl,
        additional_context=additional_context,
        slack_context=slack_context,
        external_state_container=external_state_container,
    )


def llm_loop_completion_handle(
    state_container: ChatStateContainer,
    is_connected: Callable[[], bool],
    db_session: Session,
    assistant_message: ChatMessage,
    llm: LLM,
    reserved_tokens: int,
) -> None:
    chat_session_id = assistant_message.chat_session_id

    # Snapshot all state under the container's lock before any DB write.
    # Worker threads may still be running (e.g. user-cancellation path), so
    # direct attribute access is not thread-safe — use the provided getters.
    answer_tokens = state_container.get_answer_tokens()
    reasoning_tokens = state_container.get_reasoning_tokens()
    citation_to_doc = state_container.get_citation_to_doc()
    tool_calls = state_container.get_tool_calls()
    is_clarification = state_container.get_is_clarification()
    all_search_docs = state_container.get_all_search_docs()
    emitted_citations = state_container.get_emitted_citations()
    pre_answer_processing_time = state_container.get_pre_answer_processing_time()

    completed_normally = is_connected()
    if completed_normally:
        if answer_tokens is None:
            raise RuntimeError("LLM run completed normally but did not return an answer.")
        final_answer = answer_tokens
    else:
        # Stopped by user - append stop message
        logger.debug(f"Chat session {chat_session_id} stopped by user")
        if answer_tokens:
            final_answer = answer_tokens + " ... \n\nGeneration was stopped by the user."
        else:
            final_answer = "The generation was stopped by the user."

    save_chat_turn(
        message_text=final_answer,
        reasoning_tokens=reasoning_tokens,
        citation_to_doc=citation_to_doc,
        tool_calls=tool_calls,
        all_search_docs=all_search_docs,
        db_session=db_session,
        assistant_message=assistant_message,
        is_clarification=is_clarification,
        emitted_citations=emitted_citations,
        pre_answer_processing_time=pre_answer_processing_time,
    )

    # Check if compression is needed after saving the message
    updated_chat_history = create_chat_history_chain(
        chat_session_id=chat_session_id,
        db_session=db_session,
    )
    total_tokens = calculate_total_history_tokens(updated_chat_history)

    compression_params = get_compression_params(
        max_input_tokens=llm.config.max_input_tokens,
        current_history_tokens=total_tokens,
        reserved_tokens=reserved_tokens,
    )
    if compression_params.should_compress:
        # Build tool mapping for formatting messages
        all_tools = get_tools(db_session)
        tool_id_to_name = {tool.id: tool.name for tool in all_tools}

        compress_chat_history(
            db_session=db_session,
            chat_history=updated_chat_history,
            llm=llm,
            compression_params=compression_params,
            tool_id_to_name=tool_id_to_name,
        )


_CITATION_LINK_START_PATTERN = re.compile(r"\s*\[\[\d+\]\]\(")


def _find_markdown_link_end(text: str, destination_start: int) -> int | None:
    depth = 0
    i = destination_start

    while i < len(text):
        curr = text[i]
        if curr == "\\":
            i += 2
            continue

        if curr == "(":
            depth += 1
        elif curr == ")":
            if depth == 0:
                return i
            depth -= 1

        i += 1

    return None


def remove_answer_citations(answer: str) -> str:
    stripped_parts: list[str] = []
    cursor = 0

    while match := _CITATION_LINK_START_PATTERN.search(answer, cursor):
        stripped_parts.append(answer[cursor : match.start()])
        link_end = _find_markdown_link_end(answer, match.end())
        if link_end is None:
            stripped_parts.append(answer[match.start() :])
            return "".join(stripped_parts)

        cursor = link_end + 1

    stripped_parts.append(answer[cursor:])
    return "".join(stripped_parts)


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
        if error_msg is not None:
            answer = ""
        else:
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


@log_function_time()
def gather_stream_full(
    packets: AnswerStream,
    state_container: ChatStateContainer,
) -> ChatFullResponse:
    """
    Aggregate streaming packets and state container into a complete ChatFullResponse.

    This function consumes all packets from the stream and combines them with
    the accumulated state from the ChatStateContainer to build a complete response
    including answer, reasoning, citations, and tool calls.

    Args:
        packets: The stream of packets from handle_stream_message_objects
        state_container: The state container that accumulates tool calls, reasoning, etc.

    Returns:
        ChatFullResponse with all available data
    """
    answer: str | None = None
    citations: list[CitationInfo] = []
    error_msg: str | None = None
    message_id: int | None = None
    top_documents: list[SearchDoc] = []
    chat_session_id: UUID | None = None

    for packet in packets:
        if isinstance(packet, Packet):
            if isinstance(packet.obj, AgentResponseStart):
                if packet.obj.final_documents:
                    top_documents = packet.obj.final_documents
            elif isinstance(packet.obj, AgentResponseDelta):
                if answer is None:
                    answer = ""
                if packet.obj.content:
                    answer += packet.obj.content
            elif isinstance(packet.obj, CitationInfo):
                citations.append(packet.obj)
        elif isinstance(packet, StreamingError):
            error_msg = packet.error
        elif isinstance(packet, MessageResponseIDInfo):
            message_id = packet.reserved_assistant_message_id
        elif isinstance(packet, CreateChatSessionID):
            chat_session_id = packet.chat_session_id

    if message_id is None:
        raise ValueError("Message ID is required")

    # Use state_container for complete answer (handles edge cases gracefully)
    final_answer = state_container.get_answer_tokens() or answer or ""

    # Get reasoning from state container (None when model doesn't produce reasoning)
    reasoning = state_container.get_reasoning_tokens()

    # Convert ToolCallInfo list to ToolCallResponse list
    tool_call_responses = [
        ToolCallResponse(
            tool_name=tc.tool_name,
            tool_arguments=tc.tool_call_arguments,
            tool_result=tc.tool_call_response,
            search_docs=tc.search_docs,
            generated_images=tc.generated_images,
            pre_reasoning=tc.reasoning_tokens,
        )
        for tc in state_container.get_tool_calls()
    ]

    return ChatFullResponse(
        answer=final_answer,
        answer_citationless=remove_answer_citations(final_answer),
        pre_answer_reasoning=reasoning,
        tool_calls=tool_call_responses,
        top_documents=top_documents,
        citation_info=citations,
        message_id=message_id,
        chat_session_id=chat_session_id,
        error_msg=error_msg,
    )
