from collections.abc import Callable
from functools import partial

from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.chat.chat_state import ChatTurnSetup, PersonaPromptConfig, PreparedModel
from onyx.chat.compression import find_summary_for_branch
from onyx.chat.files import (
    _collect_available_file_ids,
    _convert_loaded_files_to_chat_files,
    _load_context_user_files_for_tools,
    determine_search_params,
    extract_context_files,
    load_all_chat_files,
    resolve_context_user_files,
    summarize_file_metadata,
)
from onyx.chat.incognito import (
    content_free_file_descriptors,
    incognito_llm_request_policy,
)
from onyx.chat.incognito_context import append_incognito_message, load_incognito_context
from onyx.chat.models import AnswerStreamPart, ChatHistoryResult, CreateChatSessionID
from onyx.chat.prompt_utils import calculate_reserved_tokens
from onyx.configs.constants import DEFAULT_PERSONA_ID, MessageType, MilestoneRecordType
from onyx.context.messages import PromptMetadata
from onyx.db.chat import (
    create_chat_session_from_request,
    create_new_chat_message,
    get_chat_session_by_id,
    reserve_chat_response_ids,
)
from onyx.db.chat_history import (
    convert_chat_history,
    is_last_assistant_message_clarification,
    load_message_branch,
)
from onyx.db.document_set import filter_document_set_names_by_user_access
from onyx.db.enums import HookPoint, record_mode_persists_content
from onyx.db.memory import get_memories
from onyx.db.models import ChatMessage, ChatSession, Persona, User, UserFile
from onyx.db.tools import get_tools
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import ExtractedContextFiles, FileToolMetadata
from onyx.file_store.utils import verify_user_files
from onyx.hooks.executor import HookSkipped, HookSoftFailed, execute_hook
from onyx.hooks.points.query_processing import (
    QueryProcessingPayload,
    QueryProcessingResponse,
)
from onyx.llm.factory import get_llm_for_persona, get_llm_token_counter
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import AssistantMessage, ReasoningEffort, TextContent, UserMessage
from onyx.llm.override_models import LLMOverride
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.onyxbot.slack.models import SlackContext
from onyx.prompts.prompt_utils import substitute_user_placeholders
from onyx.server.query_and_chat.models import (
    MessageResponseIDInfo,
    ModelResponseSlot,
    MultiModelMessageResponseIDInfo,
    SendMessageRequest,
)
from onyx.server.usage_limits import check_llm_cost_limit_for_provider
from onyx.tools.constants import FILE_READER_TOOL_ID, SEARCH_TOOL_ID
from onyx.tools.models import ChatFile, SearchToolUsage
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import mt_cloud_telemetry
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


def _resolve_query_processing_hook_result(
    hook_result: QueryProcessingResponse | HookSkipped | HookSoftFailed,
    message_text: str,
) -> str:
    """Accept a rewritten query or reject it; skipped hooks preserve the original."""
    if isinstance(hook_result, (HookSkipped, HookSoftFailed)):
        return message_text
    if not (hook_result.query and hook_result.query.strip()):
        raise OnyxError(
            OnyxErrorCode.QUERY_REJECTED,
            hook_result.rejection_message
            or "The hook extension for query processing did not return a valid query. No rejection reason was provided.",
        )
    return hook_result.query.strip()


def _build_model_display_name(override: LLMOverride | None, llm: LLM) -> str:
    """Use the requested display name, falling back to the configured model."""
    if override is not None:
        chosen = override.display_name or override.model_version
        if chosen:
            return chosen
    return llm.info.model_name


def _load_session(
    request: SendMessageRequest, user: User, db_session: Session, *, bypass_acl: bool
) -> ChatSession:
    filters = request.internal_search_filters
    if (
        not bypass_acl
        and not user.is_anonymous
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
            llm_provider_api_key=llm.transport.config.api_key,
        )
        selected_models.append((llm, _build_model_display_name(override, llm)))
    return selected_models


def _accept_message(
    new_msg_req: SendMessageRequest,
    chat_session: ChatSession,
    user: User,
    db_session: Session,
) -> tuple[list[ChatMessage], ChatMessage, str | None]:
    """Apply the query hook once; regeneration reuses its accepted user message."""
    message_text = new_msg_req.message
    chat_history, parent_message = load_message_branch(
        chat_session.id, new_msg_req.parent_message_id, db_session
    )

    # Regeneration reuses the accepted user message.
    if parent_message.message_type == MessageType.USER:
        return chat_history, parent_message, None
    else:
        # The hook sends query text and email externally; respect content egress policy.
        mode = chat_session.incognito_record_mode
        if message_text.strip() and (mode is None or mode.fires_hooks):
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
            message_text = _resolve_query_processing_hook_result(
                hook_result, message_text
            )

        # Use one tokenizer for stored counts, including after model switches.
        default_tokenizer = get_tokenizer(None, None)
        user_token_count = len(default_tokenizer.encode(message_text))
        # Incognito persists structure and token counts; text stays in the ephemeral store.
        keeps_content = record_mode_persists_content(mode)
        user_message = create_new_chat_message(
            chat_session_id=chat_session.id,
            parent_message=parent_message,
            message=message_text if keeps_content else "",
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

    return chat_history, user_message, message_text


def _prepare_history(
    chat_history: list[ChatMessage],
    chat_session: ChatSession,
    context_user_files: list[UserFile],
    extracted_context_files: ExtractedContextFiles,
    token_counter: Callable[[str], int],
    tool_id_to_name_map: dict[int, str],
    db_session: Session,
    *,
    accepted_text: str | None,
    additional_context: str | None,
) -> tuple[ChatHistoryResult, list[ChatFile], bool]:
    """Load replayable messages and tool files, retaining references dropped by summaries."""
    persona = chat_session.persona
    summary_message = find_summary_for_branch(db_session, chat_history)
    # Preserve file metadata when summaries replace the messages that attached them.
    summarized_file_metadata: dict[str, FileToolMetadata] = {}
    if summary_message and summary_message.last_summarized_message_id:
        cutoff_id = summary_message.last_summarized_message_id
        summarized_file_metadata = summarize_file_metadata(
            [message for message in chat_history if message.id <= cutoff_id]
        )
        chat_history = [m for m in chat_history if m.id > cutoff_id]

    skip_clarification = is_last_assistant_message_clarification(chat_history)

    # Keep file bytes lazy until prompt preparation or a tool needs them.
    files = load_all_chat_files(chat_history, db_session)
    chat_files_for_tools = _convert_loaded_files_to_chat_files(files)
    chat_files_for_tools.extend(
        _load_context_user_files_for_tools(
            context_user_files,
            {chat_file.filename for chat_file in chat_files_for_tools},
        )
    )

    # Detach history from ORM objects before agent execution.
    has_file_reader_tool = any(
        tool.in_code_tool_id == FILE_READER_TOOL_ID for tool in persona.tools
    )

    chat_history_result = convert_chat_history(
        chat_history=chat_history,
        files=files,
        context_image_files=extracted_context_files.image_files,
        additional_context=additional_context,
        token_counter=token_counter,
        tool_id_to_name_map=tool_id_to_name_map,
    )
    messages = chat_history_result.messages

    # Restore incognito text from ephemeral storage; database rows contain no content.
    incognito_mode = chat_session.incognito_record_mode
    if not record_mode_persists_content(incognito_mode):
        stored_messages = load_incognito_context(chat_session.id).messages
        if (
            accepted_text is not None
            and messages
            and isinstance(messages[-1], UserMessage)
        ):
            current_user = messages[-1].model_copy(update={"content": accepted_text})
            messages = stored_messages + [current_user]
            append_incognito_message(chat_session.id, current_user)
        else:
            messages = stored_messages

    # FileReaderTool needs metadata for files whose text no longer fits the prompt.
    all_injected_file_metadata: dict[str, FileToolMetadata] = (
        chat_history_result.all_injected_file_metadata if has_file_reader_tool else {}
    )

    # Include files whose source messages were replaced by a summary.
    if summarized_file_metadata:
        for fid, meta in summarized_file_metadata.items():
            all_injected_file_metadata.setdefault(fid, meta)

    if all_injected_file_metadata:
        logger.debug(
            "FileReader: file metadata for model: %s",
            [(fid, m.filename) for fid, m in all_injected_file_metadata.items()],
        )

    if summary_message is not None:
        summary_simple = AssistantMessage(
            content=[TextContent(text=summary_message.message)],
            metadata=PromptMetadata(token_count=summary_message.token_count),
        )
        messages.insert(0, summary_simple)

    return (
        ChatHistoryResult(
            messages=messages, all_injected_file_metadata=all_injected_file_metadata
        ),
        chat_files_for_tools,
        skip_clarification,
    )


def prepare_chat_turn(
    new_msg_req: SendMessageRequest,
    user: User,
    db_session: Session,
    # None → single-model (persona default LLM); non-empty list → multi-model (one LLM per override)
    llm_overrides: list[LLMOverride] | None,
    *,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    bypass_acl: bool = False,
    slack_context: SlackContext | None = None,
    # External conversation context enters the prompt without being persisted.
    additional_context: str | None = None,
) -> ChatTurnSetup:
    """Prepare messages, files, scalar persona settings, and response IDs for execution."""
    chat_session = _load_session(new_msg_req, user, db_session, bypass_acl=bypass_acl)
    persona = chat_session.persona
    is_multi = bool(llm_overrides)
    initial_packets: list[AnswerStreamPart] = []
    if new_msg_req.chat_session_id is None:
        initial_packets.append(
            CreateChatSessionID(
                chat_session_id=chat_session.id,
                incognito=chat_session.incognito_record_mode is not None,
            )
        )
    user_identity = LLMUserIdentity(
        user_id="anonymous_user" if user.is_anonymous else user.email or str(user.id),
        session_id=str(chat_session.id),
    )

    selected_models = _select_models(
        new_msg_req,
        chat_session,
        user,
        llm_overrides,
        litellm_additional_headers,
        db_session,
    )
    token_counter = get_llm_token_counter(selected_models[0][0])
    chat_history, user_message, accepted_text = _accept_message(
        new_msg_req, chat_session, user, db_session
    )

    # Keep summarized attachments accessible to FileReaderTool.
    context_user_files = resolve_context_user_files(
        persona=persona,
        project_id=chat_session.project_id,
        user_id=user.id,
        db_session=db_session,
    )
    available_files = _collect_available_file_ids(
        chat_history=chat_history, context_user_files=context_user_files
    )

    user_memory_context = get_memories(user, db_session)

    # Read stored agent/project instructions before calculating the prompt budget.
    custom_agent_prompt = get_custom_agent_prompt(persona, chat_session)

    # Hide disabled memories from the prompt while retaining context for memory writes.
    prompt_memory_context = (
        user_memory_context
        if user.use_memories
        else user_memory_context.without_memories()
    )

    # Count substituted instructions so long directory values fit the reserved budget.
    max_reserved_system_prompt_tokens_str = substitute_user_placeholders(
        (persona.system_prompt or "") + (custom_agent_prompt or ""),
        user_memory_context.user_info.placeholder_values,
    )
    reserved_token_count = calculate_reserved_tokens(
        db_session=db_session,
        persona_system_prompt=max_reserved_system_prompt_tokens_str,
        token_counter=token_counter,
        files=new_msg_req.file_descriptors,
        user_memory_context=prompt_memory_context,
    )

    # Use the smallest context window across models for safety (harmless for N=1).
    llm_max_context_window = min(
        llm.info.max_input_tokens for llm, _ in selected_models
    )

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

    all_tools = get_tools(db_session)
    tool_id_to_name_map = {tool.id: tool.name for tool in all_tools}

    search_tool_id = next(
        (tool.id for tool in all_tools if tool.in_code_tool_id == SEARCH_TOOL_ID), None
    )

    forced_tool_id = new_msg_req.forced_tool_id
    if (
        search_params.search_usage == SearchToolUsage.DISABLED
        and forced_tool_id is not None
        and search_tool_id is not None
        and forced_tool_id == search_tool_id
    ):
        forced_tool_id = None

    # Resolve forced tools against enabled tools; disabled tools can remain attached to personas.
    if forced_tool_id in {tool.id for tool in all_tools if not tool.enabled}:
        forced_tool_id = None

    history, chat_files_for_tools, skip_clarification = _prepare_history(
        chat_history,
        chat_session,
        context_user_files,
        extracted_context_files,
        token_counter,
        tool_id_to_name_map,
        db_session,
        accepted_text=accepted_text,
        additional_context=additional_context or new_msg_req.additional_context,
    )

    response_ids = reserve_chat_response_ids(
        db_session=db_session,
        chat_session_id=chat_session.id,
        parent_message_id=user_message.id,
        model_display_names=[name for _, name in selected_models],
    )
    models = [
        PreparedModel(llm=llm, display_name=name, message_id=message_id)
        for (llm, name), message_id in zip(selected_models, response_ids, strict=True)
    ]
    initial_packets.append(
        MultiModelMessageResponseIDInfo(
            user_message_id=user_message.id,
            responses=[
                ModelResponseSlot(
                    message_id=model.message_id, model_name=model.display_name
                )
                for model in models
            ],
        )
        if is_multi
        else MessageResponseIDInfo(
            user_message_id=user_message.id,
            reserved_assistant_message_id=models[0].message_id,
        )
    )
    processing_run_id = user_message.id if is_multi else models[0].message_id

    cache = get_cache_backend()

    # Finish database preparation before model execution starts.
    db_session.commit()

    return ChatTurnSetup(
        initial_packets=initial_packets,
        new_msg_req=new_msg_req,
        chat_session_id=chat_session.id,
        chat_session_project_id=chat_session.project_id,
        incognito_record_mode=chat_session.incognito_record_mode,
        persona_id=persona.id,
        persona=PersonaPromptConfig(
            system_prompt=persona.system_prompt,
            task_prompt=persona.task_prompt,
            datetime_aware=persona.datetime_aware,
            replace_base_system_prompt=persona.replace_base_system_prompt,
        ),
        user_message_id=user_message.id,
        user_identity=user_identity,
        models=models,
        messages=history.messages,
        extracted_context_files=extracted_context_files,
        processing_run_id=processing_run_id,
        reserved_token_count=reserved_token_count,
        reasoning_effort=chat_session.reasoning_effort_override or ReasoningEffort.AUTO,
        search_params=search_params,
        all_injected_file_metadata=history.all_injected_file_metadata,
        available_files=available_files,
        forced_tool_id=forced_tool_id,
        chat_files_for_tools=chat_files_for_tools,
        custom_agent_prompt=custom_agent_prompt,
        user_memory_context=user_memory_context,
        skip_clarification=skip_clarification,
        cache=cache,
        bypass_acl=bypass_acl,
        slack_context=slack_context,
        custom_tool_additional_headers=custom_tool_additional_headers,
        mcp_headers=mcp_headers,
    )


def get_custom_agent_prompt(persona: Persona, chat_session: ChatSession) -> str | None:
    """Select persona instructions, or project instructions for the default persona."""
    # Custom agent instructions take precedence over project instructions, including an empty prompt.
    if persona.id != DEFAULT_PERSONA_ID:
        if persona.replace_base_system_prompt:
            return None
        return persona.system_prompt or None

    if chat_session.project and chat_session.project.instructions:
        return chat_session.project.instructions

    return None
