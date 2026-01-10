import datetime
import json
import os
from collections.abc import Generator
from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Query
from fastapi import Request
from fastapi import Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from redis.client import Redis
from sqlalchemy.orm import Session

from onyx.auth.api_key import get_hashed_api_key_from_request
from onyx.auth.pat import get_hashed_pat_from_request
from onyx.auth.users import current_chat_accessible_user
from onyx.auth.users import current_user
from onyx.chat.chat_state import ChatStateContainer
from onyx.chat.chat_utils import create_chat_history_chain
from onyx.chat.chat_utils import create_chat_session_from_request
from onyx.chat.chat_utils import extract_headers
from onyx.chat.models import ChatFullResponse
from onyx.chat.models import CreateChatSessionID
from onyx.chat.process_message import gather_stream_full
from onyx.chat.process_message import handle_stream_message_objects
from onyx.chat.process_message import stream_chat_message_objects
from onyx.chat.prompt_utils import get_default_base_system_prompt
from onyx.chat.stop_signal_checker import set_fence
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.chat_configs import HARD_DELETE_CHATS
from onyx.configs.constants import MessageType
from onyx.configs.constants import MilestoneRecordType
from onyx.configs.model_configs import LITELLM_PASS_THROUGH_HEADERS
from onyx.db.chat import add_chats_to_session_from_slack_thread
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import delete_all_chat_sessions_for_user
from onyx.db.chat import delete_chat_session
from onyx.db.chat import duplicate_chat_session_for_user_from_slack
from onyx.db.chat import get_chat_message
from onyx.db.chat import get_chat_messages_by_session
from onyx.db.chat import get_chat_session_by_id
from onyx.db.chat import get_chat_sessions_by_user
from onyx.db.chat import get_or_create_root_message
from onyx.db.chat import set_as_latest_chat_message
from onyx.db.chat import translate_db_message_to_chat_message_detail
from onyx.db.chat import update_chat_session
from onyx.db.chat_search import search_chat_sessions
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.feedback import create_chat_message_feedback
from onyx.db.feedback import create_doc_retrieval_feedback
from onyx.db.feedback import remove_chat_message_feedback
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.usage import increment_usage
from onyx.db.usage import UsageType
from onyx.db.user_file import get_file_id_by_user_file_id
from onyx.file_processing.extract_file_text import docx_to_txt_filename
from onyx.file_store.file_store import get_default_file_store
from onyx.llm.constants import LlmProviderNames
from onyx.llm.factory import get_default_llm
from onyx.llm.factory import get_llm_for_persona
from onyx.llm.factory import get_llm_token_counter
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.redis.redis_pool import get_redis_client
from onyx.secondary_llm_flows.chat_session_naming import (
    get_renamed_conversation_name,
)
from onyx.server.api_key_usage import check_api_key_usage
from onyx.server.query_and_chat.models import ChatFeedbackRequest
from onyx.server.query_and_chat.models import ChatMessageIdentifier
from onyx.server.query_and_chat.models import ChatRenameRequest
from onyx.server.query_and_chat.models import ChatSearchResponse
from onyx.server.query_and_chat.models import ChatSessionCreationRequest
from onyx.server.query_and_chat.models import ChatSessionDetailResponse
from onyx.server.query_and_chat.models import ChatSessionDetails
from onyx.server.query_and_chat.models import ChatSessionGroup
from onyx.server.query_and_chat.models import ChatSessionsResponse
from onyx.server.query_and_chat.models import ChatSessionSummary
from onyx.server.query_and_chat.models import ChatSessionUpdateRequest
from onyx.server.query_and_chat.models import CreateChatMessageRequest
from onyx.server.query_and_chat.models import LLMOverride
from onyx.server.query_and_chat.models import MessageOrigin
from onyx.server.query_and_chat.models import PromptOverride
from onyx.server.query_and_chat.models import RenameChatSessionResponse
from onyx.server.query_and_chat.models import SearchFeedbackRequest
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.models import UpdateChatSessionTemperatureRequest
from onyx.server.query_and_chat.models import UpdateChatSessionThreadRequest
from onyx.server.query_and_chat.session_loading import (
    translate_assistant_message_to_packets,
)
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.token_limit import check_token_rate_limits
from onyx.server.usage_limits import check_usage_and_raise
from onyx.server.usage_limits import is_usage_limits_enabled
from onyx.server.utils import get_json_line
from onyx.server.utils import PUBLIC_API_TAGS
from onyx.utils.headers import get_custom_tool_additional_request_headers
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import mt_cloud_telemetry
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/chat")


def _get_available_tokens_for_persona(
    persona: Persona,
    db_session: Session,
    user: User | None,
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

    llm = get_llm_for_persona(persona=persona, user=user)
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
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
    project_id: int | None = None,
    only_non_project_chats: bool = True,
    include_failed_chats: bool = False,
) -> ChatSessionsResponse:
    user_id = user.id if user is not None else None

    try:
        chat_sessions = get_chat_sessions_by_user(
            user_id=user_id,
            deleted=False,
            db_session=db_session,
            project_id=project_id,
            only_non_project_chats=only_non_project_chats,
            include_failed_chats=include_failed_chats,
        )

    except ValueError:
        raise ValueError("Chat session does not exist or has been deleted")

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
            )
            for chat in chat_sessions
        ]
    )


@router.put("/update-chat-session-temperature")
def update_chat_session_temperature(
    update_thread_req: UpdateChatSessionTemperatureRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    chat_session = get_chat_session_by_id(
        chat_session_id=update_thread_req.chat_session_id,
        user_id=user.id if user is not None else None,
        db_session=db_session,
    )

    # Validate temperature_override
    if update_thread_req.temperature_override is not None:
        if (
            update_thread_req.temperature_override < 0
            or update_thread_req.temperature_override > 2
        ):
            raise HTTPException(
                status_code=400, detail="Temperature must be between 0 and 2"
            )

        # Additional check for Anthropic models
        if (
            chat_session.current_alternate_model
            and LlmProviderNames.ANTHROPIC
            in chat_session.current_alternate_model.lower()
        ):
            if update_thread_req.temperature_override > 1:
                raise HTTPException(
                    status_code=400,
                    detail="Temperature for Anthropic models must be between 0 and 1",
                )

    chat_session.temperature_override = update_thread_req.temperature_override

    db_session.add(chat_session)
    db_session.commit()


@router.put("/update-chat-session-model")
def update_chat_session_model(
    update_thread_req: UpdateChatSessionThreadRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    chat_session = get_chat_session_by_id(
        chat_session_id=update_thread_req.chat_session_id,
        user_id=user.id if user is not None else None,
        db_session=db_session,
    )
    chat_session.current_alternate_model = update_thread_req.new_alternate_model

    db_session.add(chat_session)
    db_session.commit()


@router.get("/get-chat-session/{session_id}", tags=PUBLIC_API_TAGS)
def get_chat_session(
    session_id: UUID,
    is_shared: bool = False,
    include_deleted: bool = False,
    user: User | None = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionDetailResponse:
    user_id = user.id if user is not None else None
    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=session_id,
            user_id=user_id,
            db_session=db_session,
            is_shared=is_shared,
            include_deleted=include_deleted,
        )
    except ValueError:
        raise ValueError("Chat session does not exist or has been deleted")

    # for chat-seeding: if the session is unassigned, assign it now. This is done here
    # to avoid another back and forth between FE -> BE before starting the first
    # message generation
    if chat_session.user_id is None and user_id is not None:
        chat_session.user_id = user_id
        db_session.commit()

    session_messages = get_chat_messages_by_session(
        chat_session_id=session_id,
        user_id=user_id,
        db_session=db_session,
        # we already did a permission check above with the call to
        # `get_chat_session_by_id`, so we can skip it here
        skip_permission_check=True,
        # we need the tool call objs anyways, so just fetch them in a single call
        prefetch_top_two_level_tool_calls=True,
    )

    # Convert messages to ChatMessageDetail format
    chat_message_details = [
        translate_db_message_to_chat_message_detail(msg) for msg in session_messages
    ]

    # Every assistant message might have a set of tool calls associated with it, these need to be replayed back for the frontend
    # Each list is the set of tool calls for the given assistant message.
    replay_packet_lists: list[list[Packet]] = []
    for msg in session_messages:
        if msg.message_type == MessageType.ASSISTANT:
            replay_packet_lists.append(
                translate_assistant_message_to_packets(
                    chat_message=msg, db_session=db_session
                )
            )
            # msg_packet_list.append(Packet(ind=end_step_nr, obj=OverallStop()))

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
        deleted=chat_session.deleted,
        # Packets are now directly serialized as Packet Pydantic models
        packets=replay_packet_lists,
    )


@router.post("/create-chat-session", tags=PUBLIC_API_TAGS)
def create_new_chat_session(
    chat_session_creation_request: ChatSessionCreationRequest,
    user: User | None = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> CreateChatSessionID:
    user_id = user.id if user is not None else None

    try:
        new_chat_session = create_chat_session_from_request(
            chat_session_request=chat_session_creation_request,
            user_id=user_id,
            db_session=db_session,
        )
    except ValueError as e:
        # Project access denied
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=400, detail="Invalid Persona provided.")

    return CreateChatSessionID(chat_session_id=new_chat_session.id)


@router.put("/rename-chat-session")
def rename_chat_session(
    rename_req: ChatRenameRequest,
    request: Request,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> RenameChatSessionResponse:
    name = rename_req.name
    chat_session_id = rename_req.chat_session_id
    user_id = user.id if user is not None else None

    if name:
        update_chat_session(
            db_session=db_session,
            user_id=user_id,
            chat_session_id=chat_session_id,
            description=name,
        )
        return RenameChatSessionResponse(new_name=name)

    full_history = create_chat_history_chain(
        chat_session_id=chat_session_id, db_session=db_session
    )

    llm = get_default_llm(
        additional_headers=extract_headers(
            request.headers, LITELLM_PASS_THROUGH_HEADERS
        )
    )

    # Check LLM cost limits before using the LLM (only for Onyx-managed keys)
    from onyx.server.usage_limits import check_llm_cost_limit_for_provider

    check_llm_cost_limit_for_provider(
        db_session=db_session,
        tenant_id=get_current_tenant_id(),
        llm_provider_api_key=llm.config.api_key,
    )

    new_name = get_renamed_conversation_name(full_history=full_history, llm=llm)

    update_chat_session(
        db_session=db_session,
        user_id=user_id,
        chat_session_id=chat_session_id,
        description=new_name,
    )

    return RenameChatSessionResponse(new_name=new_name)


@router.patch("/chat-session/{session_id}")
def patch_chat_session(
    session_id: UUID,
    chat_session_update_req: ChatSessionUpdateRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user is not None else None
    update_chat_session(
        db_session=db_session,
        user_id=user_id,
        chat_session_id=session_id,
        sharing_status=chat_session_update_req.sharing_status,
    )
    return None


@router.delete("/delete-all-chat-sessions", tags=PUBLIC_API_TAGS)
def delete_all_chat_sessions(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        delete_all_chat_sessions_for_user(user=user, db_session=db_session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/delete-chat-session/{session_id}", tags=PUBLIC_API_TAGS)
def delete_chat_session_by_id(
    session_id: UUID,
    hard_delete: bool | None = None,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user is not None else None
    try:
        # Use the provided hard_delete parameter if specified, otherwise use the default config
        actual_hard_delete = (
            hard_delete if hard_delete is not None else HARD_DELETE_CHATS
        )
        delete_chat_session(
            user_id, session_id, db_session, hard_delete=actual_hard_delete
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# WARNING: this endpoint is deprecated and will be removed soon. Use the new send-chat-message endpoint instead.
@router.post("/send-message")
def handle_new_chat_message(
    chat_message_req: CreateChatMessageRequest,
    request: Request,
    user: User | None = Depends(current_chat_accessible_user),
    _rate_limit_check: None = Depends(check_token_rate_limits),
    _api_key_usage_check: None = Depends(check_api_key_usage),
) -> StreamingResponse:
    """
    This endpoint is both used for all the following purposes:
    - Sending a new message in the session
    - Regenerating a message in the session (just send the same one again)
    - Editing a message (similar to regenerating but sending a different message)
    - Kicking off a seeded chat session (set `use_existing_user_message`)

    Assumes that previous messages have been set as the latest to minimize overhead.

    Args:
        chat_message_req (CreateChatMessageRequest): Details about the new chat message.
        request (Request): The current HTTP request context.
        user (User | None): The current user, obtained via dependency injection.
        _ (None): Rate limit check is run if user/group/global rate limits are enabled.

    Returns:
        StreamingResponse: Streams the response to the new chat message.
    """
    tenant_id = get_current_tenant_id()
    logger.debug(f"Received new chat message: {chat_message_req.message}")

    if not chat_message_req.message and not chat_message_req.use_existing_user_message:
        raise HTTPException(status_code=400, detail="Empty chat message is invalid")

    mt_cloud_telemetry(
        tenant_id=tenant_id,
        distinct_id=user.email if user else tenant_id,
        event=MilestoneRecordType.RAN_QUERY,
    )

    def stream_generator() -> Generator[str, None, None]:
        try:
            with get_session_with_current_tenant() as db_session:
                for obj in stream_chat_message_objects(
                    new_msg_req=chat_message_req,
                    user=user,
                    db_session=db_session,
                    litellm_additional_headers=extract_headers(
                        request.headers, LITELLM_PASS_THROUGH_HEADERS
                    ),
                    custom_tool_additional_headers=get_custom_tool_additional_request_headers(
                        request.headers
                    ),
                ):
                    yield get_json_line(obj.model_dump())

        except Exception as e:
            logger.exception("Error in chat message streaming")
            yield json.dumps({"error": str(e)})

        finally:
            logger.debug("Stream generator finished")

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.post("/send-chat-message", response_model=None, tags=PUBLIC_API_TAGS)
def handle_send_chat_message(
    chat_message_req: SendMessageRequest,
    request: Request,
    user: User | None = Depends(current_chat_accessible_user),
    _rate_limit_check: None = Depends(check_token_rate_limits),
    _api_key_usage_check: None = Depends(check_api_key_usage),
) -> StreamingResponse | ChatFullResponse:
    """
    This endpoint is used to send a new chat message.

    Args:
        chat_message_req (SendMessageRequest): Details about the new chat message.
            - When stream=True (default): Returns StreamingResponse with SSE
            - When stream=False: Returns ChatFullResponse with complete data
        request (Request): The current HTTP request context.
        user (User | None): The current user, obtained via dependency injection.
        _ (None): Rate limit check is run if user/group/global rate limits are enabled.

    Returns:
        StreamingResponse | ChatFullResponse: Either streams or returns complete response.
    """
    logger.debug(f"Received new chat message: {chat_message_req.message}")

    tenant_id = get_current_tenant_id()
    mt_cloud_telemetry(
        tenant_id=tenant_id,
        distinct_id=user.email if user else tenant_id,
        event=MilestoneRecordType.RAN_QUERY,
    )

    # Override origin to API when authenticated via API key or PAT
    # to prevent clients from polluting telemetry data
    if get_hashed_api_key_from_request(request) or get_hashed_pat_from_request(request):
        chat_message_req.origin = MessageOrigin.API

    # Non-streaming path: consume all packets and return complete response
    if not chat_message_req.stream:
        with get_session_with_current_tenant() as db_session:
            # Check and track non-streaming API usage limits
            if is_usage_limits_enabled():
                check_usage_and_raise(
                    db_session=db_session,
                    usage_type=UsageType.NON_STREAMING_API_CALLS,
                    tenant_id=tenant_id,
                    pending_amount=1,
                )
                increment_usage(
                    db_session=db_session,
                    usage_type=UsageType.NON_STREAMING_API_CALLS,
                    amount=1,
                )
                db_session.commit()

            state_container = ChatStateContainer()
            packets = handle_stream_message_objects(
                new_msg_req=chat_message_req,
                user=user,
                db_session=db_session,
                litellm_additional_headers=extract_headers(
                    request.headers, LITELLM_PASS_THROUGH_HEADERS
                ),
                custom_tool_additional_headers=get_custom_tool_additional_request_headers(
                    request.headers
                ),
                external_state_container=state_container,
            )
            result = gather_stream_full(packets, state_container)
            # Note: LLM cost tracking is now handled in multi_llm.py
            return result

    # Streaming path, normal Onyx UI behavior
    def stream_generator() -> Generator[str, None, None]:
        state_container = ChatStateContainer()
        try:
            with get_session_with_current_tenant() as db_session:
                for obj in handle_stream_message_objects(
                    new_msg_req=chat_message_req,
                    user=user,
                    db_session=db_session,
                    litellm_additional_headers=extract_headers(
                        request.headers, LITELLM_PASS_THROUGH_HEADERS
                    ),
                    custom_tool_additional_headers=get_custom_tool_additional_request_headers(
                        request.headers
                    ),
                    external_state_container=state_container,
                ):
                    yield get_json_line(obj.model_dump())
                # Note: LLM cost tracking is now handled in multi_llm.py

        except Exception as e:
            logger.exception("Error in chat message streaming")
            yield json.dumps({"error": str(e)})

        finally:
            logger.debug("Stream generator finished")

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.put("/set-message-as-latest")
def set_message_as_latest(
    message_identifier: ChatMessageIdentifier,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user is not None else None

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


@router.post("/create-chat-message-feedback")
def create_chat_feedback(
    feedback: ChatFeedbackRequest,
    user: User | None = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user else None

    create_chat_message_feedback(
        is_positive=feedback.is_positive,
        feedback_text=feedback.feedback_text,
        predefined_feedback=feedback.predefined_feedback,
        chat_message_id=feedback.chat_message_id,
        user_id=user_id,
        db_session=db_session,
    )


@router.delete("/remove-chat-message-feedback")
def remove_chat_feedback(
    chat_message_id: int,
    user: User | None = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> None:
    user_id = user.id if user else None

    remove_chat_message_feedback(
        chat_message_id=chat_message_id,
        user_id=user_id,
        db_session=db_session,
    )


@router.post("/document-search-feedback")
def create_search_feedback(
    feedback: SearchFeedbackRequest,
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> None:
    """This endpoint isn't protected - it does not check if the user has access to the document
    Users could try changing boosts of arbitrary docs but this does not leak any data.
    """
    create_doc_retrieval_feedback(
        message_id=feedback.message_id,
        document_id=feedback.document_id,
        document_rank=feedback.document_rank,
        clicked=feedback.click,
        feedback=feedback.search_feedback,
        db_session=db_session,
    )


class MaxSelectedDocumentTokens(BaseModel):
    max_tokens: int


@router.get("/max-selected-document-tokens")
def get_max_document_tokens(
    persona_id: int,
    user: User | None = Depends(current_user),
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
        raise HTTPException(status_code=404, detail="Persona not found")

    return MaxSelectedDocumentTokens(
        max_tokens=_get_available_tokens_for_persona(
            persona=persona,
            user=user,
            db_session=db_session,
        ),
    )


class AvailableContextTokensResponse(BaseModel):
    available_tokens: int


@router.get("/available-context-tokens/{session_id}")
def get_available_context_tokens_for_session(
    session_id: UUID,
    user: User | None = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> AvailableContextTokensResponse:
    """Return available context tokens for a chat session based on its persona."""

    try:
        chat_session = get_chat_session_by_id(
            chat_session_id=session_id,
            user_id=user.id if user else None,
            db_session=db_session,
            is_shared=False,
            include_deleted=False,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Chat session not found")

    if not chat_session.persona:
        raise HTTPException(status_code=400, detail="Chat session has no persona")

    available = _get_available_tokens_for_persona(
        persona=chat_session.persona,
        user=user,
        db_session=db_session,
    )

    return AvailableContextTokensResponse(available_tokens=available)


"""Endpoints for chat seeding"""


class ChatSeedRequest(BaseModel):
    # standard chat session stuff
    persona_id: int

    # overrides / seeding
    llm_override: LLMOverride | None = None
    prompt_override: PromptOverride | None = None
    description: str | None = None
    message: str | None = None

    # TODO: support this
    # initial_message_retrieval_options: RetrievalDetails | None = None


class ChatSeedResponse(BaseModel):
    redirect_url: str


@router.post("/seed-chat-session", tags=PUBLIC_API_TAGS)
def seed_chat(
    chat_seed_request: ChatSeedRequest,
    # NOTE: This endpoint is designed for programmatic access (API keys, external services)
    # rather than authenticated user sessions. The user parameter is used for access control
    # but the created chat session is "unassigned" (user_id=None) until a user visits the web UI.
    # This allows external systems to pre-seed chat sessions that users can then access.
    user: User | None = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> ChatSeedResponse:

    try:
        new_chat_session = create_chat_session(
            db_session=db_session,
            description=chat_seed_request.description or "",
            user_id=None,  # this chat session is "unassigned" until a user visits the web UI
            persona_id=chat_seed_request.persona_id,
            llm_override=chat_seed_request.llm_override,
            prompt_override=chat_seed_request.prompt_override,
        )
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=400, detail="Invalid Persona provided.")

    if chat_seed_request.message is not None:
        root_message = get_or_create_root_message(
            chat_session_id=new_chat_session.id, db_session=db_session
        )
        llm = get_llm_for_persona(
            persona=new_chat_session.persona,
            user=user,
        )

        tokenizer = get_tokenizer(
            model_name=llm.config.model_name,
            provider_type=llm.config.model_provider,
        )
        token_count = len(tokenizer.encode(chat_seed_request.message))

        create_new_chat_message(
            chat_session_id=new_chat_session.id,
            parent_message=root_message,
            message=chat_seed_request.message,
            token_count=token_count,
            message_type=MessageType.USER,
            db_session=db_session,
        )

    return ChatSeedResponse(
        redirect_url=f"{WEB_DOMAIN}/chat?chatId={new_chat_session.id}&seeded=true"
    )


class SeedChatFromSlackRequest(BaseModel):
    chat_session_id: UUID


class SeedChatFromSlackResponse(BaseModel):
    redirect_url: str


@router.post("/seed-chat-session-from-slack")
def seed_chat_from_slack(
    chat_seed_request: SeedChatFromSlackRequest,
    user: User | None = Depends(current_user),
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


@router.get("/file/{file_id:path}", tags=PUBLIC_API_TAGS)
def fetch_chat_file(
    file_id: str,
    request: Request,
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> Response:

    # For user files, we need to get the file id from the user file id
    file_id_from_user_file = get_file_id_by_user_file_id(file_id, db_session)
    if file_id_from_user_file:
        file_id = file_id_from_user_file

    file_store = get_default_file_store()
    file_record = file_store.read_file_record(file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    original_file_name = file_record.display_name
    if file_record.file_type.startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        # Check if a converted text file exists for .docx files
        txt_file_name = docx_to_txt_filename(original_file_name)
        txt_file_id = os.path.join(os.path.dirname(file_id), txt_file_name)
        txt_file_record = file_store.read_file_record(txt_file_id)
        if txt_file_record:
            file_record = txt_file_record
            file_id = txt_file_id

    media_type = file_record.file_type
    file_io = file_store.read_file(file_id, mode="b")

    # Files served here are immutable (content-addressed by file_id), so allow long-lived caching.
    # Use `private` because this is behind auth / tenant scoping.
    etag = f'"{file_id}"'
    cache_headers = {
        "Cache-Control": "private, max-age=31536000, immutable",
        "ETag": etag,
        "Vary": "Cookie",
    }

    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=cache_headers)

    return StreamingResponse(file_io, media_type=media_type, headers=cache_headers)


@router.get("/search", tags=PUBLIC_API_TAGS)
async def search_chats(
    query: str | None = Query(None),
    page: int = Query(1),
    page_size: int = Query(10),
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatSearchResponse:
    """
    Search for chat sessions based on the provided query.
    If no query is provided, returns recent chat sessions.
    """

    # Use the enhanced database function for chat search
    chat_sessions, has_more = search_chat_sessions(
        user_id=user.id if user else None,
        db_session=db_session,
        query=query,
        page=page,
        page_size=page_size,
        include_deleted=False,
        include_onyxbot_flows=False,
    )

    # Group chat sessions by time period
    today = datetime.datetime.now().date()
    yesterday = today - timedelta(days=1)
    this_week = today - timedelta(days=7)
    this_month = today - timedelta(days=30)

    today_chats: list[ChatSessionSummary] = []
    yesterday_chats: list[ChatSessionSummary] = []
    this_week_chats: list[ChatSessionSummary] = []
    this_month_chats: list[ChatSessionSummary] = []
    older_chats: list[ChatSessionSummary] = []

    for session in chat_sessions:
        session_date = session.time_created.date()

        chat_summary = ChatSessionSummary(
            id=session.id,
            name=session.description,
            persona_id=session.persona_id,
            time_created=session.time_created,
            shared_status=session.shared_status,
            current_alternate_model=session.current_alternate_model,
            current_temperature_override=session.temperature_override,
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


@router.post("/stop-chat-session/{chat_session_id}", tags=PUBLIC_API_TAGS)
def stop_chat_session(
    chat_session_id: UUID,
    user: User | None = Depends(current_user),
    redis_client: Redis = Depends(get_redis_client),
) -> dict[str, str]:
    """
    Stop a chat session by setting a stop signal in Redis.
    This endpoint is called by the frontend when the user clicks the stop button.
    """
    set_fence(chat_session_id, redis_client, True)
    return {"message": "Chat session stopped"}
