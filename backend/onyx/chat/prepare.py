from collections.abc import Callable
from functools import partial
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.chat.agent import ChatAgent
from onyx.chat.files import (
    _collect_available_file_ids,
    _convert_loaded_files_to_chat_files,
    _load_context_user_files_for_tools,
    determine_search_params,
    extract_context_files,
    load_chat_files,
    resolve_context_user_files,
    summarize_file_metadata,
)
from onyx.chat.history_store import get_chat_history_store
from onyx.chat.incognito import (
    content_free_file_descriptors,
    incognito_llm_request_policy,
)
from onyx.chat.llm_step import PromptMetadata
from onyx.chat.models import (
    AnswerStreamPart,
    AvailableFiles,
    ChatHistoryMessage,
    ChatHistoryResult,
    ChatTurnSetup,
    CreateChatSessionID,
    PersonaPromptConfig,
    ReservedChatResponse,
)
from onyx.chat.prompt_utils import (
    build_language_section,
    calculate_reserved_tokens,
    get_default_base_system_prompt,
)
from onyx.configs.chat_configs import SKIP_DEEP_RESEARCH_CLARIFICATION
from onyx.configs.constants import (
    DEFAULT_PERSONA_ID,
    DocumentSource,
    MessageType,
    MilestoneRecordType,
)
from onyx.context.search.models import BaseFilters
from onyx.db.chat import (
    create_chat_session_from_request,
    create_new_chat_message,
    get_chat_session_by_id,
    reserve_chat_response_ids,
)
from onyx.db.chat_history import (
    capture_chat_history,
    checkpoint_from_summary,
    convert_chat_history,
    find_summary_for_branch,
    is_last_assistant_message_clarification,
    load_message_branch,
)
from onyx.db.document_set import filter_document_set_names_by_user_access
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import HookPoint, IncognitoRecordMode, record_mode_persists_content
from onyx.db.memory import UserMemoryContext, get_memories
from onyx.db.models import ChatMessage, ChatSession, Persona, User
from onyx.db.tools import capture_persona_tool_configuration, get_tools
from onyx.db.user_file import prepare_chat_file_inputs
from onyx.deep_research.agent import MIN_RESEARCH_CONTEXT_TOKENS, DeepResearchAgent
from onyx.deep_research.tool_definitions import (
    RESEARCH_AGENT_IN_CODE_ID,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.models import (
    ChatFileInput,
    ExtractedContextFiles,
    FileToolMetadata,
    UserFileMetadata,
)
from onyx.file_store.utils import verify_user_files
from onyx.hooks.executor import HookSkipped, HookSoftFailed, execute_hook
from onyx.hooks.points.query_processing import (
    QueryProcessingPayload,
    QueryProcessingResponse,
)
from onyx.llm.cancellation import CancellationSignal, cancellation_scope
from onyx.llm.factory import get_llm_for_persona, get_llm_token_counter
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import AssistantMessage, ReasoningEffort, TextContent
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
from onyx.tools.models import ChatFile, PersonaToolConfiguration, SearchToolUsage
from onyx.tools.tool_constructor import (
    CustomToolConfig,
    FileReaderToolConfig,
    SearchToolConfig,
    construct_tools,
)
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
    return llm.config.model_name


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
        selected_models.append((llm, _build_model_display_name(override, llm)))
    return selected_models


def _accept_message(
    new_msg_req: SendMessageRequest,
    chat_session: ChatSession,
    user: User,
    db_session: Session,
) -> tuple[list[ChatMessage], str | None]:
    """Apply the query hook once; regeneration reuses its accepted user message."""
    message_text = new_msg_req.message
    chat_history, parent_message = load_message_branch(
        chat_session.id, new_msg_req.parent_message_id, db_session
    )

    if parent_message.message_type == MessageType.USER:
        return chat_history, None
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
        message_text = _resolve_query_processing_hook_result(hook_result, message_text)

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

    return chat_history, message_text


class _ChatPreparation(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: UUID
    project_id: int | None
    incognito_record_mode: IncognitoRecordMode | None
    persona_id: int
    persona: PersonaPromptConfig
    base_system_prompt: str
    tool_configuration: PersonaToolConfiguration
    research_tool_id: int | None
    selected_models: list[tuple[LLM, str]]
    history: list[ChatHistoryMessage]
    file_inputs: list[ChatFileInput]
    context_user_files: list[UserFileMetadata]
    available_files: AvailableFiles
    user_message_id: int
    accepted_text: str | None
    user_memory_context: UserMemoryContext
    custom_agent_prompt: str | None
    reserved_token_count: int
    reasoning_effort: ReasoningEffort
    forced_tool_id: int | None
    search_tool_id: int | None
    summary: AssistantMessage | None
    summarized_file_metadata: dict[str, FileToolMetadata]
    skip_clarification: bool


def _prepare_chat_data(
    request: SendMessageRequest,
    user: User,
    db_session: Session,
    llm_overrides: list[LLMOverride] | None,
    litellm_additional_headers: dict[str, str] | None,
) -> _ChatPreparation:
    chat_session = _load_session(request, user, db_session)
    persona = chat_session.persona
    selected_models = _select_models(
        request,
        chat_session,
        user,
        llm_overrides,
        litellm_additional_headers,
        db_session,
    )
    token_counter = get_llm_token_counter(selected_models[0][0])
    chat_history, accepted_text = _accept_message(
        request, chat_session, user, db_session
    )
    user_message_id = chat_history[-1].id
    context_user_files = [
        UserFileMetadata.model_validate(file)
        for file in resolve_context_user_files(
            persona, chat_session.project_id, user.id, db_session
        )
    ]
    available_files = _collect_available_file_ids(chat_history, context_user_files)
    memory = get_memories(user, db_session)
    custom_prompt = get_custom_agent_prompt(persona, chat_session)
    base_system_prompt = get_default_base_system_prompt(db_session)
    reserved_tokens = calculate_reserved_tokens(
        db_session=db_session,
        persona_system_prompt=substitute_user_placeholders(
            (persona.system_prompt or "") + (custom_prompt or ""),
            memory.user_info.placeholder_values,
        ),
        token_counter=token_counter,
        files=request.file_descriptors,
        user_memory_context=memory if user.use_memories else memory.without_memories(),
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
    if request.deep_research and research_tool_id is None:
        raise ValueError("Research tool configuration is missing")
    tool_names = {tool.id: tool.name for tool in tools}
    forced_tool_id = request.forced_tool_id
    if forced_tool_id in {tool.id for tool in tools if not tool.enabled}:
        forced_tool_id = None
    summary_message = find_summary_for_branch(db_session, chat_history)
    checkpoint = checkpoint_from_summary(summary_message)
    if checkpoint is not None:
        # Exact coverage was measured after applying any legacy summary baseline.
        summary_message = find_summary_for_branch(
            db_session, chat_history, legacy_only=True
        )
    summarized_file_metadata: dict[str, FileToolMetadata] = {}
    if summary_message and summary_message.last_summarized_message_id:
        cutoff = summary_message.last_summarized_message_id
        summarized_file_metadata = summarize_file_metadata(
            [message for message in chat_history if message.id <= cutoff]
        )
        chat_history = [message for message in chat_history if message.id > cutoff]
    descriptors = {
        descriptor["id"]: descriptor
        for message in chat_history
        for descriptor in message.files or []
    }
    return _ChatPreparation(
        session_id=chat_session.id,
        project_id=chat_session.project_id,
        incognito_record_mode=chat_session.incognito_record_mode,
        persona_id=persona.id,
        persona=PersonaPromptConfig(
            system_prompt=persona.system_prompt,
            task_prompt=persona.task_prompt,
            datetime_aware=persona.datetime_aware,
            replace_base_system_prompt=persona.replace_base_system_prompt,
        ),
        base_system_prompt=base_system_prompt,
        tool_configuration=capture_persona_tool_configuration(persona),
        research_tool_id=research_tool_id,
        selected_models=selected_models,
        history=capture_chat_history(
            chat_history,
            tool_names,
            token_counter,
            checkpoint,
        ),
        file_inputs=prepare_chat_file_inputs(list(descriptors.values()), db_session),
        context_user_files=context_user_files,
        available_files=available_files,
        user_message_id=user_message_id,
        accepted_text=accepted_text,
        user_memory_context=memory,
        custom_agent_prompt=custom_prompt,
        reserved_token_count=reserved_tokens,
        reasoning_effort=chat_session.reasoning_effort_override or ReasoningEffort.AUTO,
        forced_tool_id=forced_tool_id,
        search_tool_id=next(
            (tool.id for tool in tools if tool.in_code_tool_id == SEARCH_TOOL_ID), None
        ),
        summary=AssistantMessage(
            content=[TextContent(text=summary_message.message)],
            metadata=PromptMetadata(token_count=summary_message.token_count),
        )
        if summary_message and summary_message.last_summarized_message_id is not None
        else None,
        summarized_file_metadata=summarized_file_metadata,
        skip_clarification=is_last_assistant_message_clarification(chat_history),
    )


class _PreparedHistory(BaseModel):
    previous_run_id: str | None
    history: ChatHistoryResult
    files: list[ChatFile]


def _prepare_history(
    prepared: _ChatPreparation,
    extracted_context_files: ExtractedContextFiles,
    token_counter: Callable[[str], int],
    additional_context: str | None,
) -> _PreparedHistory:
    files = load_chat_files(prepared.file_inputs)
    tool_files = _convert_loaded_files_to_chat_files(files)
    tool_files.extend(
        _load_context_user_files_for_tools(
            prepared.context_user_files, {file.filename for file in tool_files}
        )
    )
    history = convert_chat_history(
        chat_history=prepared.history,
        files=files,
        context_image_files=extracted_context_files.image_files,
        additional_context=additional_context,
        token_counter=token_counter,
    )
    previous_run_id = next(
        (
            message.agent_run_id
            for message in reversed(prepared.history)
            if message.agent_run_id is not None
        ),
        None,
    )
    history_store = get_chat_history_store(
        message_id=prepared.user_message_id,
        chat_session_id=prepared.session_id,
        persist_content=record_mode_persists_content(prepared.incognito_record_mode),
    )
    messages, previous_run_id = history_store.prepare_messages(
        history.messages, previous_run_id, prepared.accepted_text
    )
    file_metadata = (
        history.all_injected_file_metadata
        if any(
            tool.in_code_tool_id == FILE_READER_TOOL_ID
            for tool in prepared.tool_configuration.tools
        )
        else {}
    )
    for file_id, metadata in prepared.summarized_file_metadata.items():
        file_metadata.setdefault(file_id, metadata)
    if prepared.summary:
        messages.insert(0, prepared.summary)
    return _PreparedHistory(
        previous_run_id=previous_run_id,
        history=ChatHistoryResult(
            messages=messages, all_injected_file_metadata=file_metadata
        ),
        files=tool_files,
    )


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
    with get_session_with_current_tenant() as session:
        prepared = _prepare_chat_data(
            new_msg_req,
            user,
            session,
            llm_overrides,
            litellm_additional_headers,
        )
    token_counter = get_llm_token_counter(prepared.selected_models[0][0])
    extracted_files = extract_context_files(
        user_files=prepared.context_user_files,
        llm_max_context_window=min(
            llm.config.max_input_tokens for llm, _ in prepared.selected_models
        ),
        reserved_token_count=prepared.reserved_token_count,
    )
    search_params = determine_search_params(
        prepared.persona_id, prepared.project_id, extracted_files
    )
    forced_tool_id = prepared.forced_tool_id
    if (
        search_params.search_usage == SearchToolUsage.DISABLED
        and forced_tool_id == prepared.search_tool_id
    ):
        forced_tool_id = None
    history = _prepare_history(
        prepared,
        extracted_files,
        token_counter,
        additional_context or new_msg_req.additional_context,
    )
    with get_session_with_current_tenant() as session:
        response_ids = reserve_chat_response_ids(
            db_session=session,
            chat_session_id=prepared.session_id,
            parent_message_id=prepared.user_message_id,
            model_display_names=[name for _, name in prepared.selected_models],
        )
    models = [
        ReservedChatResponse(llm=llm, display_name=name, message_id=message_id)
        for (llm, name), message_id in zip(
            prepared.selected_models, response_ids, strict=True
        )
    ]
    initial_packets: list[AnswerStreamPart] = []
    if new_msg_req.chat_session_id is None:
        initial_packets.append(
            CreateChatSessionID(
                chat_session_id=prepared.session_id,
                incognito=prepared.incognito_record_mode is not None,
            )
        )
    is_multi = bool(llm_overrides)
    initial_packets.append(
        MultiModelMessageResponseIDInfo(
            user_message_id=prepared.user_message_id,
            responses=[
                ModelResponseSlot(
                    message_id=model.message_id, model_name=model.display_name
                )
                for model in models
            ],
        )
        if is_multi
        else MessageResponseIDInfo(
            user_message_id=prepared.user_message_id,
            reserved_assistant_message_id=models[0].message_id,
        )
    )
    return ChatTurnSetup(
        initial_packets=initial_packets,
        new_msg_req=new_msg_req,
        chat_session_id=prepared.session_id,
        chat_session_project_id=prepared.project_id,
        incognito_record_mode=prepared.incognito_record_mode,
        persona_id=prepared.persona_id,
        persona=prepared.persona,
        base_system_prompt=prepared.base_system_prompt,
        tool_configuration=prepared.tool_configuration,
        research_tool_id=prepared.research_tool_id,
        checkpoint=next(
            (
                message.checkpoint
                for message in reversed(prepared.history)
                if message.checkpoint is not None
            ),
            None,
        ),
        user_message_id=prepared.user_message_id,
        user_identity=LLMUserIdentity(
            user_id="anonymous_user"
            if user.is_anonymous
            else user.email or str(user.id),
            session_id=str(prepared.session_id),
        ),
        responses=models,
        messages=history.history.messages[:-1],
        input_messages=history.history.messages[-1:],
        previous_run_id=history.previous_run_id,
        extracted_context_files=extracted_files,
        stream_id=prepared.user_message_id if is_multi else models[0].message_id,
        reasoning_effort=prepared.reasoning_effort,
        search_params=search_params,
        all_injected_file_metadata=history.history.all_injected_file_metadata,
        available_files=prepared.available_files,
        forced_tool_id=forced_tool_id,
        chat_files_for_tools=history.files,
        custom_agent_prompt=prepared.custom_agent_prompt,
        user_memory_context=prepared.user_memory_context,
        skip_clarification=prepared.skip_clarification,
        cache=get_cache_backend(),
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


def _should_enable_slack_search(persona_id: int, filters: BaseFilters | None) -> bool:
    source_types = filters.source_type if filters else None
    return (source_types is not None and DocumentSource.SLACK in source_types) or (
        persona_id == DEFAULT_PERSONA_ID and source_types is None
    )


def create_chat_agent(
    setup: ChatTurnSetup,
    user: User,
    response_index: int,
    cancellation: CancellationSignal,
    auto_detect_search_filters: bool,
) -> ChatAgent | DeepResearchAgent:
    llm = setup.responses[response_index].llm
    with cancellation_scope(cancellation):
        cancellation.check()
        # Tools open DB sessions on demand, so model I/O cannot retain a connection.
        tools_by_type = construct_tools(
            configuration=setup.tool_configuration,
            user=user,
            llm=llm,
            search_tool_config=SearchToolConfig(
                user_selected_filters=setup.new_msg_req.internal_search_filters,
                project_id_filter=setup.search_params.project_id_filter,
                persona_id_filter=setup.search_params.persona_id_filter,
                slack_context=setup.slack_context,
                enable_slack_search=_should_enable_slack_search(
                    setup.persona_id, setup.new_msg_req.internal_search_filters
                ),
                auto_detect_filters=auto_detect_search_filters,
            ),
            custom_tool_config=CustomToolConfig(
                chat_session_id=setup.chat_session_id,
                message_id=setup.user_message_id,
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
        tools = [tool for tool_list in tools_by_type.values() for tool in tool_list]

        if setup.forced_tool_id and setup.forced_tool_id not in {
            tool.id for tool in tools
        }:
            raise ValueError(f"Forced tool {setup.forced_tool_id} not found in tools")

        history_store = get_chat_history_store(
            message_id=setup.user_message_id,
            chat_session_id=setup.chat_session_id,
            persist_content=record_mode_persists_content(setup.incognito_record_mode),
        )
        agent_id = history_store.root_agent_id(str(setup.chat_session_id))

        if len(setup.responses) == 1 and setup.new_msg_req.deep_research:
            if setup.chat_session_project_id:
                raise RuntimeError("Deep research is not supported for projects")
            if setup.research_tool_id is None:
                raise ValueError("Deep research tool configuration is missing")
            if llm.config.max_input_tokens < MIN_RESEARCH_CONTEXT_TOKENS:
                raise ValueError(
                    "Deep research requires a model with at least 50,000 input tokens"
                )
            return DeepResearchAgent(
                agent_id=agent_id,
                messages=list(setup.messages),
                allowed_tools=tools,
                llm=llm,
                token_counter=get_llm_token_counter(llm),
                user_identity=setup.user_identity,
                language_section=build_language_section(
                    setup.user_memory_context.user_info.language
                ),
                reasoning_effort=setup.reasoning_effort,
                all_injected_file_metadata=setup.all_injected_file_metadata,
                skip_clarification=SKIP_DEEP_RESEARCH_CLARIFICATION
                or setup.skip_clarification,
                checkpoint=setup.checkpoint,
                previous_run_id=setup.previous_run_id,
            )
        return ChatAgent(
            agent_id=agent_id,
            messages=list(setup.messages),
            tools=tools,
            custom_agent_prompt=setup.custom_agent_prompt,
            context_files=setup.extracted_context_files,
            persona=setup.persona,
            base_system_prompt=setup.base_system_prompt,
            checkpoint=setup.checkpoint,
            previous_run_id=setup.previous_run_id,
            user_memory_context=setup.user_memory_context,
            llm=llm,
            token_counter=get_llm_token_counter(llm),
            forced_tool_id=setup.forced_tool_id,
            user_identity=setup.user_identity,
            chat_files=setup.chat_files_for_tools,
            reasoning_effort=setup.reasoning_effort,
            include_citations=setup.new_msg_req.include_citations,
            all_injected_file_metadata=setup.all_injected_file_metadata,
            inject_memories_in_prompt=user.use_memories,
        )
