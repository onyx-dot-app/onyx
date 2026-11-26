import datetime
import posixpath
import time
from collections.abc import Callable, Generator
from concurrent.futures import Future
from datetime import timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    Request,
    Response,
)
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.access.access import user_can_access_chat_file
from onyx.agents.models import MessageDelivery, RunFailureKind, RunStatus
from onyx.auth.api_key import get_hashed_api_key_from_request
from onyx.auth.pat import get_hashed_pat_from_request
from onyx.auth.permissions import require_permission
from onyx.auth.users import current_chat_accessible_user
from onyx.background.task_utils import enqueue_user_file_deletes
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.chat.agent_stream import read_agent_stream_pointer
from onyx.chat.chat_processing_checker import (
    ADMISSION_CACHE_TIMEOUT_S,
    current_turn_owner,
    get_processing_stream,
    is_chat_session_processing,
    stop_current_turn,
)
from onyx.chat.chat_utils import (
    create_chat_session_from_request,
)
from onyx.chat.errors import unhandled_stream_error
from onyx.chat.file_preview import (
    convert_chat_file_preview_pdf,
    resolve_chat_file_preview,
)
from onyx.chat.incognito import (
    delete_incognito_generated_files,
    incognito_allowed_for_user,
)
from onyx.chat.incognito_context import teardown_incognito_session
from onyx.chat.models import (
    ChatFullResponse,
    ChatResponseOutcome,
    CreateChatSessionID,
    PendingChatMessage,
    SavedToolQuestion,
)
from onyx.chat.presentation import overall_stop
from onyx.chat.process_message import (
    USER_INPUT_PENDING,
    dispatch_pending_chat_messages,
    handle_multi_model_stream,
    handle_stream_message_objects,
    process_chat_query,
    run_chat_turn,
)
from onyx.chat.prompt_utils import get_default_base_system_prompt
from onyx.chat.run_store import (
    ownerless_response_ids,
    request_response_stop,
    stop_response,
)
from onyx.chat.session_naming import name_chat_session
from onyx.chat.stop_signal_checker import request_stop
from onyx.chat.stream_buffer import StreamChunkRead, read_stream_chunks
from onyx.chat.tool_approvals import action_now_blocked
from onyx.chat.tool_questions import card_answers
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.chat_configs import (
    CHAT_HEARTBEAT_INTERVAL_S,
    CHAT_RESUME_POLL_INTERVAL_S,
    HARD_DELETE_CHATS,
)
from onyx.configs.constants import (
    PUBLIC_API_TAGS,
    MessageType,
    MilestoneRecordType,
)
from onyx.configs.model_configs import LITELLM_PASS_THROUGH_HEADERS
from onyx.configs.tool_configs import CUSTOM_TOOL_PASS_THROUGH_HEADERS
from onyx.db.access import user_can_read_chat_session
from onyx.db.approval_request import (
    approvals_version,
    close_pending_approval_requests__no_commit,
    get_approval_request_for_user,
    record_approval_decision__no_commit,
)
from onyx.db.chat import (
    add_chat_session__no_commit,
    add_chats_to_session_from_slack_thread,
    agent_subtree_ids,
    delete_all_chat_sessions_for_user,
    delete_chat_session,
    duplicate_chat_session_for_user_from_slack,
    get_chat_artifact_file,
    get_chat_message,
    get_chat_message_page_ids,
    get_chat_messages_by_session,
    get_chat_published_files,
    get_chat_session_by_id,
    get_chat_sessions_by_user,
    get_incognito_session_ids_for_user,
    get_owned_chat_session,
    get_selected_branch,
    set_as_latest_chat_message,
    set_chat_session_tool_options__no_commit,
    set_preferred_response,
    translate_db_message_to_chat_message_detail,
    update_chat_session,
)
from onyx.db.chat_checkpoint import parked_response_ids, parked_tree_approval_ids
from onyx.db.chat_inputs import (
    active_agent_response_ids,
    chat_message_content,
    drop_agent_work__no_commit,
    get_human_input_session,
    interrupt_human_message__no_commit,
    list_human_messages,
    lock_agent,
    pause_chat_queue__no_commit,
    read_chat_inbox,
    submit_human_message__no_commit,
    withdraw_human_message__no_commit,
)
from onyx.db.chat_response import (
    load_chat_approvals,
    load_child_responses,
    waiting_approval_reply_ids,
)
from onyx.db.chat_search import search_chat_sessions
from onyx.db.chat_subagents import (
    agent_run_summaries,
    latest_agent_response,
    load_session_agent_metadata,
    selected_agent_message_ids,
)
from onyx.db.engine.sql_engine import get_session, get_session_with_current_tenant
from onyx.db.enums import (
    ApprovalDecidedVia,
    ApprovalDecision,
    Permission,
    QuestionAnsweredVia,
    QuestionOutcome,
    record_mode_persists_content,
)
from onyx.db.feedback import create_chat_message_feedback, remove_chat_message_feedback
from onyx.db.incognito import (
    is_incognito_teardown_target,
    mark_incognito_user_files_deleting,
)
from onyx.db.models import (
    ChatMessage,
    ChatSessionSharedStatus,
    FileRecord,
    Persona,
    User,
)
from onyx.db.persona import get_persona_by_id
from onyx.db.question_request import (
    get_question_request_for_user,
    get_response_question_requests,
    resolve_question_requests__no_commit,
)
from onyx.db.usage import UsageType, increment_usage
from onyx.db.user_file import get_file_id_by_user_file_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_processing.file_types import PDF_MIME_TYPE
from onyx.file_store.file_store import get_default_file_store
from onyx.file_store.serving import (
    ATTACHMENT_SAFE_MIME_TYPES,
    RESPONSE_POLICY_VERSION,
    ensure_filename_extension,
    resolve_inline_disposition,
)
from onyx.indexing.chat_artifact_index import delete_chat_artifacts_from_index
from onyx.integrations.models import ApprovalMode
from onyx.llm.constants import LlmProviderNames
from onyx.llm.factory import (
    get_llm_for_persona,
    get_llm_token_counter,
)
from onyx.llm.models import (
    USER_SELECTABLE_REASONING_EFFORTS,
    ReasoningEffort,
    parse_user_selectable_reasoning_effort,
)
from onyx.secondary_llm_flows.chat_session_naming import (
    DEFAULT_CHAT_SESSION_NAME,
)
from onyx.server.api_key_usage import check_api_key_usage
from onyx.server.features.action_policies.models import ApprovalChoice
from onyx.server.features.build.sandbox.firecracker.purge import (
    purge_deleted_chat_sessions,
)
from onyx.server.middleware.rate_limiting import get_feedback_rate_limiters
from onyx.server.query_and_chat.acp_stream import ChatAcpTranslator
from onyx.server.query_and_chat.chat_utils import (
    is_spreadsheet_mime_type,
    parse_spreadsheet_for_preview,
)
from onyx.server.query_and_chat.models import (
    ApprovalDecisionResponse,
    ChatApprovalDecisionRequest,
    ChatArtifactAccess,
    ChatArtifactFile,
    ChatFeedbackRequest,
    ChatMessageDetail,
    ChatMessageIdentifier,
    ChatQuestionAnswersRequest,
    ChatRenameRequest,
    ChatSearchResponse,
    ChatSessionCreationRequest,
    ChatSessionDetailResponse,
    ChatSessionDetails,
    ChatSessionGroup,
    ChatSessionProcessingStatus,
    ChatSessionsResponse,
    ChatSessionSummary,
    ChatSessionUpdateRequest,
    ChatSubagent,
    ChatSubagentHistory,
    CurrentStreamInfo,
    MessageOrigin,
    PendingChatMessageRequest,
    QuestionAnswersResponse,
    RenameChatSessionResponse,
    SendMessageRequest,
    SetPreferredResponseRequest,
    StopChatResponse,
    StopSubagentsRequest,
    StopSubagentsResponse,
    UpdateChatSessionReasoningRequest,
    UpdateChatSessionTemperatureRequest,
    UpdateChatSessionThreadRequest,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.session_loading import (
    load_session_tools,
    translate_assistant_message_to_packets,
)
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
    Packet,
    StreamCursor,
    UserMessagePacket,
    heartbeat_packet,
)
from onyx.server.query_and_chat.token_limit import (
    check_token_rate_limits,
)
from onyx.server.usage_limits import (
    check_usage_and_raise,
    is_usage_limits_enabled,
)
from onyx.server.utils import get_json_line
from onyx.tools.models import ToolOptions
from onyx.tools.tool_implementations.subagents.models import ChatConfiguration
from onyx.utils.headers import get_relevant_headers
from onyx.utils.logger import setup_logger
from onyx.utils.postgres_sanitization import sanitize_string
from onyx.utils.telemetry import mt_cloud_telemetry
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Largest page a client can ask of `get-chat-session`.
MAX_CHAT_SESSION_PAGE_SIZE = 200

router = APIRouter(prefix="/chat")


def _get_available_tokens_for_persona(
    persona: Persona,
    db_session: Session,
    user: User,
) -> int:
    def _get_non_reserved_input_tokens(
        model_max_input_tokens: int,
        system_and_agent_prompt_tokens: int,
        num_tools: int,
        token_reserved_per_tool: int = 256,
        # Estimating for a long user input message, hard to know ahead of time
        default_reserved_tokens: int = 2000,
    ) -> int:
        return (
            model_max_input_tokens
            - system_and_agent_prompt_tokens
            - num_tools * token_reserved_per_tool
            - default_reserved_tokens
        )

    llm = get_llm_for_persona(persona=persona, user=user, user_defaults=None)
    token_counter = get_llm_token_counter(llm)

    if persona.replace_base_system_prompt and persona.system_prompt:
        # User has opted to replace the base system prompt entirely
        combined_prompt_tokens = token_counter(persona.system_prompt)
    else:
        # Default behavior: prepend custom prompt to base system prompt
        system_prompt = get_default_base_system_prompt(db_session)
        agent_prompt = persona.system_prompt + " " if persona.system_prompt else ""
        combined_prompt_tokens = token_counter(agent_prompt + system_prompt)

    return _get_non_reserved_input_tokens(
        model_max_input_tokens=llm.config.max_input_tokens,
        system_and_agent_prompt_tokens=combined_prompt_tokens,
        num_tools=len(persona.tools),
    )


@router.get("/get-user-chat-sessions", tags=PUBLIC_API_TAGS)
def get_user_chat_sessions(
    user: User = Depends(require_permission(Permission.READ_CHAT)),
    db_session: Session = Depends(get_session),
    project_id: int | None = None,
    only_non_project_chats: bool = True,
    include_failed_chats: bool = False,
    page_size: int = Query(default=50, ge=1, le=100),
    before: str | None = Query(default=None),
) -> ChatSessionsResponse:
    user_id = user.id

    try:
        before_dt = (
            datetime.datetime.fromisoformat(before) if before is not None else None
        )
    except ValueError:
        raise OnyxError(
            OnyxErrorCode.VALIDATION_ERROR,
            "Invalid 'before' timestamp format",
            status_code_override=422,
        )

    try:
        # Fetch one extra to determine if there are more results
        chat_sessions = get_chat_sessions_by_user(
            user_id=user_id,
            deleted=False,
            db_session=db_session,
            project_id=project_id,
            only_non_project_chats=only_non_project_chats,
            include_failed_chats=include_failed_chats,
            # The owner's own history is the one surface incognito hides from.
            exclude_incognito=True,
            limit=page_size + 1,
            before=before_dt,
        )

    except ValueError:
        raise ValueError("Chat session does not exist or has been deleted")

    has_more = len(chat_sessions) > page_size
    chat_sessions = chat_sessions[:page_size]

    return ChatSessionsResponse(
        sessions=[
            ChatSessionDetails(
                id=chat.id,
                name=chat.description,
                persona_id=chat.persona_id,
                time_created=chat.time_created.isoformat(),
                time_updated=chat.time_updated.isoformat(),
                shared_status=chat.shared_status,
                current_alternate_model=chat.current_alternate_model,
                current_temperature_override=chat.temperature_override,
                current_reasoning_effort_override=chat.reasoning_effort_override,
            )
            for chat in chat_sessions
        ],
        has_more=has_more,
    )


@router.put("/update-chat-session-temperature")
def update_chat_session_temperature(
    update_thread_req: UpdateChatSessionTemperatureRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    chat_session = get_chat_session_by_id(
        chat_session_id=update_thread_req.chat_session_id,
        user_id=user.id,
        db_session=db_session,
    )

    # Validate temperature_override
    if update_thread_req.temperature_override is not None:
        if (
            update_thread_req.temperature_override < 0
            or update_thread_req.temperature_override > 2
        ):
            raise OnyxError(
                OnyxErrorCode.BAD_REQUEST, "Temperature must be between 0 and 2"
            )

        # Additional check for Anthropic models
        if (
            chat_session.current_alternate_model
            and LlmProviderNames.ANTHROPIC
            in chat_session.current_alternate_model.lower()
        ):
            if update_thread_req.temperature_override > 1:
                raise OnyxError(
                    OnyxErrorCode.BAD_REQUEST,
                    "Temperature for Anthropic models must be between 0 and 1",
                )

    chat_session.temperature_override = update_thread_req.temperature_override

    add_chat_session__no_commit(db_session, chat_session)
    db_session.commit()


@router.put("/update-chat-session-reasoning")
def update_chat_session_reasoning(
    update_thread_req: UpdateChatSessionReasoningRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    chat_session = get_chat_session_by_id(
        chat_session_id=update_thread_req.chat_session_id,
        user_id=user.id,
        db_session=db_session,
    )

    # NULL clears the override. Any set value must be a user-selectable effort.
    reasoning_effort: ReasoningEffort | None = None
    if update_thread_req.reasoning_effort_override is not None:
        try:
            reasoning_effort = parse_user_selectable_reasoning_effort(
                update_thread_req.reasoning_effort_override
            )
        except ValueError:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "reasoning_effort_override must be one of: "
                + ", ".join(
                    effort.value
                    for effort in ReasoningEffort
                    if effort in USER_SELECTABLE_REASONING_EFFORTS
                ),
            )

    chat_session.reasoning_effort_override = reasoning_effort
    add_chat_session__no_commit(db_session, chat_session)
    db_session.commit()


@router.put("/update-chat-session-model")
def update_chat_session_model(
    update_thread_req: UpdateChatSessionThreadRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    chat_session = get_chat_session_by_id(
        chat_session_id=update_thread_req.chat_session_id,
        user_id=user.id,
        db_session=db_session,
    )
    chat_session.current_alternate_model = update_thread_req.new_alternate_model

    add_chat_session__no_commit(db_session, chat_session)
    db_session.commit()


@router.get("/get-chat-session/{session_id}", tags=PUBLIC_API_TAGS)
def get_chat_session(
    session_id: UUID,
    is_shared: bool = False,
    include_deleted: bool = False,
    # In `Annotated`, so a direct call (as in tests) gets the plain default.
    limit: Annotated[
        int | None,
        Query(
            ge=1,
            le=MAX_CHAT_SESSION_PAGE_SIZE,
            description=(
                "Return one page of the current branch: its last `limit` "
                "messages and their children. `has_older_messages` tells "
                "whether the branch has messages before the page. Without it, "
                "every message on every branch is returned."
            ),
        ),
    ] = None,
    before_message_id: Annotated[
        int | None,
        Query(
            description=(
                "With `limit`, return the page that ends before this message. "
                "Pass the oldest loaded message to load the next older page."
            ),
        ),
    ] = None,
    user: User = Depends(
        require_permission(Permission.READ_CHAT, allow_anonymous=True)
    ),
    db_session: Session = Depends(get_session),
) -> ChatSessionDetailResponse:
    user_id = user.id
    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=session_id,
            user_id=user_id,
            db_session=db_session,
            is_shared=is_shared,
            include_deleted=include_deleted,
        )
    except ValueError:
        try:
            # If we failed to get a chat session, try to retrieve the session with
            # less restrictive filters in order to identify what exactly mismatched
            # so we can bubble up an accurate error code andmessage.
            existing_chat_session = get_chat_session_by_id(
                chat_session_id=session_id,
                user_id=None,
                db_session=db_session,
                is_shared=False,
                include_deleted=True,
            )
        except ValueError:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Chat session not found")

        if not include_deleted and existing_chat_session.deleted:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Chat session has been deleted")

        if is_shared:
            if existing_chat_session.shared_status != ChatSessionSharedStatus.PUBLIC:
                raise OnyxError(
                    OnyxErrorCode.UNAUTHORIZED, "Chat session is not shared"
                )
        elif user_id is not None and existing_chat_session.user_id not in (
            user_id,
            None,
        ):
            raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "Access denied")

        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Chat session not found")

    # for chat-seeding: if the session is unassigned, assign it now. This is done here
    # to avoid another back and forth between FE -> BE before starting the first
    # message generation
    if chat_session.user_id is None and user_id is not None:
        chat_session.user_id = user_id
        db_session.commit()

    # Read admission and the approvals version before the messages. A turn
    # saves before it releases admission, so an idle result means the page
    # holds that turn's saves, and a request that opens meanwhile changes the
    # version.
    current_stream: CurrentStreamInfo | None = None
    is_processing = True
    try:
        cache = get_cache_backend(operation_timeout_s=ADMISSION_CACHE_TIMEOUT_S)
        is_processing = is_chat_session_processing(session_id, cache)
        stream = get_processing_stream(session_id, cache)
        if stream is not None:
            current_stream = CurrentStreamInfo(
                stream_id=stream.stream_id, response_ids=stream.response_ids
            )
    except Exception:
        is_processing = True
        logger.exception(
            "An error occurred while checking if the chat session is processing"
        )
    version = approvals_version(db_session, session_id)

    page_message_ids: set[int] | None = None
    has_older_messages = False
    if limit is not None:
        # The latest page reaches back to every waiting card's reply, so a
        # client that loads only that page shows every waiting card.
        page_message_ids, has_older_messages = get_chat_message_page_ids(
            chat_session_id=session_id,
            db_session=db_session,
            limit=limit,
            before_message_id=before_message_id,
            waiting_reply_ids=waiting_approval_reply_ids(db_session, session_id)
            if before_message_id is None
            else (),
        )
    chat_message_details, replay_packet_lists = _session_messages_and_packets(
        db_session, session_id, user_id, page_message_ids
    )
    # The client keeps the list from a latest-page load, and the shared view
    # from its full load; an older page does not need it. Read after the
    # replay, so the list holds every file that a replayed call published.
    published_files = (
        get_chat_published_files(session_id, db_session)
        if before_message_id is None and (limit is not None or is_shared)
        else None
    )
    if is_shared:
        # A shared view shows no skills the owner picked: not on questions and
        # not on messages accepted during a response.
        chat_message_details = [
            detail.model_copy(update={"mentions": []})
            for detail in chat_message_details
        ]
        replay_packet_lists = [
            [
                packet.model_copy(
                    update={"obj": packet.obj.model_copy(update={"mentions": []})}
                )
                if isinstance(packet.obj, UserMessagePacket)
                else packet
                for packet in packets
            ]
            for packets in replay_packet_lists
        ]

    return ChatSessionDetailResponse(
        chat_session_id=session_id,
        description=chat_session.description,
        persona_id=chat_session.persona_id,
        persona_name=chat_session.persona.name if chat_session.persona else None,
        personal_icon_name=chat_session.persona.icon_name,
        current_alternate_model=chat_session.current_alternate_model,
        messages=chat_message_details,
        time_created=chat_session.time_created,
        shared_status=chat_session.shared_status,
        current_temperature_override=chat_session.temperature_override,
        current_reasoning_effort_override=chat_session.reasoning_effort_override,
        deleted=chat_session.deleted,
        owner_name=chat_session.user.personal_name if chat_session.user else None,
        # Packets are now directly serialized as Packet Pydantic models
        packets=replay_packet_lists,
        current_stream=current_stream,
        approvals_version=version,
        is_processing=is_processing,
        incognito=chat_session.incognito_record_mode is not None,
        has_older_messages=has_older_messages,
        published_files=published_files,
        # Only the owner's composer reads the options; a shared view shows none.
        tool_options=chat_session.tool_options
        if user_id is not None and chat_session.user_id == user_id
        else None,
    )


@router.post("/create-chat-session", tags=PUBLIC_API_TAGS)
def create_new_chat_session(
    chat_session_creation_request: ChatSessionCreationRequest,
    user: User = Depends(
        require_permission(Permission.WRITE_CHAT, allow_anonymous=True)
    ),
    db_session: Session = Depends(get_session),
) -> CreateChatSessionID:
    try:
        new_chat_session = create_chat_session_from_request(
            chat_session_request=chat_session_creation_request,
            user=user,
            db_session=db_session,
        )
    except OnyxError:
        # Carries its own status and detail (e.g. incognito refused).
        raise
    except ValueError as e:
        # Project or persona access denied
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, str(e))
    except Exception as e:
        logger.exception(e)
        raise OnyxError(OnyxErrorCode.BAD_REQUEST, "Invalid Persona provided.")

    return CreateChatSessionID(
        chat_session_id=new_chat_session.id,
        incognito=new_chat_session.incognito_record_mode is not None,
    )


@router.put("/rename-chat-session")
def rename_chat_session(
    rename_req: ChatRenameRequest,
    request: Request,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
) -> RenameChatSessionResponse:
    name = rename_req.name
    chat_session_id = rename_req.chat_session_id
    user_id = user.id

    if name:
        with get_session_with_current_tenant() as db_session:
            chat_session = update_chat_session(
                db_session=db_session,
                user_id=user_id,
                chat_session_id=chat_session_id,
                description=name,
            )
        # Echo what was stored: a content-free session drops the title, and
        # reporting the requested one would show a rename that did not happen.
        return RenameChatSessionResponse(new_name=chat_session.description or "")

    with get_session_with_current_tenant() as db_session:
        chat_session = get_chat_session_by_id(
            chat_session_id=chat_session_id,
            user_id=user_id,
            db_session=db_session,
        )
        # Auto-naming derives a title from the conversation and writes it to the
        # session row. A non-persisting incognito mode keeps no content in
        # Postgres, so it keeps the fallback name and skips the LLM call.
        if not record_mode_persists_content(chat_session.incognito_record_mode):
            return RenameChatSessionResponse(new_name=DEFAULT_CHAT_SESSION_NAME)

    # Returns a saved name, including one the chat turn is still generating.
    try:
        new_name = name_chat_session(
            chat_session_id=chat_session_id,
            user=user,
            additional_headers=get_relevant_headers(
                request.headers, LITELLM_PASS_THROUGH_HEADERS
            ),
            regenerate=rename_req.regenerate,
        )
    except OnyxError:
        raise
    except Exception as error:
        if not rename_req.regenerate:
            raise
        # A failed regeneration keeps the old name and reports the model failure.
        logger.warning("Failed to regenerate chat session name: %s", error)
        raise OnyxError(
            OnyxErrorCode.LLM_PROVIDER_ERROR,
            "Could not generate a new chat name",
        ) from error
    return RenameChatSessionResponse(new_name=new_name)


@router.patch("/chat-session/{session_id}")
def patch_chat_session(
    session_id: UUID,
    chat_session_update_req: ChatSessionUpdateRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id
    update_chat_session(
        db_session=db_session,
        user_id=user_id,
        chat_session_id=session_id,
        sharing_status=chat_session_update_req.sharing_status,
    )
    return None


def _teardown_incognito_after_delete(
    chat_session_id: UUID, user_id: UUID, db_session: Session
) -> None:
    """The rows are already gone, so a failed teardown is logged rather than
    failing a delete the caller cannot retry. The context TTL is the backstop.

    Uploads are queued here too, so deleting a chat cleans up the same things
    the dedicated teardown endpoint does."""
    try:
        mark_incognito_user_files_deleting(db_session, chat_session_id, user_id)
        db_session.commit()
    except Exception:
        logger.exception("Incognito file cleanup failed for %s", chat_session_id)
    try:
        teardown_incognito_session(chat_session_id)
    except Exception:
        logger.exception("Incognito teardown failed for session %s", chat_session_id)


@router.delete("/delete-all-chat-sessions", tags=PUBLIC_API_TAGS)
def delete_all_chat_sessions(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    incognito_session_ids = get_incognito_session_ids_for_user(user.id, db_session)
    # Blobs first, and nothing is deleted while any remain: their ids live on
    # the rows this is about to drop, so the other order strands them.
    if not all(
        delete_incognito_generated_files(incognito_id, db_session)
        for incognito_id in incognito_session_ids
    ):
        raise OnyxError(
            OnyxErrorCode.SERVICE_UNAVAILABLE,
            "Some generated files could not be deleted yet. Try again shortly.",
        )
    try:
        deleted_ids, artifact_ids = delete_all_chat_sessions_for_user(
            user=user, db_session=db_session
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.BAD_REQUEST, str(e))
    delete_chat_artifacts_from_index(artifact_ids)
    purge_deleted_chat_sessions(user.id, deleted_ids)
    # Read after the delete commits: a park either commits first or refuses.
    if not HARD_DELETE_CHATS:
        _end_parked_responses(parked_response_ids(db_session, user.id))
    for incognito_id in incognito_session_ids:
        _teardown_incognito_after_delete(incognito_id, user.id, db_session)


def _end_parked_responses(response_ids: list[int]) -> None:
    """End the parked responses of soft-deleted chats, which nothing can
    decide anymore: their requests, checkpoints and program dumps go. A hard
    delete removes them with the chat."""
    if not response_ids:
        return
    cache = get_cache_backend()
    tenant_id = get_current_tenant_id()
    for response_id in response_ids:
        try:
            stop_response(cache, tenant_id, response_id, "user")
        except Exception:
            logger.exception("Could not end parked response %s", response_id)


@router.delete("/delete-chat-session/{session_id}", tags=PUBLIC_API_TAGS)
def delete_chat_session_by_id(
    session_id: UUID,
    hard_delete: bool | None = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id
    try:
        session = get_chat_session_by_id(
            chat_session_id=session_id, user_id=user_id, db_session=db_session
        )
        is_incognito = session.incognito_record_mode is not None
        if is_incognito and not delete_incognito_generated_files(
            session_id, db_session
        ):
            raise OnyxError(
                OnyxErrorCode.SERVICE_UNAVAILABLE,
                "Some generated files could not be deleted yet. Try again shortly.",
            )
        # Use the provided hard_delete parameter if specified, otherwise use the default config
        actual_hard_delete = (
            hard_delete if hard_delete is not None else HARD_DELETE_CHATS
        )
        artifact_ids = delete_chat_session(
            user_id, session_id, db_session, hard_delete=actual_hard_delete
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.BAD_REQUEST, str(e))
    delete_chat_artifacts_from_index(artifact_ids)
    purge_deleted_chat_sessions(user_id, [session_id])
    # Read after the delete commits: a park either commits first or refuses.
    if not actual_hard_delete:
        _end_parked_responses(parked_response_ids(db_session, user.id, session_id))
    if is_incognito:
        _teardown_incognito_after_delete(session_id, user.id, db_session)


class IncognitoAvailabilityResponse(BaseModel):
    available: bool


@router.get("/incognito-availability")
def get_incognito_availability(
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> IncognitoAvailabilityResponse:
    """Whether the acting user may start an incognito chat, so the client can
    hide the toggle. The create endpoint enforces the same rule regardless."""
    return IncognitoAvailabilityResponse(
        available=incognito_allowed_for_user(user, db_session)
    )


@router.post("/end-incognito-session/{session_id}", tags=PUBLIC_API_TAGS)
def end_incognito_session(
    session_id: UUID,
    bg_tasks: BackgroundTasks,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Drop an incognito session's live context the moment the chat closes.

    The context TTL is only the backstop for when this never arrives, such as
    a hard tab close. Uploads are found by session id, so one still in flight
    when the user leaves, or one attached before any message created the
    session, is queued for deletion just the same.
    """
    if not is_incognito_teardown_target(db_session, session_id, user.id):
        return
    # Durable file marking runs before the Redis teardown: the beacon is
    # one-shot, so a failure after this point still leaves the files queued
    # for deletion rather than stored but hidden.
    deletable_ids = mark_incognito_user_files_deleting(db_session, session_id, user.id)
    db_session.commit()

    # Nothing past the commit may raise. This is a one-shot beacon, so an error
    # reaches nobody who can act on it, and raising would discard the response
    # carrying the in-process drain that a Celery-less deployment relies on.
    enqueue_user_file_deletes(
        deletable_ids, tenant_id=get_current_tenant_id(), bg_tasks=bg_tasks
    )
    for what, step in (
        (
            "delete generated files",
            lambda: delete_incognito_generated_files(session_id, db_session),
        ),
        ("end the context", lambda: teardown_incognito_session(session_id)),
    ):
        try:
            if step() is False:
                logger.warning(
                    "Incognito teardown could not %s for %s", what, session_id
                )
        except Exception:
            logger.exception("Incognito teardown could not %s for %s", what, session_id)


def _reject_while_user_input_waits(db_session: Session, chat_session_id: UUID) -> None:
    """The user may draft but not send while the selected response is parked:
    its waits, its own requests and questions or a foreground subtree's
    requests, are on the user. A background agent waits independently and
    does not block. A typed answer to the response's questions goes through
    the question answers route."""
    selected, _ = get_selected_branch(db_session, chat_session_id)
    if selected is not None and selected.response_status == RunStatus.SUSPENDED:
        raise OnyxError(OnyxErrorCode.APPROVAL_PENDING, USER_INPUT_PENDING)


# NOTE: This endpoint is extremely central to the application, any changes to it should be reviewed and approved by an experienced
# team member. It is very important to 1. avoid bloat and 2. that this remains backwards compatible across versions.
@router.post(
    "/send-chat-message",
    response_model=ChatFullResponse,  # no-response-model: allow the handler also returns a Response, so the annotation is a union
    tags=PUBLIC_API_TAGS,
    responses={
        200: {
            "description": (
                "If `stream=true`, returns `text/event-stream`.\n"
                "If `stream=false`, returns `application/json` (ChatFullResponse). "
                "When tool calls wait for the user, the response stops and "
                "lists them: approval requests in `pending_tool_approvals`, "
                "and questions in `pending_tool_questions`. After the "
                "decisions and answers it continues in the chat session."
            ),
            "content": {
                "text/event-stream": {
                    "schema": {"type": "string"},
                    "examples": {
                        "stream": {
                            "summary": "Stream of NDJSON AnswerStreamPart's",
                            "value": "string",
                        }
                    },
                },
            },
        }
    },
)
def handle_send_chat_message(
    chat_message_req: SendMessageRequest,
    request: Request,
    user: User = Depends(
        require_permission(Permission.WRITE_CHAT, allow_anonymous=True)
    ),
    _rate_limit_check: None = Depends(check_token_rate_limits),
    _api_key_usage_check: None = Depends(check_api_key_usage),
) -> StreamingResponse | ChatFullResponse:
    """
    This endpoint is used to send a new chat message.

    Args:
        chat_message_req (SendMessageRequest): Details about the new chat message.
            - When stream=True (default): Returns StreamingResponse with SSE
            - When stream=False: Returns ChatFullResponse with complete data, or
              with `pending_tool_approvals` and `pending_tool_questions` when
              the response stops because tool calls wait for the user
        request (Request): The current HTTP request context.
        user (User): The current user, obtained via dependency injection.
        _ (None): Rate limit check is run if user/group/global rate limits are enabled.

    Returns:
        StreamingResponse | ChatFullResponse: Either streams or returns complete response.
    """
    # Session id only: the session's incognito mode isn't loaded yet, and a
    # verbatim prompt in the debug log would be exactly the durable message
    # log incognito must never leave behind.
    logger.debug(
        "Received new chat message for session %s", chat_message_req.chat_session_id
    )

    # Check before streaming starts, so the client gets a status, not a packet.
    # Only the session's owner learns that it waits; the turn reports any
    # other caller's access error.
    if chat_message_req.chat_session_id is not None:
        with get_session_with_current_tenant() as db_session:
            try:
                get_chat_session_by_id(
                    chat_session_id=chat_message_req.chat_session_id,
                    user_id=user.id,
                    db_session=db_session,
                )
            except ValueError:
                pass
            else:
                _reject_while_user_input_waits(
                    db_session, chat_message_req.chat_session_id
                )

    tenant_id = get_current_tenant_id()
    mt_cloud_telemetry(
        tenant_id=tenant_id,
        distinct_id=tenant_id if user.is_anonymous else str(user.id),
        event=MilestoneRecordType.RAN_QUERY,
    )

    # Authentication identifies the Discord bot's service API key, not a
    # request field.
    discord_bot = getattr(  # ods: ignore[getattr]
        request.state, "discord_bot_api_key", False
    )
    # Override origin to API when authenticated via API key or PAT
    # to prevent clients from polluting telemetry data
    if get_hashed_api_key_from_request(request) or get_hashed_pat_from_request(request):
        chat_message_req.origin = (
            MessageOrigin.DISCORDBOT if discord_bot else MessageOrigin.API
        )

    # Discord cannot show approval requests, so a turn of the Discord bot's
    # service API key is not offered an action that would ask.
    approval_mode = (
        ApprovalMode.NO_APPROVER if discord_bot else ApprovalMode.INTERACTIVE
    )

    # Multi-model streaming path: 2-3 LLMs in parallel (streaming only)
    is_multi_model = (
        chat_message_req.llm_overrides is not None
        and len(chat_message_req.llm_overrides) > 1
    )
    if is_multi_model and chat_message_req.stream:
        # Narrowed here; is_multi_model already checked llm_overrides is not None
        llm_overrides = chat_message_req.llm_overrides or []

        def multi_model_stream_generator() -> Generator[str, None, None]:
            try:
                for obj in handle_multi_model_stream(
                    new_msg_req=chat_message_req,
                    user=user,
                    llm_overrides=llm_overrides,
                    litellm_additional_headers=get_relevant_headers(
                        request.headers, LITELLM_PASS_THROUGH_HEADERS
                    ),
                    custom_tool_additional_headers=get_relevant_headers(
                        request.headers, CUSTOM_TOOL_PASS_THROUGH_HEADERS
                    ),
                    mcp_headers=chat_message_req.mcp_headers,
                    approval_mode=approval_mode,
                ):
                    yield get_json_line(obj.model_dump())
            except Exception as e:
                logger.exception("Error in multi-model streaming")
                yield get_json_line(unhandled_stream_error(e).model_dump())

        return StreamingResponse(
            multi_model_stream_generator(), media_type="text/event-stream"
        )

    if is_multi_model and not chat_message_req.stream:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Multi-model mode (llm_overrides with >1 entry) requires stream=True.",
        )

    # Non-streaming path: consume all packets and return complete response
    if not chat_message_req.stream:
        if is_usage_limits_enabled():
            with get_session_with_current_tenant() as usage_db_session:
                check_usage_and_raise(
                    db_session=usage_db_session,
                    usage_type=UsageType.NON_STREAMING_API_CALLS,
                    tenant_id=tenant_id,
                    pending_amount=1,
                )
                increment_usage(
                    db_session=usage_db_session,
                    usage_type=UsageType.NON_STREAMING_API_CALLS,
                    amount=1,
                )
                usage_db_session.commit()

        result = run_chat_turn(
            new_msg_req=chat_message_req,
            user=user,
            litellm_additional_headers=get_relevant_headers(
                request.headers, LITELLM_PASS_THROUGH_HEADERS
            ),
            custom_tool_additional_headers=get_relevant_headers(
                request.headers, CUSTOM_TOOL_PASS_THROUGH_HEADERS
            ),
            mcp_headers=chat_message_req.mcp_headers,
            additional_context=chat_message_req.additional_context,
            approval_mode=approval_mode,
        )
        # CreateChatSessionID is only yielded for newly-created sessions, so for
        # follow-up messages on an existing session the aggregated response would
        # otherwise omit chat_session_id. Backfill it from the request so the
        # field is always present for non-streaming clients.
        if (
            result.chat_session_id is None
            and chat_message_req.chat_session_id is not None
        ):
            result.chat_session_id = chat_message_req.chat_session_id
        return result

    # Streaming path, normal Onyx UI behavior
    def stream_generator() -> Generator[str, None, None]:
        response_future = Future[ChatResponseOutcome]()
        # v2 re-shapes each object as an ACP update (acp_stream.py).
        acp = ChatAcpTranslator() if chat_message_req.protocol_version == 2 else None
        try:
            for obj in handle_stream_message_objects(
                new_msg_req=chat_message_req,
                user=user,
                litellm_additional_headers=get_relevant_headers(
                    request.headers, LITELLM_PASS_THROUGH_HEADERS
                ),
                custom_tool_additional_headers=get_relevant_headers(
                    request.headers, CUSTOM_TOOL_PASS_THROUGH_HEADERS
                ),
                mcp_headers=chat_message_req.mcp_headers,
                additional_context=chat_message_req.additional_context,
                response_future=response_future,
                approval_mode=approval_mode,
            ):
                if acp is None:
                    yield get_json_line(obj.model_dump())
                else:
                    for update in acp.translate(obj.model_dump()):
                        yield get_json_line(update)

        except Exception as e:
            logger.exception("Error in chat message streaming")
            error = unhandled_stream_error(e).model_dump()
            if acp is None:
                yield get_json_line(error)
            else:
                for update in acp.translate(error):
                    yield get_json_line(update)

        finally:
            logger.debug("Stream generator finished")

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.put("/set-message-as-latest")
def set_message_as_latest(
    message_identifier: ChatMessageIdentifier,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id

    chat_message = get_chat_message(
        chat_message_id=message_identifier.message_id,
        user_id=user_id,
        db_session=db_session,
    )

    set_as_latest_chat_message(
        chat_message=chat_message,
        user_id=user_id,
        db_session=db_session,
    )


@router.put("/set-preferred-response")
def set_preferred_response_endpoint(
    request_body: SetPreferredResponseRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> None:
    """Set the preferred assistant response for a multi-model turn."""
    try:
        # Ownership check: get_chat_message raises ValueError if the message
        # doesn't belong to this user, preventing cross-user mutation.
        get_chat_message(
            chat_message_id=request_body.user_message_id,
            user_id=user.id,
            db_session=db_session,
        )
        set_preferred_response(
            db_session=db_session,
            user_message_id=request_body.user_message_id,
            preferred_assistant_message_id=request_body.preferred_response_id,
        )
    except ValueError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e))


@router.post(
    "/create-chat-message-feedback",
    dependencies=get_feedback_rate_limiters(),
)
def create_chat_feedback(
    feedback: ChatFeedbackRequest,
    user: User = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id

    create_chat_message_feedback(
        is_positive=feedback.is_positive,
        feedback_text=feedback.feedback_text,
        predefined_feedback=feedback.predefined_feedback,
        chat_message_id=feedback.chat_message_id,
        user_id=user_id,
        db_session=db_session,
    )


@router.delete(
    "/remove-chat-message-feedback",
    dependencies=get_feedback_rate_limiters(),
)
def remove_chat_feedback(
    chat_message_id: int,
    user: User = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id

    remove_chat_message_feedback(
        chat_message_id=chat_message_id,
        user_id=user_id,
        db_session=db_session,
    )


class MaxSelectedDocumentTokens(BaseModel):
    max_tokens: int


@router.get("/max-selected-document-tokens")
def get_max_document_tokens(
    persona_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> MaxSelectedDocumentTokens:
    try:
        persona = get_persona_by_id(
            persona_id=persona_id,
            user=user,
            db_session=db_session,
            is_for_edit=False,
        )
    except ValueError:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Persona not found")

    return MaxSelectedDocumentTokens(
        max_tokens=_get_available_tokens_for_persona(
            persona=persona,
            user=user,
            db_session=db_session,
        ),
    )


"""Endpoints for chat seeding"""


class SeedChatFromSlackRequest(BaseModel):
    chat_session_id: UUID


class SeedChatFromSlackResponse(BaseModel):
    redirect_url: str


@router.post("/seed-chat-session-from-slack")
def seed_chat_from_slack(
    chat_seed_request: SeedChatFromSlackRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> SeedChatFromSlackResponse:
    slack_chat_session_id = chat_seed_request.chat_session_id
    new_chat_session = duplicate_chat_session_for_user_from_slack(
        db_session=db_session,
        user=user,
        chat_session_id=slack_chat_session_id,
    )

    add_chats_to_session_from_slack_thread(
        db_session=db_session,
        slack_chat_session_id=slack_chat_session_id,
        new_chat_session_id=new_chat_session.id,
    )

    return SeedChatFromSlackResponse(
        redirect_url=f"{WEB_DOMAIN}/chat?chatId={new_chat_session.id}"
    )


@router.get("/artifacts/{artifact_id}")
def get_chat_artifact(
    artifact_id: UUID,
    version: int | None = Query(None),
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> ChatArtifactFile:
    """A published file's version, by default its newest, and how the user
    may open it: the owner of its chat, a reader of that chat (a public
    share), or, for an explicit version, anyone who can download that
    version (`user_can_access_chat_file`), such as a reader of another chat
    that added it. 404 otherwise, and for a deleted chat; the web opens an
    artifact link with it."""
    found = get_chat_artifact_file(db_session, artifact_id, version)
    if found is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Artifact not found")
    chat, file = found
    access: ChatArtifactAccess
    if chat.user_id == user.id:
        access = "owner"
    elif user_can_read_chat_session(db_session, chat.id, user.id):
        access = "chat_reader"
    elif version is not None and user_can_access_chat_file(
        file.file_id, user, db_session
    ):
        access = "file_only"
    else:
        # The same 404, so callers cannot probe for artifacts of others.
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Artifact not found")
    return ChatArtifactFile(**file.model_dump(exclude={"display_path"}), access=access)


def _readable_chat_file_record(
    file_id: str, user: User, db_session: Session
) -> FileRecord:
    """The record of the chat file `file_id`, a stored file's id or a user
    file's id, when `user` can read it. Raises OnyxError NOT_FOUND
    otherwise, also for a file of another user, so callers cannot probe for
    files across ownership boundaries."""
    # For user files, we need to get the file id from the user file id
    file_id_from_user_file = get_file_id_by_user_file_id(file_id, db_session)
    if file_id_from_user_file:
        file_id = file_id_from_user_file
    if not user_can_access_chat_file(file_id, user, db_session):
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "File not found")
    file_record = get_default_file_store().read_file_record(file_id)
    if not file_record:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "File not found")
    return file_record


def _chat_file_preview_disposition(file_name: str) -> tuple[str, dict[str, str]]:
    """The media type and security headers of the PDF preview of the chat
    file named `file_name`: inline, named after the file with a .pdf
    extension."""
    return resolve_inline_disposition(
        PDF_MIME_TYPE, filename=f"{posixpath.splitext(file_name)[0]}.pdf"
    )


@router.get("/file/{file_id:path}", tags=PUBLIC_API_TAGS)
def fetch_chat_file(
    file_id: str,
    request: Request,
    parsed: bool = Query(False),
    preview: Annotated[Literal["pdf"] | None, Query()] = None,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> Response:
    """Download a chat file that you can read. `parsed=true` returns a
    spreadsheet as JSON sheets. `preview=pdf` returns the stored PDF preview
    of a PowerPoint or Word file of a chat upload or a published file, and
    never converts: 422 `PREVIEW_UNAVAILABLE` when the file can have no PDF
    preview (not such a file, or no upload or published file owns it, or its
    upload is being deleted), and 409 `PREVIEW_NOT_READY` when
    no PDF is stored yet: ask for it with `POST /chat/file/{file_id}/preview`.
    A file that you cannot read is 404."""
    file_record = _readable_chat_file_record(file_id, user, db_session)
    file_id = file_record.file_id
    file_store = get_default_file_store()
    file_name = file_record.display_name or file_id

    # `parsed` only changes behavior for spreadsheet files (xlsx is a binary zip
    # the frontend cannot render); everything else is served raw as usual.
    parse_spreadsheet = parsed and is_spreadsheet_mime_type(file_record.file_type)

    if preview is None:
        media_type, security_headers = resolve_inline_disposition(
            file_record.file_type,
            filename=ensure_filename_extension(file_name, file_record.file_type),
            attachment_types=ATTACHMENT_SAFE_MIME_TYPES,
            # A parsed spreadsheet is served as a JSON preview, not as the stored bytes.
            fallback_disposition=None if parse_spreadsheet else "attachment",
        )
        etag_variant = "-parsed" if parse_spreadsheet else ""
    else:
        media_type, security_headers = _chat_file_preview_disposition(file_name)
        etag_variant = "-preview-pdf"

    # Files served here are immutable (content-addressed by file_id), so allow long-lived caching.
    # Use `private` because this is behind auth / tenant scoping.
    etag: str = f'"{file_id}{etag_variant}-{RESPONSE_POLICY_VERSION}"'
    cache_headers: dict[str, str] = {
        "Cache-Control": "private, max-age=31536000, immutable",
        "ETag": etag,
        "Vary": "Cookie",
        **security_headers,
    }

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=cache_headers)

    if preview is not None:
        preview_row, _, _ = resolve_chat_file_preview(db_session, file_record)
        if preview_row.preview_file_id is None:
            raise OnyxError(
                OnyxErrorCode.PREVIEW_NOT_READY, "The PDF preview is not made yet"
            )
        # The link is written once, so the ETag names one PDF.
        return StreamingResponse(
            file_store.read_file(
                preview_row.preview_file_id, mode="b", use_tempfile=True
            ),
            media_type=media_type,
            headers=cache_headers,
        )

    if parse_spreadsheet:
        # Use a tempfile since openpyxl needs a seekable file and the workbook
        # may be large.
        with file_store.read_file(file_id, mode="b", use_tempfile=True) as xlsx_io:
            preview_sheets = parse_spreadsheet_for_preview(
                xlsx_io, file_record.display_name or ""
            )
        return JSONResponse(content=preview_sheets.model_dump(), headers=cache_headers)

    file_io = file_store.read_file(file_id, mode="b")
    return StreamingResponse(file_io, media_type=media_type, headers=cache_headers)


@router.post("/file/{file_id:path}/preview", tags=PUBLIC_API_TAGS)
def make_chat_file_preview(
    file_id: str,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> StreamingResponse:
    """The PDF preview of a PowerPoint or Word file of a chat upload or a
    published file that you can read: the stored PDF, else the PDF that the
    sandbox of the file's owner converts, which can take some seconds, and
    which later `GET /chat/file/{file_id}?preview=pdf` requests return.
    Errors: 404 for a file that you cannot read. 422 `PREVIEW_UNAVAILABLE`
    when the file has no PDF preview now (not such a file, no upload or
    published file owns it or its upload is being deleted, larger than the
    conversion limit, a file that the converter rejects or cannot
    convert within its time limit, or no sandbox in the deployment):
    download the file instead. 503 when the sandbox cannot start or be
    reached now: try again."""
    file_record = _readable_chat_file_record(file_id, user, db_session)
    media_type, security_headers = _chat_file_preview_disposition(
        file_record.display_name or file_record.file_id
    )
    return StreamingResponse(
        convert_chat_file_preview_pdf(db_session, file_record),
        media_type=media_type,
        headers={
            "Cache-Control": "private, no-store",
            "Vary": "Cookie",
            **security_headers,
        },
    )


@router.get("/search", tags=PUBLIC_API_TAGS)
def search_chats(
    query: str | None = Query(None),
    page: int = Query(1),
    page_size: int = Query(10),
    user: User = Depends(require_permission(Permission.READ_CHAT)),
    db_session: Session = Depends(get_session),
) -> ChatSearchResponse:
    """
    Search for chat sessions based on the provided query.
    If no query is provided, returns recent chat sessions.
    """

    # Use the enhanced database function for chat search
    chat_sessions, has_more = search_chat_sessions(
        user_id=user.id,
        db_session=db_session,
        query=query,
        page=page,
        page_size=page_size,
        include_deleted=False,
    )

    # Group chat sessions by time period
    today = datetime.datetime.now(datetime.UTC).date()
    yesterday = today - timedelta(days=1)
    this_week = today - timedelta(days=7)
    this_month = today - timedelta(days=30)

    today_chats: list[ChatSessionSummary] = []
    yesterday_chats: list[ChatSessionSummary] = []
    this_week_chats: list[ChatSessionSummary] = []
    this_month_chats: list[ChatSessionSummary] = []
    older_chats: list[ChatSessionSummary] = []

    for session in chat_sessions:
        session_date = session.time_created.astimezone(datetime.UTC).date()

        chat_summary = ChatSessionSummary(
            id=session.id,
            name=session.description,
            persona_id=session.persona_id,
            time_created=session.time_created,
            shared_status=session.shared_status,
            current_alternate_model=session.current_alternate_model,
            current_temperature_override=session.temperature_override,
            current_reasoning_effort_override=session.reasoning_effort_override,
        )

        if session_date == today:
            today_chats.append(chat_summary)
        elif session_date == yesterday:
            yesterday_chats.append(chat_summary)
        elif session_date > this_week:
            this_week_chats.append(chat_summary)
        elif session_date > this_month:
            this_month_chats.append(chat_summary)
        else:
            older_chats.append(chat_summary)

    # Create groups
    groups = []
    if today_chats:
        groups.append(ChatSessionGroup(title="Today", chats=today_chats))
    if yesterday_chats:
        groups.append(ChatSessionGroup(title="Yesterday", chats=yesterday_chats))
    if this_week_chats:
        groups.append(ChatSessionGroup(title="This Week", chats=this_week_chats))
    if this_month_chats:
        groups.append(ChatSessionGroup(title="This Month", chats=this_month_chats))
    if older_chats:
        groups.append(ChatSessionGroup(title="Older", chats=older_chats))

    return ChatSearchResponse(
        groups=groups,
        has_more=has_more,
        next_page=page + 1 if has_more else None,
    )


# ~32 KiB decompressed per chunk → ~1 MiB peak per read; a full-buffer replay
# would otherwise materialize up to the whole decompressed buffer at once.
_RESUME_MAX_CHUNKS_PER_READ = 32


@router.get("/chat-session/{session_id}/status", tags=PUBLIC_API_TAGS)
def get_chat_session_processing_status(
    session_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    user: User = Depends(
        require_permission(Permission.READ_CHAT, allow_anonymous=True)
    ),
) -> ChatSessionProcessingStatus:
    with get_session_with_current_tenant() as db_session:
        try:
            chat_session = get_chat_session_by_id(
                chat_session_id=session_id,
                user_id=user.id,
                db_session=db_session,
            )
        except ValueError as error:
            raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND) from error
        inbox = read_chat_inbox(db_session, session_id)
        # Read admission after input: a turn claims admission before it
        # consumes input, so a starting turn shows as startable input or as
        # processing.
        cache = get_cache_backend(operation_timeout_s=ADMISSION_CACHE_TIMEOUT_S)
        stream = get_processing_stream(session_id, cache)
        busy = stream is not None or is_chat_session_processing(session_id, cache)
        # Read the version after admission: a turn opens its requests before it
        # releases admission, so an idle result carries their version.
        version = approvals_version(db_session, session_id)
    resumes_root = any(run.is_root for run in inbox.resumable_runs)
    # Decided agents wait to resume; a parked agent that still waits for the
    # user does not count.
    resumes_agents = any(not run.is_root for run in inbox.resumable_runs)
    status = ChatSessionProcessingStatus(
        latest_response_id=inbox.selected_response_id,
        has_active_subagents=any(result.is_running for result in inbox.results)
        or bool(inbox.child_work)
        or resumes_agents,
        has_startable_input=inbox.next_turn is not None,
        # A decided root that waits to resume, such as after a failed start
        # that retries, keeps the chat processing.
        is_processing=busy or resumes_root,
        current_stream=CurrentStreamInfo(
            stream_id=stream.stream_id, response_ids=stream.response_ids
        )
        if stream is not None
        else None,
        approvals_version=version,
    )

    if (
        not busy
        and chat_session.user_id == user.id
        and user.id is not None
        and (
            inbox.next_turn is not None
            # A parked root response whose waits all ended continues.
            or resumes_root
            # Dispatch saves a response whose owner is gone as interrupted.
            or ownerless_response_ids(cache, inbox.unfinished_response_ids)
            # Agent work needs a host when no running child's store scans.
            or ((inbox.child_work or resumes_agents) and not inbox.running_response_ids)
        )
    ):
        # Queued work can outlive the process that completed its previous response.
        background_tasks.add_task(
            dispatch_pending_chat_messages,
            session_id,
            user.id,
            get_relevant_headers(request.headers, LITELLM_PASS_THROUGH_HEADERS),
            get_relevant_headers(request.headers, CUSTOM_TOOL_PASS_THROUGH_HEADERS),
        )
    return status


def _session_messages_and_packets(
    db_session: Session,
    session_id: UUID,
    user_id: UUID | None,
    message_ids: set[int] | None = None,
    root_session_id: UUID | None = None,
) -> tuple[list[ChatMessageDetail], list[list[Packet]]]:
    """A session's messages and each response's replay packets. The caller
    checked access to the session. With `root_session_id`, the session is one
    of that chat's subagents: its approvals live under the root, and its ended
    responses get the stop packet that a root's replay carries."""
    agent_session = root_session_id is not None
    session_messages = get_chat_messages_by_session(
        chat_session_id=session_id,
        user_id=user_id,
        db_session=db_session,
        message_ids=message_ids,
        agent_session=agent_session,
        skip_permission_check=True,
        # we need the tool call objs anyways, so just fetch them in a single call
        prefetch_top_two_level_tool_calls=True,
        prefetch_message_details=True,
        # the replay builds search and fetch packets from these
        prefetch_tool_call_search_docs=True,
    )
    details = [
        translate_db_message_to_chat_message_detail(msg) for msg in session_messages
    ]
    # Each response replays its tool calls for the frontend.
    tools_by_id = load_session_tools(session_messages, db_session)
    responses = [
        msg for msg in session_messages if msg.message_type == MessageType.ASSISTANT
    ]
    chat_approvals = load_chat_approvals(
        db_session, root_session_id or session_id, [msg.id for msg in responses]
    )
    child_responses = load_child_responses(db_session, responses)
    packets = [
        translate_assistant_message_to_packets(
            chat_message=msg,
            tools_by_id=tools_by_id,
            chat_approvals=chat_approvals,
            child_responses=child_responses,
            db_session=db_session,
        )
        for msg in responses
    ]
    if agent_session:
        # A child's saved output ends without the stop that a root's has; a
        # running response's comes from its live stream.
        for msg, response_packets in zip(responses, packets, strict=True):
            status = msg.response_status
            if (
                status is not None
                and (status.is_terminal or status == RunStatus.SUSPENDED)
                and not any(
                    isinstance(packet.obj, OverallStop) for packet in response_packets
                )
            ):
                response_packets.append(
                    Packet(
                        placement=Placement(turn_index=0),
                        obj=overall_stop(status, msg.response_failure),
                    )
                )
    return details, packets


@router.get("/chat-session/{session_id}/agents")
def get_chat_session_agents(
    session_id: UUID,
    user: User = Depends(
        require_permission(Permission.READ_CHAT, allow_anonymous=True)
    ),
) -> list[ChatSubagent]:
    """The background agents on the selected branch, newest first."""
    with get_session_with_current_tenant() as db_session:
        try:
            get_chat_session_by_id(
                chat_session_id=session_id, user_id=user.id, db_session=db_session
            )
        except ValueError as error:
            raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND) from error
        selected, branch = get_selected_branch(db_session, session_id)
    if selected is None:
        return []
    # Each loader opens its own session, so this one is closed first
    agents = [
        agent
        for agent in load_session_agent_metadata(
            selected.id, branch=branch, include_root=False
        )
        # `spawn_agent` children; Deep Research workers run in the foreground
        if isinstance(agent.restoration_config, ChatConfiguration)
    ]
    with get_session_with_current_tenant() as db_session:
        summaries = agent_run_summaries(
            db_session,
            [int(agent.latest_run_id) for agent in agents if agent.latest_run_id],
        )
    cache = get_cache_backend()
    subagents: list[ChatSubagent] = []
    for agent in agents:
        run_id = int(agent.latest_run_id) if agent.latest_run_id else None
        model, duration = (
            summaries.get(run_id, (None, None)) if run_id is not None else (None, None)
        )
        live = run_id is not None and (
            agent.status is None or not agent.status.is_terminal
        )
        pointer = (
            read_agent_stream_pointer(cache, run_id)
            if live and run_id is not None
            else None
        )
        subagents.append(
            ChatSubagent(
                id=UUID(agent.id),
                path=agent.path,
                status=agent.status,
                stopped_by_user=agent.failure_kind == RunFailureKind.STOPPED_BY_USER,
                started_at=agent.latest_run_started_at,
                latest_run_id=run_id,
                stream_id=pointer.stream_id if pointer else None,
                activity_tool=pointer.activity_tool if pointer else None,
                model=model,
                duration_seconds=duration,
            )
        )
    return subagents


def _authorized_agent(session_id: UUID, agent_id: UUID, user: User) -> None:
    """404 unless the agent is below the root of the user's chat."""
    with get_session_with_current_tenant() as db_session:
        try:
            get_chat_session_by_id(
                chat_session_id=session_id, user_id=user.id, db_session=db_session
            )
        except ValueError as error:
            raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND) from error
        if not agent_subtree_ids(db_session, session_id, agent_id):
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Agent not found")


def _live_response_id(latest: ChatMessage | None) -> int | None:
    """The response whose stream a subagent view may follow: one that has not
    ended. A worker that died leaves its pointer behind after recovery saves
    the failure, as the agents list knows."""
    if latest is None:
        return None
    status = latest.response_status
    return latest.id if status is None or not status.is_terminal else None


@router.get("/chat-session/{session_id}/agents/{agent_id}/history")
def get_chat_subagent_history(
    session_id: UUID,
    agent_id: UUID,
    user: User = Depends(
        require_permission(Permission.READ_CHAT, allow_anonymous=True)
    ),
) -> ChatSubagentHistory:
    """A background agent's saved conversation, in the chat page's format,
    with the live stream of its running response."""
    _authorized_agent(session_id, agent_id, user)
    with get_session_with_current_tenant() as db_session:
        # One agent can answer on several branches after an edit; show only
        # the selected one, as the agent list does.
        selected, branch = get_selected_branch(db_session, session_id)
        if selected is None:
            return ChatSubagentHistory(messages=[], packets=[], stream=None)
        latest = latest_agent_response(db_session, branch, str(agent_id))
        response_id = latest.id if latest is not None else None
        live_id = _live_response_id(latest)
        # Read the stream before the messages: a run releases its stream
        # after its terminal save, so a missing stream means saved output.
        pointer = (
            read_agent_stream_pointer(get_cache_backend(), live_id)
            if live_id is not None
            else None
        )
        messages, packets = _session_messages_and_packets(
            db_session,
            agent_id,
            user.id,
            message_ids=selected_agent_message_ids(db_session, branch, agent_id),
            root_session_id=session_id,
        )
    return ChatSubagentHistory(
        messages=messages,
        packets=packets,
        stream=CurrentStreamInfo(
            stream_id=pointer.stream_id, response_ids=[response_id]
        )
        if pointer is not None and response_id is not None
        else None,
    )


@router.get("/chat-session/{session_id}/agents/{agent_id}/stream")
def stream_chat_subagent(
    session_id: UUID,
    agent_id: UUID,
    stream_id: int = Query(..., gt=0),
    cursor: int = Query(0, ge=0),
    user: User = Depends(
        require_permission(Permission.READ_CHAT, allow_anonymous=True)
    ),
) -> StreamingResponse:
    """Replay a background agent's live stream from ``cursor`` and tail it,
    as ``resume-stream`` does for the root turn."""
    _authorized_agent(session_id, agent_id, user)
    with get_session_with_current_tenant() as db_session:
        selected, branch = get_selected_branch(db_session, session_id)
        latest = (
            latest_agent_response(db_session, branch, str(agent_id))
            if selected is not None
            else None
        )
        response_id = _live_response_id(latest)
    cache = get_cache_backend()

    def live() -> bool:
        pointer = (
            read_agent_stream_pointer(cache, response_id)
            if response_id is not None
            else None
        )
        return pointer is not None and pointer.stream_id == stream_id

    if not live():
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "No live stream for this agent")
    return _tail_stream_buffer(cache, agent_id, stream_id, cursor, live)


@router.get("/chat-session/{session_id}/resume-stream", tags=PUBLIC_API_TAGS)
def resume_chat_stream(
    session_id: UUID,
    cursor: int = Query(0, ge=0),
    expected_stream_id: int | None = Query(None, alias="stream_id", gt=0),
    user: User = Depends(
        require_permission(Permission.READ_CHAT, allow_anonymous=True)
    ),
) -> StreamingResponse:
    """Replay buffered output from ``cursor`` and tail it while its worker is live.
    Serves any pod: the buffer lives in the shared cache. 404 when nothing can
    be served at ``cursor``: no running stream, a different ``stream_id``, or
    a buffer that is missing or has a gap there. The client then refetches
    the session. A 200 stream starts with a cursor packet; a stream that ends
    without a stop packet lost its tail, and a resume from its last cursor gets
    output or 404."""
    # Short-lived session: a Depends(get_session) would stay checked out (idle
    # in transaction) for the lifetime of the SSE response.
    with get_session_with_current_tenant() as db_session:
        try:
            get_chat_session_by_id(
                chat_session_id=session_id,
                user_id=user.id,
                db_session=db_session,
            )
        except ValueError:
            raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND)

    cache = get_cache_backend()
    stream = get_processing_stream(session_id, cache)
    if stream is None or (
        expected_stream_id is not None and expected_stream_id != stream.stream_id
    ):
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND, "No resumable stream for this chat session"
        )
    return _tail_stream_buffer(
        cache,
        session_id,
        stream.stream_id,
        cursor,
        lambda: is_chat_session_processing(session_id, cache),
    )


def _tail_stream_buffer(
    cache: CacheBackend,
    buffer_session_id: UUID,
    stream_id: int,
    cursor: int,
    writer_live: Callable[[], bool],
) -> StreamingResponse:
    """Replay a stream buffer from ``cursor`` and tail it while ``writer_live``.
    404 when the buffer is missing or has a gap at ``cursor``."""
    first_read = read_stream_chunks(
        cache,
        buffer_session_id,
        stream_id,
        cursor,
        max_chunks=_RESUME_MAX_CHUNKS_PER_READ,
    )
    if first_read is None or first_read.gap or cursor > first_read.chunk_count:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND, "No resumable stream for this chat session"
        )
    # Freeze the restore boundary so new writes cannot prolong replay.
    replay_through = first_read.chunk_count

    def stream_buffered_run(read: StreamChunkRead) -> Generator[str, None, None]:
        chunk_cursor = cursor
        writer_stopped = False
        last_emit = time.monotonic()
        yield get_json_line(
            StreamCursor(
                stream_id=stream_id,
                next_cursor=chunk_cursor,
                replay_complete=chunk_cursor >= replay_through,
            ).model_dump()
        )
        while True:
            if read.blocks:
                yield "".join(read.blocks)
                chunk_cursor = read.next_cursor
                yield get_json_line(
                    StreamCursor(
                        stream_id=stream_id,
                        next_cursor=chunk_cursor,
                        replay_complete=chunk_cursor >= replay_through,
                    ).model_dump()
                )
                # Drain the backlog before sleeping; done is only trusted once
                # a read comes back empty (a capped read can precede the tail).
                last_emit = time.monotonic()
            elif read.done or writer_stopped:
                return
            elif not writer_live():
                # Drain once more after ownership ends to catch the writer's
                # last flush.
                writer_stopped = True
            else:
                now = time.monotonic()
                if now - last_emit >= CHAT_HEARTBEAT_INTERVAL_S:
                    yield get_json_line(heartbeat_packet().model_dump())
                    last_emit = now
                time.sleep(CHAT_RESUME_POLL_INTERVAL_S)
            next_read = read_stream_chunks(
                cache,
                buffer_session_id,
                stream_id,
                chunk_cursor,
                max_chunks=(
                    min(_RESUME_MAX_CHUNKS_PER_READ, replay_through - chunk_cursor)
                    if chunk_cursor < replay_through
                    else _RESUME_MAX_CHUNKS_PER_READ
                ),
            )
            # The buffer expired or broke: end the stream. A resume from the
            # last cursor gets 404, and the client refetches the session.
            if (
                next_read is None
                or next_read.gap
                or chunk_cursor > next_read.chunk_count
            ):
                return
            read = next_read

    return StreamingResponse(
        stream_buffered_run(first_read), media_type="text/event-stream"
    )


@router.post("/chat-session/{session_id}/pending-messages")
def submit_pending_chat_message(
    session_id: UUID,
    body: PendingChatMessageRequest,
    request: Request,
    user: User = Depends(require_permission(Permission.WRITE_CHAT)),
    db_session: Session = Depends(get_session),
    _rate_limit_check: None = Depends(check_token_rate_limits),
    _api_key_usage_check: None = Depends(check_api_key_usage),
) -> PendingChatMessage:
    """Submit text for the next step, normal completion, or interruption."""
    chat_session = get_human_input_session(db_session, session_id, user)
    _reject_while_user_input_waits(db_session, session_id)
    cache = get_cache_backend()
    pending = submit_human_message__no_commit(
        db_session,
        session_id,
        message=process_chat_query(body.message, chat_session, user, db_session),
        delivery=body.delivery,
        target_response_id=body.target_response_id,
        # A turn that holds admission without a stream has no response yet.
        turn_preparing=is_chat_session_processing(session_id, cache)
        and get_processing_stream(session_id, cache) is None,
        deep_research=body.deep_research,
        llm_override=body.llm_override,
        mentions=body.mentions,
    )
    # The interrupt stops the turn running at commit, never the turn it starts.
    interrupted = current_turn_owner(session_id, cache)
    db_session.commit()
    if pending.delivery == MessageDelivery.INTERRUPT and interrupted is not None:
        stop_current_turn(session_id, cache, owner=interrupted)
    dispatch_pending_chat_messages(
        session_id,
        user.id,
        get_relevant_headers(request.headers, LITELLM_PASS_THROUGH_HEADERS),
        get_relevant_headers(request.headers, CUSTOM_TOOL_PASS_THROUGH_HEADERS),
    )
    return pending


@router.get("/chat-session/{session_id}/pending-messages")
def list_pending_chat_messages(
    session_id: UUID,
    user: User = Depends(require_permission(Permission.READ_CHAT)),
    db_session: Session = Depends(get_session),
) -> list[PendingChatMessage]:
    get_human_input_session(db_session, session_id, user)
    return list_human_messages(db_session, session_id)


@router.delete("/chat-session/{session_id}/pending-messages/{message_id}")
def withdraw_pending_chat_message(
    session_id: UUID,
    message_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.WRITE_CHAT)),
    db_session: Session = Depends(get_session),
) -> PendingChatMessage:
    """Remove pending input and return its text for local editing or discarding."""
    get_human_input_session(db_session, session_id, user)
    pending = withdraw_human_message__no_commit(db_session, session_id, message_id)
    db_session.commit()
    dispatch_pending_chat_messages(
        session_id,
        user.id,
        get_relevant_headers(request.headers, LITELLM_PASS_THROUGH_HEADERS),
        get_relevant_headers(request.headers, CUSTOM_TOOL_PASS_THROUGH_HEADERS),
    )
    return pending


@router.post("/chat-session/{session_id}/pending-messages/{message_id}/interrupt")
def interrupt_with_pending_chat_message(
    session_id: UUID,
    message_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.WRITE_CHAT)),
    db_session: Session = Depends(get_session),
    _rate_limit_check: None = Depends(check_token_rate_limits),
    _api_key_usage_check: None = Depends(check_api_key_usage),
) -> PendingChatMessage:
    """Stop current work; the message starts the next turn."""
    get_human_input_session(db_session, session_id, user)
    _reject_while_user_input_waits(db_session, session_id)
    pending = interrupt_human_message__no_commit(db_session, session_id, message_id)
    cache = get_cache_backend()
    # The interrupt stops the turn running at commit, never the turn it starts.
    interrupted = current_turn_owner(session_id, cache)
    db_session.commit()
    if interrupted is not None:
        stop_current_turn(session_id, cache, owner=interrupted)
    dispatch_pending_chat_messages(
        session_id,
        user.id,
        get_relevant_headers(request.headers, LITELLM_PASS_THROUGH_HEADERS),
        get_relevant_headers(request.headers, CUSTOM_TOOL_PASS_THROUGH_HEADERS),
    )
    return pending


@router.patch("/chat-session/{session_id}/tool-options")
def update_chat_tool_options(
    session_id: UUID,
    body: ToolOptions,
    user: User = Depends(require_permission(Permission.WRITE_CHAT)),
    db_session: Session = Depends(get_session),
) -> ToolOptions | None:
    """Save the fields of the chat's tool options that the body sets.

    Returns the stored options, or None for a chat that stores none.
    """
    if user.is_anonymous or user.id is None:
        raise OnyxError(OnyxErrorCode.UNAUTHORIZED, "Sign in to save tool options")
    chat_session = get_owned_chat_session(session_id, user.id, db_session)
    if chat_session is None or chat_session.deleted:
        raise OnyxError(OnyxErrorCode.SESSION_NOT_FOUND, "Chat session not found")
    stored = set_chat_session_tool_options__no_commit(
        db_session, session_id, body, user
    )
    if db_session.dirty:
        db_session.commit()
    return stored


@router.post("/chat-session/{session_id}/stop-subagents")
def stop_chat_subagents(
    session_id: UUID,
    body: StopSubagentsRequest | None = None,
    user: User = Depends(require_permission(Permission.WRITE_CHAT)),
    db_session: Session = Depends(get_session),
) -> StopSubagentsResponse:
    """Stop every active background agent on the selected branch, parked
    ones included, or only the body's agent and the agents below it.

    The root turn and its foreground workers keep running. Pending work for
    the stopped agents is dropped. The requests that the agents wait on end
    as the user's rejection. A stopped agent's result wakes no agent; its
    parent reads it as a notice at its next step.
    """
    get_human_input_session(db_session, session_id, user)
    cache = get_cache_backend()
    lock_agent(db_session, str(session_id))
    agent_ids: set[UUID] | None = None
    if body is not None and body.agent_id is not None:
        agent_ids = agent_subtree_ids(db_session, session_id, body.agent_id)
        if not agent_ids:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Agent not found")
    _, branch = get_selected_branch(db_session, session_id)
    stopped = active_agent_response_ids(db_session, branch.message_ids, agent_ids)
    drop_agent_work__no_commit(db_session, branch, agent_ids)
    close_pending_approval_requests__no_commit(
        db_session,
        ApprovalDecision.REJECTED,
        ApprovalDecidedVia.USER,
        chat_message_ids=stopped,
    )
    # Spawns check their parent's Stop after the chat lock, so the keys go first.
    for response_id in stopped:
        request_response_stop(cache, response_id, "user")
    db_session.commit()
    for response_id in stopped:
        stop_response(cache, get_current_tenant_id(), response_id, "user")
    return StopSubagentsResponse(stopped_count=len(stopped))


@router.post("/approvals/{approval_id}/decision", tags=PUBLIC_API_TAGS)
def decide_approval(
    approval_id: UUID,
    body: ChatApprovalDecisionRequest,
    request: Request,
    user: User = Depends(require_permission(Permission.WRITE_CHAT)),
    db_session: Session = Depends(get_session),
) -> ApprovalDecisionResponse:
    """Approve or reject an action in a chat that waits for the user.

    The decision is saved. Once no request of its response waits, the response
    continues under a new stream ID. `continuation` names that stream when this
    decision started it or found it running; the chat session's status names
    it too. Only the decision's `mcp_headers` reach the MCP servers of a
    continuation that this route starts; a continuation that another request
    starts, such as a status read, has none. Repeating a saved decision returns it, also after the
    response ends or the action policies change; a different one, or a
    request that is no longer waiting, is a conflict. Approving an action that
    the current action policies block saves a rejection by the policy
    (`decided_via` POLICY). The headers are not saved.
    """
    approval = get_approval_request_for_user(db_session, approval_id, user.id)
    if approval is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Approval request not found")
    rejected = body.decision == ApprovalChoice.REJECT
    upgrades_to_grant = (
        body.decision == ApprovalChoice.APPROVE_SESSION
        and approval.decision == ApprovalDecision.APPROVED
        and approval.decided_via == ApprovalDecidedVia.USER
    )
    if approval.decision is None or upgrades_to_grant:
        blocked = action_now_blocked(
            db_session,
            integration_id=approval.integration_id,
            action_id=approval.action_id,
            user_id=user.id,
            chat_session_id=approval.chat_session_id,
        )
        record_approval_decision__no_commit(
            db_session,
            approval,
            ApprovalDecision.REJECTED
            if rejected or blocked
            else ApprovalDecision.APPROVED,
            ApprovalDecidedVia.POLICY
            if blocked and not rejected
            else ApprovalDecidedVia.SESSION_GRANT
            if body.decision == ApprovalChoice.APPROVE_SESSION
            else ApprovalDecidedVia.USER,
        )
    db_session.refresh(approval)
    decided_via = approval.decided_via
    # The answer to this body: an approval that a policy blocked was saved as
    # a rejection. A saved answer also comes from an earlier attempt, a session
    # grant from another request, or a concurrent decision.
    decision = (
        ApprovalDecision.REJECTED
        if rejected or decided_via == ApprovalDecidedVia.POLICY
        else ApprovalDecision.APPROVED
    )
    if decided_via is None or approval.decision != decision:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "This request was already decided or is no longer waiting",
        )
    return ApprovalDecisionResponse(
        approval_id=approval_id,
        decision=decision,
        decided_via=decided_via,
        continuation=_continue_response(
            db_session,
            request,
            user,
            approval.chat_session_id,
            approval.chat_message_id,
            body.mcp_headers,
        ),
    )


def _continue_response(
    db_session: Session,
    request: Request,
    user: User,
    chat_session_id: UUID,
    response_id: int,
    mcp_headers: dict[str, str] | None,
) -> CurrentStreamInfo | None:
    """Commit the user's input to a waiting response and dispatch, so the
    response continues once nothing of it waits. Returns the stream that
    continues it, when this dispatch started it or found it running."""
    db_session.commit()
    dispatch_pending_chat_messages(
        chat_session_id,
        user.id,
        get_relevant_headers(request.headers, LITELLM_PASS_THROUGH_HEADERS),
        get_relevant_headers(request.headers, CUSTOM_TOOL_PASS_THROUGH_HEADERS),
        mcp_headers=mcp_headers,
        decided_response_id=response_id,
    )
    stream = get_processing_stream(
        chat_session_id,
        get_cache_backend(operation_timeout_s=ADMISSION_CACHE_TIMEOUT_S),
    )
    return (
        CurrentStreamInfo(stream_id=stream.stream_id, response_ids=stream.response_ids)
        if stream is not None and stream.resumed and response_id in stream.response_ids
        else None
    )


@router.post("/question-requests/{question_request_id}/answers", tags=PUBLIC_API_TAGS)
def answer_questions(
    question_request_id: UUID,
    body: ChatQuestionAnswersRequest,
    request: Request,
    user: User = Depends(require_permission(Permission.WRITE_CHAT)),
    db_session: Session = Depends(get_session),
) -> QuestionAnswersResponse:
    """Answer the questions that a chat response's agent asked the user.

    `answers` answer this request's questions from its card: each question
    once, with its option labels, a note, or both. A question takes one option
    label at most, or several when its `multi_select` is true. A `message` is text
    that the user typed in the chat instead: it answers every question of the
    response that waits, and the agent reads it as the user typed it. A
    message is a conflict (APPROVAL_PENDING) while an approval request of the
    response, or of a foreground run that it waits for, waits.

    The answer is saved. Once nothing of its response waits, the response
    continues under a new stream ID; `continuation` names that stream when
    this answer started it or found it running. Only the answer's
    `mcp_headers` reach the MCP servers of a continuation that this route
    starts; they are not saved. Repeating a saved answer returns it, also
    after the response ends; a different one, or a question that no longer
    waits, is a conflict.
    """
    question = get_question_request_for_user(db_session, question_request_id, user.id)
    if question is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, "Question request not found")
    chat_session = get_chat_session_by_id(
        chat_session_id=question.chat_session_id,
        user_id=user.id,
        db_session=db_session,
    )
    saved = SavedToolQuestion.model_validate(question)
    response_id = question.chat_message_id
    if body.message is not None:
        # The admin's query hook sees typed text, as it sees a chat message.
        message = chat_message_content(
            process_chat_query(
                sanitize_string(body.message), chat_session, user, db_session
            )
        )

        asked_at = question.created_at

        def answered_by_message() -> bool:
            # Only a message saved after this question was asked can be a
            # repeat; the same text for a later question answers it.
            return any(
                row.answered_via == QuestionAnsweredVia.MESSAGE
                and row.message == message
                and row.resolved_at is not None
                and row.resolved_at >= asked_at
                for row in get_response_question_requests(db_session, [response_id])
            )

        # A message answers every question of the response that waits; a
        # retry of it answers none asked since.
        answered = (
            []
            if answered_by_message()
            else resolve_question_requests__no_commit(
                db_session,
                QuestionOutcome.ANSWERED,
                chat_message_ids=[response_id],
                answered_via=QuestionAnsweredVia.MESSAGE,
                message=message,
            )
        )
        # The request's session rolls back the answers.
        if answered and parked_tree_approval_ids(db_session, [response_id]):
            raise OnyxError(
                OnyxErrorCode.APPROVAL_PENDING,
                "Approve or reject the pending requests before you answer "
                "with a message",
            )
        # A repeat, also of a message that a concurrent request saved,
        # returns it.
        conflict = not answered and not answered_by_message()
    else:
        answers = [
            answer.model_copy(
                update={
                    "user_note": chat_message_content(
                        process_chat_query(
                            sanitize_string(answer.user_note),
                            chat_session,
                            user,
                            db_session,
                        )
                    )
                    if answer.user_note
                    else answer.user_note
                }
            )
            for answer in card_answers(saved.questions, body.answers or [])
        ]
        answered = resolve_question_requests__no_commit(
            db_session,
            QuestionOutcome.ANSWERED,
            question_request_ids=[question_request_id],
            answered_via=QuestionAnsweredVia.CARD,
            answers=[answer.model_dump(mode="json") for answer in answers],
        )
        if not answered:
            # A repeat, also of answers that a concurrent request saved,
            # returns them.
            db_session.refresh(question)
            saved = SavedToolQuestion.model_validate(question)
        conflict = not answered and (saved.answered_via, saved.answers) != (
            QuestionAnsweredVia.CARD,
            answers,
        )
    if conflict:
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "This question was already answered or is no longer waiting",
        )
    return QuestionAnswersResponse(
        question_request_id=question_request_id,
        continuation=_continue_response(
            db_session,
            request,
            user,
            question.chat_session_id,
            response_id,
            body.mcp_headers,
        ),
    )


@router.post("/stop-chat-session/{chat_session_id}", tags=PUBLIC_API_TAGS)
def stop_chat_session(
    chat_session_id: UUID,
    stream_id: int | None = Query(default=None, gt=0),
    user: User = Depends(require_permission(Permission.WRITE_CHAT)),
    db_session: Session = Depends(get_session),
) -> StopChatResponse:
    """Stop one stream, or without `stream_id` the chat's current turn.

    Without `stream_id`, Stop also pauses the queue, whether or not a turn is
    running; saved responses keep their status.
    """
    try:
        get_chat_session_by_id(
            chat_session_id=chat_session_id,
            user_id=user.id,
            db_session=db_session,
        )
    except ValueError as error:
        raise OnyxError(
            OnyxErrorCode.SESSION_NOT_FOUND, "Chat session not found"
        ) from error

    if stream_id is None:

        def pause_queue() -> None:
            pause_chat_queue__no_commit(db_session, chat_session_id)
            db_session.commit()

        stop_current_turn(chat_session_id, get_cache_backend(), pause_queue=pause_queue)
    else:
        request_stop(chat_session_id, get_cache_backend(), stream_id=stream_id)
    return StopChatResponse(message="Chat session stopped")
