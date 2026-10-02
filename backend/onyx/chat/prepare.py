from collections.abc import Callable
from functools import partial

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.cache.factory import get_cache_backend
from onyx.chat.agent import ChatAgent
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
from onyx.chat.models import (
    ChatHistoryMessage,
    ChatHistoryResult,
    ChatTurnSetup,
    PersonaPromptConfig,
    ReservedChatResponse,
)
from onyx.chat.prompt_formatting import PromptMetadata
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
    create_new_chat_message,
    get_chat_session_by_id,
    reserve_chat_response_ids,
)
from onyx.db.chat_history import (
    checkpoint_from_summary,
    find_summary_for_branch,
    load_message_branch,
)
from onyx.db.document_set import filter_document_set_names_by_user_access
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import HookPoint, record_mode_persists_content
from onyx.db.memory import get_memories
from onyx.db.models import ChatSession, Persona, User
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
from onyx.llm.models import AssistantMessage, ReasoningEffort, TextContent, UserMessage
from onyx.llm.override_models import LLMOverride
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.onyxbot.slack.models import SlackContext
from onyx.prompts.prompt_utils import substitute_user_placeholders
from onyx.server.query_and_chat.models import (
    SendMessageRequest,
)
from onyx.server.usage_limits import check_llm_cost_limit_for_provider
from onyx.tools.constants import FILE_READER_TOOL_ID, SEARCH_TOOL_ID
from onyx.tools.models import ChatFile, SearchToolUsage
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
    return _resolve_query_processing_hook_result(hook_result, message_text)


class _PreparedHistory(BaseModel):
    previous_run_id: str | None
    history: ChatHistoryResult
    files: list[ChatFile]


def _prepare_history(
    chat_history: list[ChatHistoryMessage],
    file_inputs: list[ChatFileInput],
    context_user_files: list[UserFileMetadata],
    extracted_context_files: ExtractedContextFiles,
    token_counter: Callable[[str], int],
    additional_context: str | None,
) -> _PreparedHistory:
    files = load_chat_files(file_inputs)
    tool_files = _convert_loaded_files_to_chat_files(files)
    tool_files.extend(
        _load_context_user_files_for_tools(
            context_user_files, {file.filename for file in tool_files}
        )
    )
    history = convert_chat_history(
        chat_history=chat_history,
        files=files,
        context_image_files=extracted_context_files.image_files,
        additional_context=additional_context,
        token_counter=token_counter,
    )
    previous_run_id = next(
        (
            message.agent_run_id
            for message in reversed(chat_history)
            if message.agent_run_id is not None
        ),
        None,
    )
    return _PreparedHistory(
        previous_run_id=previous_run_id,
        history=history,
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
    admission = ChatTurnAdmission(
        get_cache_backend(operation_timeout_s=ADMISSION_CACHE_TIMEOUT_S)
    )
    try:
        with get_session_with_current_tenant() as session:
            chat_session = _load_session(new_msg_req, user, session)
            # Reserve the session before model setup or changes to its message tree.
            admission.claim(chat_session.id)
            selected_models = _select_models(
                new_msg_req,
                chat_session,
                user,
                llm_overrides,
                litellm_additional_headers,
                session,
            )
            token_counter = get_llm_token_counter(selected_models[0][0])
            admission.refresh()
            chat_history, parent_message = load_message_branch(
                chat_session.id, new_msg_req.parent_message_id, session
            )
            accepted_text = None
            # Regeneration reuses the user message and its accepted query.
            if parent_message.message_type != MessageType.USER:
                accepted_text = _process_query(
                    new_msg_req.message, chat_session, user, session
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
                    db_session=session,
                    commit=True,
                )
                chat_history.append(user_message)
            persona = chat_session.persona
            user_message_id = chat_history[-1].id
            context_user_files = [
                UserFileMetadata.model_validate(file)
                for file in resolve_context_user_files(
                    persona, chat_session.project_id, user.id, session
                )
            ]
            # Collect file IDs for the file reader tool *before* summary truncation so
            # that files attached to older (summarized-away) messages are still accessible
            # via the FileReaderTool.
            available_files = _collect_available_file_ids(
                chat_history, context_user_files
            )
            memory = get_memories(user, session)
            custom_prompt = get_custom_agent_prompt(persona, chat_session)
            base_system_prompt = get_default_base_system_prompt(session)
            # Reserve against the placeholder-substituted text sent to the model,
            # so long directory values cannot invalidate the reservation.
            reserved_tokens = calculate_reserved_tokens(
                db_session=session,
                persona_system_prompt=substitute_user_placeholders(
                    (persona.system_prompt or "") + (custom_prompt or ""),
                    memory.user_info.placeholder_values,
                ),
                token_counter=token_counter,
                files=new_msg_req.file_descriptors,
                user_memory_context=memory
                if user.use_memories
                else memory.without_memories(),
                base_system_prompt=base_system_prompt,
            )
            tools = get_tools(session)
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
            if forced_tool_id in {tool.id for tool in tools if not tool.enabled}:
                forced_tool_id = None
            summary_message = find_summary_for_branch(session, chat_history)
            checkpoint = checkpoint_from_summary(summary_message)
            if checkpoint is not None:
                # Exact coverage was measured after applying any legacy summary baseline.
                summary_message = find_summary_for_branch(
                    session, chat_history, legacy_only=True
                )
            summarized_file_metadata: dict[str, FileToolMetadata] = {}
            if summary_message and summary_message.last_summarized_message_id:
                cutoff = summary_message.last_summarized_message_id
                summarized_file_metadata = summarize_file_metadata(
                    [message for message in chat_history if message.id <= cutoff]
                )
                chat_history = [
                    message for message in chat_history if message.id > cutoff
                ]
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
            captured_history = capture_chat_history(
                chat_history,
                tool_names,
                token_counter,
                checkpoint,
            )
            file_inputs = prepare_chat_file_inputs(list(descriptors.values()), session)
            reasoning_effort = (
                chat_session.reasoning_effort_override or ReasoningEffort.AUTO
            )
            search_tool_id = next(
                (tool.id for tool in tools if tool.in_code_tool_id == SEARCH_TOOL_ID),
                None,
            )
            summary = (
                AssistantMessage(
                    content=[TextContent(text=summary_message.message)],
                    metadata=PromptMetadata(token_count=summary_message.token_count),
                )
                if summary_message
                and summary_message.last_summarized_message_id is not None
                else None
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
        history = _prepare_history(
            chat_history=captured_history,
            file_inputs=file_inputs,
            context_user_files=context_user_files,
            extracted_context_files=extracted_files,
            token_counter=token_counter,
            additional_context=additional_context or new_msg_req.additional_context,
        )
        file_metadata = (
            history.history.all_injected_file_metadata
            if any(
                tool.in_code_tool_id == FILE_READER_TOOL_ID
                for tool in tool_configuration.tools
            )
            else {}
        )
        # Summary-truncated messages no longer carry file_id tags in the history.
        # Keep their metadata so the model can still discover these files through
        # the forgotten-file notice after context-window truncation.
        for file_id, metadata in summarized_file_metadata.items():
            file_metadata.setdefault(file_id, metadata)
        history.history.all_injected_file_metadata = file_metadata
        admission.refresh()
        # Resolve backend history before checking ownership for the input write.
        history_store = get_chat_history_store(
            message_id=user_message_id,
            chat_session_id=chat_session_id,
            persist_content=record_mode_persists_content(incognito_record_mode),
        )
        should_save_user_message = (
            accepted_text is not None
            and bool(history.history.messages)
            and isinstance(history.history.messages[-1], UserMessage)
        )
        history.history.messages, history.previous_run_id = (
            history_store.prepare_messages(
                history.history.messages, history.previous_run_id, accepted_text
            )
        )
        if should_save_user_message:
            new_user_message = (
                history.history.messages[-1] if history.history.messages else None
            )
            if not isinstance(new_user_message, UserMessage):
                raise ValueError(
                    "History storage must retain the accepted user message last"
                )
            admission.refresh()
            history_store.save_user_message(new_user_message)
        # Prepend the summary after loading history; incognito history comes from Redis.
        if summary:
            history.history.messages.insert(0, summary)
        admission.refresh()
        # Reserve assistant message IDs so each model response has a saved identity.
        with get_session_with_current_tenant() as session:
            response_ids = reserve_chat_response_ids(
                db_session=session,
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
            messages=history.history.messages[:-1],
            input_messages=history.history.messages[-1:],
            previous_run_id=history.previous_run_id,
            extracted_context_files=extracted_files,
            stream_id=user_message_id if is_multi else models[0].message_id,
            reasoning_effort=reasoning_effort,
            search_params=search_params,
            all_injected_file_metadata=history.history.all_injected_file_metadata,
            available_files=available_files,
            forced_tool_id=forced_tool_id,
            chat_files_for_tools=history.files,
            custom_agent_prompt=custom_prompt,
            user_memory_context=memory,
            skip_clarification=skip_clarification,
            cache=get_cache_backend(),
            admission=admission,
            slack_context=slack_context,
            custom_tool_additional_headers=custom_tool_additional_headers,
            mcp_headers=mcp_headers,
        )
    except BaseException:
        admission.release()
        raise


def get_custom_agent_prompt(persona: Persona, chat_session: ChatSession) -> str | None:
    """Select persona instructions, or project instructions for the default persona.

    A custom agent retains its own prompt inside a project. A prompt that
    replaces the base system prompt is not also added as a custom prompt.
    Empty persona prompts become None rather than falling back to the project.
    """
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
