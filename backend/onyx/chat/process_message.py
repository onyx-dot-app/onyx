"""
IMPORTANT: familiarize yourself with the design concepts prior to contributing to this file.
An overview can be found in the README.md file in this directory.
"""

import re
from concurrent.futures import Future
from functools import partial
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.chat.chat_processing_checker import (
    ADMISSION_CACHE_TIMEOUT_S,
    ChatTurnAdmission,
    is_chat_session_processing,
)
from onyx.chat.chat_utils import (
    capture_chat_history,
    convert_chat_history,
    create_chat_session_from_request,
    is_last_assistant_message_clarification,
)
from onyx.chat.errors import chat_error
from onyx.chat.execution import chat_turn_work, host_agent_work, start_chat_turn
from onyx.chat.files import (
    collect_available_file_ids,
    convert_loaded_files_to_chat_files,
    determine_search_params,
    extract_context_files,
    load_chat_files,
    load_context_user_files_for_tools,
    resolve_context_user_files,
)
from onyx.chat.history_store import RedisChatHistoryStore
from onyx.chat.incognito import (
    content_free_file_descriptors,
    incognito_llm_request_policy,
)
from onyx.chat.incognito_context import incognito_session_ended
from onyx.chat.models import (
    AnswerStream,
    ChatFullResponse,
    ChatInbox,
    ChatResponseOutcome,
    ChatTurnSetup,
    CreateChatSessionID,
    PersonaPromptConfig,
    QueuedChatTurn,
    ReservedChatResponse,
    ToolCallResponse,
)
from onyx.chat.prompt_utils import (
    calculate_reserved_tokens,
    get_default_base_system_prompt,
)
from onyx.chat.run_store import interrupt_ownerless_responses
from onyx.chat.stream_buffer import ChatStream
from onyx.configs.chat_configs import CHAT_RESPONSE_WAIT_TIMEOUT_S
from onyx.configs.constants import (
    DEFAULT_PERSONA_ID,
    MessageType,
    MilestoneRecordType,
)
from onyx.db.chat import (
    checkpoint_from_summary,
    create_new_chat_message,
    find_summary_for_branch,
    get_chat_session_by_id,
    load_message_branch,
    reserve_chat_response_ids,
    set_response_model_names__no_commit,
)
from onyx.db.chat_inputs import (
    accept_queued_turn__no_commit,
    fail_inbox_start__no_commit,
    fail_response_start__no_commit,
    read_chat_inbox,
)
from onyx.db.document_set import require_document_set_access
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import HookPoint, Permission, record_mode_persists_content
from onyx.db.memory import get_memories
from onyx.db.models import ChatSession, User
from onyx.db.tools import capture_persona_tool_configuration, get_tools
from onyx.db.user_file import capture_user_file_metadata, prepare_chat_file_inputs
from onyx.db.users import fetch_user_by_id
from onyx.deep_research.agent import MIN_RESEARCH_CONTEXT_TOKENS
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
from onyx.llm.models import ReasoningEffort
from onyx.llm.override_models import LLMOverride
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.onyxbot.slack.models import SlackContext
from onyx.prompts.prompt_utils import substitute_user_placeholders
from onyx.server.query_and_chat.models import (
    MessageResponseIDInfo,
    SendMessageRequest,
)
from onyx.server.query_and_chat.streaming_models import (
    StreamingError,
)
from onyx.server.query_and_chat.token_limit import (
    check_model_spend_limits,
    check_token_rate_limits,
)
from onyx.server.usage_limits import check_llm_cost_limit_for_provider
from onyx.tools.constants import (
    CODING_AGENT_TOOL_ID,
    FILE_READER_TOOL_ID,
    SEARCH_TOOL_ID,
)
from onyx.tools.models import SearchToolUsage
from onyx.tracing.framework.scope import Scope
from onyx.utils.fleet_query_telemetry import QueryObservation, telemetry_chat
from onyx.utils.logger import setup_logger
from onyx.utils.telemetry import mt_cloud_telemetry
from onyx.utils.threadpool_concurrency import start_thread_future
from onyx.utils.timing import log_function_time, log_generator_function_time
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()
ERROR_TYPE_CANCELLED = "cancelled"


def _load_session(
    request: SendMessageRequest, user: User, db_session: Session
) -> ChatSession:
    filters = request.internal_search_filters
    require_document_set_access(
        db_session, filters.document_set if filters else None, user
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
        check_model_spend_limits(user, llm.config.model_configuration_id)
        display_name = llm.config.model_name
        if override is not None:
            display_name = (
                override.display_name or override.model_version or display_name
            )
        selected_models.append((llm, display_name))
    return selected_models


def process_chat_query(
    message_text: str,
    chat_session: ChatSession,
    user: User,
    db_session: Session,
) -> str:
    """Apply query hooks before user text enters chat history or the pending queue."""
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
    queued_turn: QueuedChatTurn | None = None,
    agent_host: bool = False,
) -> ChatTurnSetup:
    """Capture configuration, load files, then reserve responses before execution.

    A queued turn starts from its accepted question: a submitted message, or a
    hidden AGENT_RESULTS message whose response's first step receives the results.
    It accepts the question and reserves its response right after admission, so a
    later failure saves an error response that pauses the queue.

    An agent host adds no messages. Its setup belongs to the selected response,
    the request's parent, and its agents run with that configuration.
    """
    results_turn = queued_turn is not None and queued_turn.message is None
    admission = ChatTurnAdmission(
        get_cache_backend(operation_timeout_s=ADMISSION_CACHE_TIMEOUT_S)
    )
    response_ids: list[int] = []
    try:
        with get_session_with_current_tenant() as db_session:
            chat_session = _load_session(new_msg_req, user, db_session)
            # Reserve the session before model setup or changes to its message tree.
            admission.claim(chat_session.id)
            if (
                queued_turn is not None or agent_host
            ) and chat_session.tool_selection is not None:
                # A turn the server starts, or its agent host, uses the chat's
                # current tools and filters.
                new_msg_req = SendMessageRequest.model_validate(
                    new_msg_req.model_dump() | chat_session.tool_selection.model_dump()
                )
            alternate_model = (
                (chat_session.current_alternate_model or "").split("__")
                if (queued_turn is not None or agent_host)
                and new_msg_req.llm_override is None
                else []
            )
            if len(alternate_model) >= 3:
                # Without its own model, a turn the server starts uses the model
                # the picker last sent with: name__provider__model[__mc:id].
                provider_name, _provider, *model_parts = alternate_model
                configuration_id = (
                    int(model_parts.pop()[3:])
                    if len(model_parts) > 1 and re.fullmatch(r"mc:\d+", model_parts[-1])
                    else None
                )
                new_msg_req = new_msg_req.model_copy(
                    update={
                        "llm_override": LLMOverride(
                            model_provider=provider_name,
                            model_version="__".join(model_parts),
                            model_configuration_id=configuration_id,
                        )
                    }
                )
            chat_history, parent_message = load_message_branch(
                chat_session.id, new_msg_req.parent_message_id, db_session
            )
            accepted_text = None
            if queued_turn is not None:
                # Submitted input already passed the hook before entering the queue.
                accepted_text = new_msg_req.message
                accept_queued_turn__no_commit(db_session, chat_session.id, queued_turn)
                chat_history.append(
                    create_new_chat_message(
                        chat_session_id=chat_session.id,
                        parent_message=parent_message,
                        message=accepted_text,
                        # Use one tokenizer for stored counts, including after model switches.
                        token_count=len(
                            get_tokenizer(None, None).encode(accepted_text)
                        ),
                        message_type=MessageType.AGENT_RESULTS
                        if results_turn
                        else MessageType.USER,
                        db_session=db_session,
                        commit=False,
                    )
                )
                # The model name is known after selection.
                response_ids = reserve_chat_response_ids(
                    db_session=db_session,
                    chat_session_id=chat_session.id,
                    parent_message_id=chat_history[-1].id,
                    model_display_names=[""],
                )
                # Write access can end while a message waits; the error response
                # pauses the queue instead of retrying the turn.
                if not has_global_permission(user, Permission.WRITE_CHAT):
                    raise OnyxError(OnyxErrorCode.INSUFFICIENT_PERMISSIONS)
                # Document-set access can end too; check the saved filters again.
                filters = new_msg_req.internal_search_filters
                require_document_set_access(
                    db_session, filters.document_set if filters else None, user
                )
                check_token_rate_limits(user)
            elif agent_host:
                # Hosted agents spend the owner's budget for every model.
                check_token_rate_limits(user)
                response_ids = [parent_message.id]
            if not results_turn and not agent_host:
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
                        "origin": new_msg_req.origin.value,
                        "has_files": len(new_msg_req.file_descriptors) > 0,
                        "has_project": chat_session.project_id is not None,
                        "has_persona": persona is not None
                        and persona.id != DEFAULT_PERSONA_ID,
                        "deep_research": new_msg_req.deep_research,
                    },
                )
            selected_models = _select_models(
                new_msg_req,
                chat_session,
                user,
                llm_overrides,
                litellm_additional_headers,
                db_session,
            )
            if new_msg_req.deep_research:
                # Validate before the user message is saved.
                if chat_session.incognito_record_mode is not None:
                    raise OnyxError(
                        OnyxErrorCode.BAD_REQUEST,
                        "Deep research is not available in incognito. Start a normal chat to use it.",
                    )
                if chat_session.project_id:
                    raise OnyxError(
                        OnyxErrorCode.BAD_REQUEST,
                        "Deep research is not supported for projects",
                    )
                if any(
                    llm.config.max_input_tokens < MIN_RESEARCH_CONTEXT_TOKENS
                    for llm, _ in selected_models
                ):
                    raise OnyxError(
                        OnyxErrorCode.BAD_REQUEST,
                        "Deep research requires a model with at least 50,000 input tokens",
                    )
            if (
                chat_session.incognito_record_mode is not None
                and new_msg_req.preferred_tool_id is not None
                and any(
                    tool.id == new_msg_req.preferred_tool_id
                    and tool.in_code_tool_id == CODING_AGENT_TOOL_ID
                    for tool in chat_session.persona.tools
                )
            ):
                # Incognito offers no coding agent; reject before the question is saved.
                raise OnyxError(
                    OnyxErrorCode.BAD_REQUEST,
                    "The Coding Agent is not available in incognito. Start a normal chat to use it.",
                )
            if queued_turn is not None:
                set_response_model_names__no_commit(
                    db_session,
                    {
                        response_id: display_name
                        for response_id, (_, display_name) in zip(
                            response_ids, selected_models, strict=True
                        )
                    },
                )
                db_session.commit()
            token_counter = get_llm_token_counter(selected_models[0][0])
            # Regeneration reuses the user message and its accepted query.
            if (
                queued_turn is None
                and not agent_host
                and parent_message.message_type != MessageType.USER
            ):
                accepted_text = process_chat_query(
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
                    commit=False,
                )
                chat_history.append(user_message)
                # The question and its responses are saved together, so a later
                # preparation failure saves an error response that queued input
                # can follow.
                response_ids = reserve_chat_response_ids(
                    db_session=db_session,
                    chat_session_id=chat_session.id,
                    parent_message_id=user_message.id,
                    model_display_names=[name for _, name in selected_models],
                )
            persona = chat_session.persona
            response_parent_id = chat_history[-1].id
            # Clients render no question for a follow-up response.
            user_message_id = None if results_turn or agent_host else response_parent_id
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
            preferred_tool_id = new_msg_req.preferred_tool_id
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
            if accepted_text is not None and not record_mode_persists_content(
                incognito_record_mode
            ):
                # Filenames belong to the live input, not the content-free database row.
                descriptors.update(
                    {
                        descriptor["id"]: descriptor
                        for descriptor in new_msg_req.file_descriptors
                    }
                )
            file_inputs = prepare_chat_file_inputs(
                list(descriptors.values()), db_session
            )
            reasoning_effort = (
                chat_session.reasoning_effort_override or ReasoningEffort.AUTO
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
        # Inline project context replaces retrieval for this request.
        if (
            search_params.search_usage == SearchToolUsage.DISABLED
            and (
                new_msg_req.allowed_tool_ids is None
                or preferred_tool_id in new_msg_req.allowed_tool_ids
            )
            and any(
                tool.id == preferred_tool_id
                and tool.in_code_tool_id == SEARCH_TOOL_ID
                and tool.enabled
                for tool in tool_configuration.tools
            )
        ):
            preferred_tool_id = None
        # Temporary history already owns earlier attachment text. Only new inputs need extraction.
        text_file_ids: set[str] | None = None
        if not record_mode_persists_content(incognito_record_mode):
            text_file_ids = (
                {descriptor["id"] for descriptor in new_msg_req.file_descriptors}
                if accepted_text is not None
                else set()
            )
        loaded_files = load_chat_files(file_inputs, text_file_ids=text_file_ids)
        chat_files_for_tools = convert_loaded_files_to_chat_files(loaded_files)
        chat_files_for_tools.extend(
            load_context_user_files_for_tools(
                context_user_files, {file.filename for file in chat_files_for_tools}
            )
        )
        history = convert_chat_history(
            chat_history=captured_history,
            files=loaded_files,
        )
        if not any(
            tool.in_code_tool_id == FILE_READER_TOOL_ID
            for tool in tool_configuration.tools
        ):
            history.all_injected_file_metadata = {}
        # Persistent history and the accepted user row are already loaded and saved.
        if not record_mode_persists_content(incognito_record_mode):
            admission.refresh()
            history_store = RedisChatHistoryStore(
                message_id=response_parent_id,
                chat_session_id=chat_session_id,
                admission=admission,
            )
            history, previous_run_id, checkpoint = history_store.prepare_messages(
                history, accepted_text
            )
            admission.refresh()
            history_store.save_user_messages(history)
            if incognito_session_ended(chat_session_id):
                raise RuntimeError("Incognito session ended")
        admission.refresh()
        # Reserve assistant message IDs so each model response has a saved identity.
        with get_session_with_current_tenant() as db_session:
            if not response_ids:
                response_ids = reserve_chat_response_ids(
                    db_session=db_session,
                    chat_session_id=chat_session_id,
                    parent_message_id=response_parent_id,
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
            checkpoint=checkpoint,
            user_message_id=user_message_id,
            user_identity=LLMUserIdentity(
                user_id="anonymous_user"
                if user.is_anonymous
                else user.email or str(user.id),
                session_id=str(chat_session_id),
            ),
            responses=models,
            messages=history.messages[: history.input_start],
            input_messages=history.messages[history.input_start :],
            previous_run_id=previous_run_id,
            additional_context=additional_context or new_msg_req.additional_context,
            extracted_context_files=extracted_files,
            stream_id=response_parent_id if is_multi else models[0].message_id,
            reasoning_effort=reasoning_effort,
            search_params=search_params,
            all_injected_file_metadata=history.all_injected_file_metadata,
            available_files=available_files,
            preferred_tool_id=preferred_tool_id,
            preferred_tool_saved=queued_turn is not None,
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
        try:
            if response_ids:
                with get_session_with_current_tenant() as db_session:
                    for response_id in response_ids:
                        fail_response_start__no_commit(db_session, response_id)
                    db_session.commit()
        except Exception:
            logger.exception("Could not save chat preparation failure")
        finally:
            admission.release()
        raise


def read_repaired_chat_inbox(chat_session_id: UUID, cache: CacheBackend) -> ChatInbox:
    """Read the inbox after saving running responses that lost their owner.

    An ownerless response never finishes, so the agent waiting for it would not
    wake, and a running root response would block the queue.
    """
    with get_session_with_current_tenant() as db_session:
        inbox = read_chat_inbox(db_session, chat_session_id)
    if interrupt_ownerless_responses(
        cache, get_current_tenant_id(), inbox.unfinished_response_ids
    ):
        with get_session_with_current_tenant() as db_session:
            inbox = read_chat_inbox(db_session, chat_session_id)
    return inbox


def dispatch_pending_chat_messages(
    chat_session_id: UUID,
    user_id: UUID,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    *,
    start_agent_host: bool = True,
) -> None:
    """Start the selected branch's next queued work through chat admission.

    The next root turn starts first. Otherwise, idle agents' work starts in an
    agent host when no running child keeps a run store scanning. Chat turns pass
    `start_agent_host=False`: their own run stores start that work. Started work
    uses the pass-through headers of the request that led to it.
    """
    try:
        cache = get_cache_backend(operation_timeout_s=ADMISSION_CACHE_TIMEOUT_S)
        if is_chat_session_processing(chat_session_id, cache):
            return
        inbox = read_repaired_chat_inbox(chat_session_id, cache)
        queued_turn = inbox.next_turn
        if queued_turn is None and not (
            start_agent_host and inbox.child_work and not inbox.running_response_ids
        ):
            return

        def start_pending_work() -> None:
            # Queued work starts a new root trace while retaining tenant context.
            trace_token = Scope.set_current_trace(None)
            span_token = Scope.set_current_span(None)
            try:
                with get_session_with_current_tenant() as db_session:
                    user = fetch_user_by_id(db_session, user_id)
                if user is None or not user.is_active:
                    logger.info("Queued chat work has no active owner")
                    return
                dispatch = partial(
                    dispatch_pending_chat_messages,
                    chat_session_id,
                    user_id,
                    litellm_additional_headers,
                    custom_tool_additional_headers,
                    start_agent_host=False,
                )
                if queued_turn is None:
                    if not has_global_permission(user, Permission.WRITE_CHAT):
                        logger.info("Agent work waits for its owner's write access")
                        return
                    try:
                        host_setup = prepare_chat_turn(
                            new_msg_req=SendMessageRequest(
                                message="",
                                chat_session_id=chat_session_id,
                                parent_message_id=inbox.selected_response_id,
                            ),
                            user=user,
                            llm_overrides=None,
                            litellm_additional_headers=litellm_additional_headers,
                            custom_tool_additional_headers=custom_tool_additional_headers,
                            agent_host=True,
                        )
                    except OnyxError as error:
                        if error.error_code is not OnyxErrorCode.RATE_LIMITED:
                            raise
                        # Like a queued turn's error response, failed runs keep
                        # the work from retrying on every poll; their results
                        # reach the agents that sent it.
                        with get_session_with_current_tenant() as db_session:
                            for work in inbox.child_work:
                                fail_inbox_start__no_commit(
                                    db_session,
                                    inbox.branch,
                                    work.agent_id,
                                    work.message.id if work.message else None,
                                    error.detail,
                                )
                            db_session.commit()
                        return
                    host_agent_work(host_setup, user, dispatch)
                    return
                setup = prepare_chat_turn(
                    new_msg_req=SendMessageRequest(
                        message=queued_turn.message.message
                        if queued_turn.message is not None
                        else "",
                        chat_session_id=chat_session_id,
                        parent_message_id=queued_turn.parent_response_id,
                        deep_research=queued_turn.message is not None
                        and queued_turn.message.deep_research,
                        llm_override=queued_turn.message.llm_override
                        if queued_turn.message is not None
                        else None,
                        # Only clients that show follow-ups queue turns or
                        # start the agents whose results wake the chat.
                        accepts_follow_ups=True,
                    ),
                    user=user,
                    llm_overrides=None,
                    litellm_additional_headers=litellm_additional_headers,
                    custom_tool_additional_headers=custom_tool_additional_headers,
                    queued_turn=queued_turn,
                )
                stream = start_chat_turn(
                    setup, user, dispatch_pending_messages=dispatch
                )
                # Delivery and persistence continue without a browser reader.
                stream.close()
            except OnyxError as error:
                if error.error_code is OnyxErrorCode.CONFLICT:
                    logger.debug("Queued chat work was claimed elsewhere")
                else:
                    log_onyx_error(error)
            except Exception:
                logger.exception("Could not start queued chat work")
            finally:
                Scope.reset_current_span(span_token)
                Scope.reset_current_trace(trace_token)

        chat_turn_work.started()
        try:
            worker = start_thread_future(
                start_pending_work, name="chat-queued-message", daemon=False
            )
        except BaseException:
            chat_turn_work.finished()
            raise
        worker.add_done_callback(lambda _future: chat_turn_work.finished())
    except Exception:
        logger.exception("Could not dispatch queued chat input")


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
    delivers_follow_ups: bool = True,
) -> AnswerStream:
    """Prepare one request, then read its independently owned agent stream.

    `delivers_follow_ups` is false for one-shot callers. Their turns start no
    queued work and offer no agent tools.
    """
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
            dispatch_pending_messages=partial(
                dispatch_pending_chat_messages,
                setup.chat_session_id,
                user.id,
                litellm_additional_headers,
                custom_tool_additional_headers,
                start_agent_host=False,
            )
            if delivers_follow_ups and setup.incognito_record_mode is None
            else None,
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
    delivers_follow_ups: bool = True,
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
        delivers_follow_ups=delivers_follow_ups,
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
def gather_stream_full(
    packets: AnswerStream,
    response_future: Future[ChatResponseOutcome],
) -> ChatFullResponse:
    """Read delivery metadata and project accepted execution content."""
    error: StreamingError | None = None
    message_id: int | None = None
    chat_session_id: UUID | None = None
    incognito = False

    for packet in packets:
        if isinstance(packet, StreamingError):
            error = packet
        elif isinstance(packet, MessageResponseIDInfo):
            message_id = packet.reserved_assistant_message_id
        elif isinstance(packet, CreateChatSessionID):
            chat_session_id = packet.chat_session_id
            incognito = packet.incognito

    if message_id is None:
        if error is not None:
            # The turn failed before it reserved a message; surface the
            # original error as an HTTP status instead of a 500.
            raise OnyxError(
                OnyxErrorCode.for_code(error.error_code),
                error.error,
                extra=error.details,
            )
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
        error_msg=outcome.error or (error.error if error else None),
    )


def run_chat_turn(
    new_msg_req: SendMessageRequest,
    user: User,
    litellm_additional_headers: dict[str, str] | None = None,
    custom_tool_additional_headers: dict[str, str] | None = None,
    mcp_headers: dict[str, str] | None = None,
    additional_context: str | None = None,
    slack_context: SlackContext | None = None,
) -> ChatFullResponse:
    """Run one chat turn to completion for in-process, non-streaming callers.

    These callers read one response, so the turn offers no agent tools.
    """
    response_future = Future[ChatResponseOutcome]()
    packets = handle_stream_message_objects(
        new_msg_req=new_msg_req,
        user=user,
        litellm_additional_headers=litellm_additional_headers,
        custom_tool_additional_headers=custom_tool_additional_headers,
        mcp_headers=mcp_headers,
        additional_context=additional_context,
        slack_context=slack_context,
        response_future=response_future,
        delivers_follow_ups=False,
    )
    return gather_stream_full(packets, response_future)
