"""
IMPORTANT: familiarize yourself with the design concepts prior to contributing to this file.
An overview can be found in the README.md file in this directory.
"""

import re
from concurrent.futures import Future
from functools import partial
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_processing_checker import (
    ADMISSION_CACHE_TIMEOUT_S,
    ChatTurnAdmission,
)
from onyx.chat.chat_utils import (
    capture_chat_history,
    convert_chat_history,
    create_chat_session_from_request,
    is_last_assistant_message_clarification,
)
from onyx.chat.errors import chat_error
from onyx.chat.execution import start_chat_turn
from onyx.chat.files import (
    collect_available_file_ids,
    convert_loaded_files_to_chat_files,
    determine_search_params,
    extract_context_files,
    load_chat_files,
    load_context_user_files_for_tools,
    resolve_context_user_files,
)
from onyx.chat.history_store import get_chat_history_store
from onyx.chat.incognito import (
    content_free_file_descriptors,
    incognito_llm_request_policy,
)
from onyx.chat.incognito_context import incognito_session_ended
from onyx.chat.models import (
    AnswerStream,
    ChatBasicResponse,
    ChatFullResponse,
    ChatResponseOutcome,
    ChatTurnSetup,
    CreateChatSessionID,
    PersonaPromptConfig,
    ReservedChatResponse,
    ToolCallResponse,
)
from onyx.chat.prompt_utils import (
    calculate_reserved_tokens,
    get_default_base_system_prompt,
)
from onyx.chat.stream_buffer import ChatStream
from onyx.configs.chat_configs import CHAT_RESPONSE_WAIT_TIMEOUT_S
from onyx.configs.constants import (
    DEFAULT_PERSONA_ID,
    MessageType,
    MilestoneRecordType,
)
from onyx.context.search.models import SearchDoc
from onyx.db.chat import (
    checkpoint_from_summary,
    create_new_chat_message,
    find_summary_for_branch,
    get_chat_session_by_id,
    load_message_branch,
    reserve_chat_response_ids,
)
from onyx.db.document_set import filter_document_set_names_by_user_access
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import HookPoint, record_mode_persists_content
from onyx.db.memory import get_memories
from onyx.db.models import ChatSession, User
from onyx.db.tools import capture_persona_tool_configuration, get_tools
from onyx.db.user_file import capture_user_file_metadata, prepare_chat_file_inputs
from onyx.deep_research.tool_definitions import (
    RESEARCH_AGENT_IN_CODE_ID,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, log_onyx_error
from onyx.file_store.utils import verify_user_files
from onyx.hooks.executor import HookSkipped, HookSoftFailed, execute_hook
from onyx.hooks.points.query_processing import (
    QueryProcessingPayload,
    QueryProcessingResponse,
)
from onyx.llm.factory import (
    get_llm_for_persona,
    get_llm_token_counter,
)
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import ReasoningEffort, UserMessage
from onyx.llm.override_models import LLMOverride
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.onyxbot.slack.models import SlackContext
from onyx.prompts.prompt_utils import substitute_user_placeholders
from onyx.server.features.tool.tool_visibility import is_tool_available_for_persona
from onyx.server.query_and_chat.models import (
    MessageResponseIDInfo,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    AgentResponseDelta,
    AgentResponseStart,
    CitationInfo,
    Packet,
    StreamingError,
)
from onyx.server.usage_limits import check_llm_cost_limit_for_provider
from onyx.tools.constants import FILE_READER_TOOL_ID, SEARCH_TOOL_ID
from onyx.tools.models import SearchToolUsage
from onyx.utils.fleet_query_telemetry import QueryObservation, telemetry_chat
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import mt_cloud_telemetry
from onyx.utils.timing import log_function_time, log_generator_function_time
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()
ERROR_TYPE_CANCELLED = "cancelled"
APPROX_CHARS_PER_TOKEN = 4


def _load_session(
    request: SendMessageRequest, user: User, db_session: Session
) -> ChatSession:
    filters = request.internal_search_filters
    if (
        not user.is_anonymous
        and filters is not None
        and filters.document_set is not None
    ):
        accessible_names = filter_document_set_names_by_user_access(
            db_session=db_session, document_set_names=filters.document_set, user=user
        )
        unauthorized = sorted(set(filters.document_set) - set(accessible_names))
        if unauthorized:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                f"User does not have access to document sets: {unauthorized}",
            )

    session_id = request.chat_session_id
    if session_id is None:
        if request.chat_session_info is None:
            raise ValueError("Must specify a chat session id or chat session info")
        session_id = create_chat_session_from_request(
            request.chat_session_info, user, db_session
        ).id
    chat_session = get_chat_session_by_id(
        chat_session_id=session_id,
        user_id=user.id,
        db_session=db_session,
        eager_load_persona=True,
    )
    verify_user_files(
        user_files=request.file_descriptors,
        user_id=user.id,
        db_session=db_session,
        project_id=chat_session.project_id,
    )
    persona = chat_session.persona
    tenant_id = get_current_tenant_id()
    # Record the user's first chat for milestone tracking.
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
            "origin": request.origin.value,
            "has_files": len(request.file_descriptors) > 0,
            "has_project": chat_session.project_id is not None,
            "has_persona": persona is not None and persona.id != DEFAULT_PERSONA_ID,
            "deep_research": request.deep_research,
        },
    )

    return chat_session


def _select_models(
    new_msg_req: SendMessageRequest,
    chat_session: ChatSession,
    user: User,
    llm_overrides: list[LLMOverride] | None,
    litellm_additional_headers: dict[str, str] | None,
    db_session: Session,
) -> list[tuple[LLM, str]]:
    # Check managed-provider cost limits before accepting each client.
    selected_models: list[tuple[LLM, str]] = []
    selected_overrides: list[LLMOverride | None] = (
        list(llm_overrides or [])
        if llm_overrides
        else [new_msg_req.llm_override or chat_session.llm_override]
    )
    # Apply overrides after persona selection resolves the provider.
    incognito_policy_fn = partial(
        incognito_llm_request_policy, chat_session.incognito_record_mode
    )
    for override in selected_overrides:
        llm = get_llm_for_persona(
            persona=chat_session.persona,
            user=user,
            llm_override=override,
            additional_headers=litellm_additional_headers,
            policy_fn=incognito_policy_fn,
        )
        check_llm_cost_limit_for_provider(
            db_session=db_session,
            tenant_id=get_current_tenant_id(),
            llm_provider_api_key=llm.config.api_key,
        )
        display_name = llm.config.model_name
        if override is not None:
            display_name = (
                override.display_name or override.model_version or display_name
            )
        selected_models.append((llm, display_name))
    return selected_models


def _process_query(
    message_text: str,
    chat_session: ChatSession,
    user: User,
    db_session: Session,
) -> str:
    # The hook sends query text and email externally; respect content egress policy.
    mode = chat_session.incognito_record_mode
    if not message_text.strip() or (mode is not None and not mode.fires_hooks):
        return message_text
    hook_result = execute_hook(
        db_session=db_session,
        hook_point=HookPoint.QUERY_PROCESSING,
        payload=QueryProcessingPayload(
            query=message_text,
            # Anonymous and some SSO users have no email.
            user_email=None if user.is_anonymous else user.email,
            chat_session_id=str(chat_session.id),
        ).model_dump(),
        response_type=QueryProcessingResponse,
    )
    if isinstance(hook_result, (HookSkipped, HookSoftFailed)):
        return message_text
    if not (hook_result.query and hook_result.query.strip()):
        raise OnyxError(
            OnyxErrorCode.QUERY_REJECTED,
            hook_result.rejection_message
            or "The hook extension for query processing did not return a valid query. No rejection reason was provided.",
        )
    return hook_result.query.strip()


def prepare_chat_turn(
    new_msg_req: SendMessageRequest,
    user: User,
    llm_overrides: list[LLMOverride] | None,
    *,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    slack_context: SlackContext | None = None,
    additional_context: str | None = None,
) -> ChatTurnSetup:
    """Capture configuration, load files, then reserve responses before execution."""
    admission = ChatTurnAdmission(
        get_cache_backend(operation_timeout_s=ADMISSION_CACHE_TIMEOUT_S)
    )
    try:
        with get_session_with_current_tenant() as db_session:
            chat_session = _load_session(new_msg_req, user, db_session)
            # Reserve the session before model setup or changes to its message tree.
            admission.claim(chat_session.id)
            selected_models = _select_models(
                new_msg_req,
                chat_session,
                user,
                llm_overrides,
                litellm_additional_headers,
                db_session,
            )
            token_counter = get_llm_token_counter(selected_models[0][0])
            chat_history, parent_message = load_message_branch(
                chat_session.id, new_msg_req.parent_message_id, db_session
            )
            accepted_text = None
            # Regeneration reuses the user message and its accepted query.
            if parent_message.message_type != MessageType.USER:
                accepted_text = _process_query(
                    new_msg_req.message, chat_session, user, db_session
                )
                # Use one tokenizer for stored counts, including after model switches.
                user_token_count = len(get_tokenizer(None, None).encode(accepted_text))
                keeps_content = record_mode_persists_content(
                    chat_session.incognito_record_mode
                )
                admission.refresh()
                user_message = create_new_chat_message(
                    chat_session_id=chat_session.id,
                    parent_message=parent_message,
                    message=accepted_text if keeps_content else "",
                    token_count=user_token_count,
                    message_type=MessageType.USER,
                    files=(
                        new_msg_req.file_descriptors
                        if keeps_content
                        else content_free_file_descriptors(new_msg_req.file_descriptors)
                    ),
                    db_session=db_session,
                    commit=True,
                )
                chat_history.append(user_message)
            persona = chat_session.persona
            user_message_id = chat_history[-1].id
            context_user_files = capture_user_file_metadata(
                resolve_context_user_files(
                    persona, chat_session.project_id, user.id, db_session
                )
            )
            # Collect file IDs for the file reader tool *before* summary truncation so
            # that files attached to older (summarized-away) messages are still accessible
            # via the FileReaderTool.
            available_files = collect_available_file_ids(
                chat_history, context_user_files
            )
            memory = get_memories(user, db_session)
            project_instructions = (
                chat_session.project.instructions if chat_session.project else None
            )
            agent_instructions = (
                persona.system_prompt if persona.id != DEFAULT_PERSONA_ID else None
            )
            if persona.replace_base_system_prompt:
                # The agent instructions already appear in the system message.
                custom_prompt = project_instructions or None
            elif project_instructions and agent_instructions:
                custom_prompt = (
                    f"Project instructions:\n{project_instructions}\n\n"
                    f"Agent instructions:\n{agent_instructions}\n\n"
                    "If these instructions conflict, follow the agent instructions."
                )
            else:
                custom_prompt = agent_instructions or project_instructions or None
            base_system_prompt = get_default_base_system_prompt(db_session)
            # Reserve against the placeholder-substituted text sent to the model,
            # so long directory values cannot invalidate the reservation.
            reserved_tokens = calculate_reserved_tokens(
                db_session=db_session,
                persona_system_prompt=substitute_user_placeholders(
                    (
                        (persona.system_prompt or "")
                        if persona.replace_base_system_prompt
                        else ""
                    )
                    + (custom_prompt or ""),
                    memory.user_info.placeholder_values,
                ),
                token_counter=token_counter,
                files=new_msg_req.file_descriptors,
                user_memory_context=memory
                if user.use_memories
                else memory.without_memories(),
                base_system_prompt=base_system_prompt,
            )
            tools = get_tools(db_session)
            research_tool_id = next(
                (
                    tool.id
                    for tool in tools
                    if tool.in_code_tool_id == RESEARCH_AGENT_IN_CODE_ID
                ),
                None,
            )
            if new_msg_req.deep_research and research_tool_id is None:
                raise ValueError("Research tool configuration is missing")
            tool_names = {tool.id: tool.name for tool in tools}
            forced_tool_id = new_msg_req.forced_tool_id
            if forced_tool_id in {
                tool.id
                for tool in tools
                if not is_tool_available_for_persona(tool, persona.id)
            }:
                forced_tool_id = None
            summary_message = find_summary_for_branch(db_session, chat_history)
            checkpoint = checkpoint_from_summary(summary_message)
            descriptors = {
                descriptor["id"]: descriptor
                for message in chat_history
                for descriptor in message.files or []
            }
            chat_session_id = chat_session.id
            project_id = chat_session.project_id
            incognito_record_mode = chat_session.incognito_record_mode
            persona_id = persona.id
            persona_prompt = PersonaPromptConfig(
                system_prompt=persona.system_prompt,
                task_prompt=persona.task_prompt,
                datetime_aware=persona.datetime_aware,
                replace_base_system_prompt=persona.replace_base_system_prompt,
            )
            tool_configuration = capture_persona_tool_configuration(persona)
            previous_run_id = (
                next(
                    (
                        str(message.id)
                        for message in reversed(chat_history)
                        if message.message_type == MessageType.ASSISTANT
                        and message.response_status is not None
                    ),
                    None,
                )
                if record_mode_persists_content(incognito_record_mode)
                else None
            )
            captured_history = capture_chat_history(
                chat_history,
                tool_names,
                token_counter,
                checkpoint,
            )
            file_inputs = prepare_chat_file_inputs(
                list(descriptors.values()), db_session
            )
            reasoning_effort = (
                chat_session.reasoning_effort_override or ReasoningEffort.AUTO
            )
            search_tool_id = next(
                (tool.id for tool in tools if tool.in_code_tool_id == SEARCH_TOOL_ID),
                None,
            )
            skip_clarification = is_last_assistant_message_clarification(chat_history)
        # File loading can be slow; release the preparation DB session first.
        admission.refresh()
        extracted_files = extract_context_files(
            user_files=context_user_files,
            llm_max_context_window=min(
                llm.config.max_input_tokens for llm, _ in selected_models
            ),
            reserved_token_count=reserved_tokens,
        )
        admission.refresh()
        search_params = determine_search_params(persona_id, project_id, extracted_files)
        if (
            search_params.search_usage == SearchToolUsage.DISABLED
            and forced_tool_id == search_tool_id
        ):
            forced_tool_id = None
        loaded_files = load_chat_files(file_inputs)
        chat_files_for_tools = convert_loaded_files_to_chat_files(loaded_files)
        chat_files_for_tools.extend(
            load_context_user_files_for_tools(
                context_user_files, {file.filename for file in chat_files_for_tools}
            )
        )
        history = convert_chat_history(
            chat_history=captured_history,
            files=loaded_files,
            context_image_files=extracted_files.image_files,
            token_counter=token_counter,
            additional_context=additional_context or new_msg_req.additional_context,
        )
        if not any(
            tool.in_code_tool_id == FILE_READER_TOOL_ID
            for tool in tool_configuration.tools
        ):
            history.all_injected_file_metadata = {}
        # Persistent history and the accepted user row are already loaded and saved.
        if not record_mode_persists_content(incognito_record_mode):
            admission.refresh()
            history_store = get_chat_history_store(
                message_id=user_message_id,
                chat_session_id=chat_session_id,
                persist_content=False,
            )
            history.messages, previous_run_id = history_store.prepare_messages(
                history.messages, previous_run_id, accepted_text
            )
            selected_user_message = history.messages[-1] if history.messages else None
            if not isinstance(selected_user_message, UserMessage):
                raise ValueError(
                    "History storage must retain the accepted user message last"
                )
            admission.refresh()
            history_store.save_user_message(selected_user_message)
            if incognito_session_ended(chat_session_id):
                raise RuntimeError("Incognito session ended")
        admission.refresh()
        # Reserve assistant message IDs so each model response has a saved identity.
        with get_session_with_current_tenant() as db_session:
            response_ids = reserve_chat_response_ids(
                db_session=db_session,
                chat_session_id=chat_session_id,
                parent_message_id=user_message_id,
                model_display_names=[name for _, name in selected_models],
            )
        models = [
            ReservedChatResponse(llm=llm, display_name=name, message_id=message_id)
            for (llm, name), message_id in zip(
                selected_models, response_ids, strict=True
            )
        ]
        is_multi = bool(llm_overrides)
        return ChatTurnSetup(
            new_msg_req=new_msg_req,
            chat_session_id=chat_session_id,
            chat_session_project_id=project_id,
            incognito_record_mode=incognito_record_mode,
            persona_id=persona_id,
            persona=persona_prompt,
            base_system_prompt=base_system_prompt,
            tool_configuration=tool_configuration,
            research_tool_id=research_tool_id,
            checkpoint=next(
                (
                    message.checkpoint
                    for message in reversed(captured_history)
                    if message.checkpoint is not None
                ),
                None,
            ),
            user_message_id=user_message_id,
            user_identity=LLMUserIdentity(
                user_id="anonymous_user"
                if user.is_anonymous
                else user.email or str(user.id),
                session_id=str(chat_session_id),
            ),
            responses=models,
            messages=history.messages[:-1],
            input_messages=history.messages[-1:],
            previous_run_id=previous_run_id,
            extracted_context_files=extracted_files,
            stream_id=user_message_id if is_multi else models[0].message_id,
            reasoning_effort=reasoning_effort,
            search_params=search_params,
            all_injected_file_metadata=history.all_injected_file_metadata,
            available_files=available_files,
            forced_tool_id=forced_tool_id,
            chat_files_for_tools=chat_files_for_tools,
            custom_agent_prompt=custom_prompt,
            user_memory_context=memory,
            skip_clarification=skip_clarification,
            cache=get_cache_backend(),
            admission=admission,
            slack_context=slack_context,
            litellm_additional_headers=litellm_additional_headers,
            custom_tool_additional_headers=custom_tool_additional_headers,
            mcp_headers=mcp_headers,
        )
    except BaseException:
        admission.release()
        raise


def _stream_chat_turn(
    new_msg_req: SendMessageRequest,
    user: User,
    llm_overrides: list[LLMOverride] | None = None,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    additional_context: str | None = None,
    slack_context: SlackContext | None = None,
    response_future: Future[ChatResponseOutcome] | None = None,
    query_observation: QueryObservation | None = None,
) -> AnswerStream:
    """Prepare one request, then read its independently owned agent stream."""
    setup: ChatTurnSetup | None = None
    stream: ChatStream | None = None
    try:
        setup = prepare_chat_turn(
            new_msg_req=new_msg_req,
            user=user,
            llm_overrides=llm_overrides,
            litellm_additional_headers=litellm_additional_headers,
            custom_tool_additional_headers=custom_tool_additional_headers,
            mcp_headers=mcp_headers,
            slack_context=slack_context,
            additional_context=additional_context,
        )
        stream = start_chat_turn(
            setup,
            user,
            response_future,
            query_observation=query_observation,
        )
        yield from stream
    except Exception as error:
        if isinstance(error, OnyxError):
            if error.error_code is not OnyxErrorCode.QUERY_REJECTED:
                log_onyx_error(error)
        else:
            logger.exception("Chat request failed")
        yield chat_error(error, setup.responses[0].llm if setup else None)
    finally:
        if stream is not None:
            stream.close()


@log_generator_function_time()
@telemetry_chat
def handle_stream_message_objects(
    new_msg_req: SendMessageRequest,
    user: User,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    additional_context: str | None = None,
    slack_context: SlackContext | None = None,
    response_future: Future[ChatResponseOutcome] | None = None,
    query_observation: QueryObservation | None = None,
) -> AnswerStream:
    """Single-model streaming entrypoint. For multi-model comparison, use ``handle_multi_model_stream``.

    Emits one fleet ``query`` record when server execution ends, including after
    client disconnects. Callers pass ``new_msg_req`` as a keyword argument
    so the record names the request channel.
    """
    yield from _stream_chat_turn(
        new_msg_req=new_msg_req,
        user=user,
        llm_overrides=None,
        litellm_additional_headers=litellm_additional_headers,
        custom_tool_additional_headers=custom_tool_additional_headers,
        mcp_headers=mcp_headers,
        additional_context=additional_context,
        slack_context=slack_context,
        response_future=response_future,
        query_observation=query_observation,
    )


@log_generator_function_time()
@telemetry_chat
def handle_multi_model_stream(
    new_msg_req: SendMessageRequest,
    user: User,
    llm_overrides: list[LLMOverride],
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    query_observation: QueryObservation | None = None,
) -> AnswerStream:
    """Stream independent responses from two or three selected models."""
    n_models = len(llm_overrides)
    if n_models < 2 or n_models > 3:
        yield StreamingError(
            error="Multi-model requires 2-3 overrides, got %d" % n_models,
            error_code="VALIDATION_ERROR",
            is_retryable=False,
        )
        return
    if new_msg_req.deep_research:
        yield StreamingError(
            error="Multi-model is not supported with deep research",
            error_code="VALIDATION_ERROR",
            is_retryable=False,
        )
        return
    yield from _stream_chat_turn(
        new_msg_req=new_msg_req,
        user=user,
        llm_overrides=llm_overrides,
        query_observation=query_observation,
        litellm_additional_headers=litellm_additional_headers,
        custom_tool_additional_headers=custom_tool_additional_headers,
        mcp_headers=mcp_headers,
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
            if packet.placement.sub_turn_index is not None:
                continue
            if isinstance(packet.obj, AgentResponseStart):
                answer = answer or ""
                if packet.obj.final_documents:
                    known_documents = {doc.document_id for doc in top_documents}
                    top_documents.extend(
                        doc
                        for doc in packet.obj.final_documents
                        if doc.document_id not in known_documents
                    )
            elif isinstance(packet.obj, AgentResponseDelta):
                answer = (answer or "") + packet.obj.content
            elif isinstance(packet.obj, CitationInfo):
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
    response_future: Future[ChatResponseOutcome],
) -> ChatFullResponse:
    """Read delivery metadata and project accepted execution content."""
    error_msg: str | None = None
    message_id: int | None = None
    chat_session_id: UUID | None = None
    incognito = False

    for packet in packets:
        if isinstance(packet, StreamingError):
            error_msg = packet.error
        elif isinstance(packet, MessageResponseIDInfo):
            message_id = packet.reserved_assistant_message_id
        elif isinstance(packet, CreateChatSessionID):
            chat_session_id = packet.chat_session_id
            incognito = packet.incognito

    if message_id is None:
        raise ValueError("Message ID is required")

    outcome = response_future.result(timeout=CHAT_RESPONSE_WAIT_TIMEOUT_S)
    snapshot = outcome.response
    final_answer = snapshot.answer or ""

    reasoning = snapshot.reasoning

    tool_call_responses = [
        ToolCallResponse(
            tool_name=tc.tool_name,
            tool_arguments=tc.tool_call_arguments,
            tool_result=tc.tool_call_response,
            search_docs=tc.search_docs,
            generated_images=tc.generated_images,
            pre_reasoning=tc.reasoning_tokens,
        )
        for tc in snapshot.tool_calls
    ]

    return ChatFullResponse(
        answer=final_answer,
        answer_citationless=remove_answer_citations(final_answer),
        pre_answer_reasoning=reasoning,
        tool_calls=tool_call_responses,
        top_documents=snapshot.top_documents,
        citation_info=snapshot.citation_info,
        message_id=message_id,
        chat_session_id=chat_session_id,
        incognito=incognito,
        error_msg=outcome.error or error_msg,
    )
