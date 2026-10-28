"""Run chat turns independently of browser connections."""

import threading
import time
from concurrent.futures import Future
from contextlib import ExitStack
from functools import partial

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.concurrency import WorkTracker
from onyx.agents.models import AgentInfo, RunState
from onyx.agents.runtime import Run
from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheLockLostError
from onyx.chat.agent import ChatAgent
from onyx.chat.chat_processing_checker import (
    PROCESSING_REFRESH_INTERVAL_S,
)
from onyx.chat.emitter import Emitter
from onyx.chat.errors import chat_error
from onyx.chat.history_store import get_chat_history_store
from onyx.chat.incognito import incognito_llm_request_policy
from onyx.chat.incognito_context import incognito_session_ended
from onyx.chat.models import ChatResponseOutcome, ChatTurnSetup, CreateChatSessionID
from onyx.chat.persistence import ChatResponsePersistence
from onyx.chat.presentation import ResponsePresenter
from onyx.chat.prompt_utils import build_language_section
from onyx.chat.restoration import restore_chat_agent
from onyx.chat.run_store import ChatRunStore
from onyx.chat.stop_signal_checker import clear_stop, is_stop_requested
from onyx.chat.stream_buffer import ChatDelivery, ChatStream, StreamBufferWriter
from onyx.chat.subagents import ChatAgentDirectory
from onyx.configs.chat_configs import (
    CHAT_EXECUTION_TIMEOUT_S,
    SKIP_DEEP_RESEARCH_CLARIFICATION,
)
from onyx.configs.constants import DEFAULT_PERSONA_ID, DocumentSource
from onyx.db.chat_subagents import load_chat_branch
from onyx.db.enums import record_mode_persists_content
from onyx.db.models import User
from onyx.deep_research.agent import MIN_RESEARCH_CONTEXT_TOKENS, DeepResearchAgent
from onyx.deep_research.tool_definitions import RESEARCH_AGENT_TOOL_NAME
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.cancellation import CancellationSignal, cancellation_scope
from onyx.llm.factory import get_llm_token_counter, get_search_selection_llm
from onyx.server.query_and_chat.models import (
    MessageResponseIDInfo,
    ModelResponseSlot,
    MultiModelMessageResponseIDInfo,
)
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    OverallStop,
    Packet,
    StreamingError,
)
from onyx.server.settings.store import load_settings
from onyx.tools.tool_constructor import (
    CustomToolConfig,
    FileReaderToolConfig,
    SearchToolConfig,
    construct_tools,
)
from onyx.tracing.framework.create import ChatTraceMetadata, trace
from onyx.utils.fleet_query_telemetry import CURRENT_QUERY_OBSERVATION, QueryObservation
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_future
from shared_configs.contextvars import (
    CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR,
    CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR,
    get_current_tenant_id,
)

logger = setup_logger()
_CANCEL_POLL_INTERVAL_S = 0.25
# Count work across tenants without retaining their turns or request data.
chat_turn_work = WorkTracker()


def start_chat_turn(
    setup: ChatTurnSetup,
    user: User,
    response_future: Future[ChatResponseOutcome] | None = None,
    *,
    query_observation: QueryObservation | None = None,
) -> ChatStream:
    """Publish response identity and launch work that outlives its stream reader."""
    mode = setup.incognito_record_mode
    content_free = not record_mode_persists_content(mode)
    mode_token = CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.set(
        mode.value if mode else None
    )
    session_token = CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.set(
        str(setup.chat_session_id) if content_free else None
    )
    turn: ChatTurnExecution | None = None
    chat_turn_work.started()
    try:
        stream_buffer = StreamBufferWriter(
            cache=setup.cache,
            chat_session_id=setup.chat_session_id,
            stream_id=setup.stream_id,
            delete_on_done=content_free,
            session_ended=(
                partial(incognito_session_ended, setup.chat_session_id)
                if content_free
                else None
            ),
        )
        turn = ChatTurnExecution(
            setup,
            user,
            response_future,
            stream_buffer,
            query_observation=query_observation,
        )
        startup_error: Exception | None = None
        try:
            turn._auto_filters = load_settings().auto_detect_search_filters is not False
            clear_stop(setup.chat_session_id, setup.cache, stream_id=setup.stream_id)
            # Stop must identify this response before the client receives its IDs.
            setup.admission.publish(setup.stream_id)
        except Exception as error:
            startup_error = error
        if setup.new_msg_req.chat_session_id is None:
            turn.delivery.publish(
                CreateChatSessionID(
                    chat_session_id=setup.chat_session_id,
                    incognito=mode is not None,
                )
            )
        turn.delivery.publish(
            MultiModelMessageResponseIDInfo(
                user_message_id=setup.user_message_id,
                responses=[
                    ModelResponseSlot(
                        message_id=response.message_id, model_name=response.display_name
                    )
                    for response in setup.responses
                ],
            )
            if len(setup.responses) > 1
            else MessageResponseIDInfo(
                user_message_id=setup.user_message_id,
                reserved_assistant_message_id=setup.responses[0].message_id,
            )
        )
        if query_observation is not None:
            query_observation.writer_owned = True
        control = start_thread_future(
            lambda: turn.run(startup_error=startup_error),
            name="chat-control",
            daemon=False,
        )
        control.add_done_callback(lambda _future: chat_turn_work.finished())
        return turn.delivery.reader
    except BaseException as error:
        if query_observation is not None:
            query_observation.writer_owned = False
        if turn is None:
            try:
                setup.admission.release()
            finally:
                chat_turn_work.finished()
        else:
            turn.reject(error)
        raise
    finally:
        CURRENT_CONTENT_FREE_SESSION_ID_CONTEXTVAR.reset(session_token)
        CURRENT_INCOGNITO_RECORD_MODE_CONTEXTVAR.reset(mode_token)


class ChatTurnExecution:
    """Own response execution, Stop control, and delivery for one user message."""

    def __init__(
        self,
        setup: ChatTurnSetup,
        user: User,
        response_future: Future[ChatResponseOutcome] | None = None,
        stream_buffer: StreamBufferWriter | None = None,
        *,
        query_observation: QueryObservation | None = None,
    ) -> None:
        self.setup = setup
        self.user = user
        self.delivery = ChatDelivery(stream_buffer, query_observation=query_observation)
        self._query_observation = query_observation
        self._stores: list[ChatRunStore] = []
        self.cancellation = CancellationSignal()
        self._response_future = response_future
        self._response_workers: dict[Future[Run | None], ChatResponsePersistence] = {}
        self._lock = threading.Lock()
        self._completion_changed = threading.Event()
        self.delivery.finished.add_done_callback(
            lambda _future: self._completion_changed.set()
        )
        self._auto_filters = False
        self._stopped_by_user = False
        self._last_refresh = self._last_stop_check = time.monotonic()

    def reject(self, error: BaseException) -> None:
        if self._query_observation is not None:
            self._query_observation.failed(error)
        self.cancellation.cancel()
        if self._response_future is not None:
            self._response_future.set_exception(error)

        def clear_status() -> None:
            try:
                self._clear_processing_status()
            finally:
                chat_turn_work.finished()

        def delivery_finished(_future: Future[None]) -> None:
            try:
                start_thread_future(
                    clear_status, name="chat-status-cleanup", daemon=False
                )
            except Exception:
                logger.exception(
                    "Rejected chat processing status cleanup could not start"
                )
                clear_status()

        # No control thread exists to observe cleanup for a rejected turn.
        try:
            self.delivery.finish()
        finally:
            self.delivery.finished.add_done_callback(delivery_finished)

    def _publish(self, packet: Packet) -> None:
        if not self.cancellation.cancelled:
            self.delivery.publish(packet)

    def run(self, *, startup_error: BaseException | None = None) -> None:
        try:
            self.delivery.events.start()
        except Exception as error:
            startup_error = error
        if startup_error is not None:
            self.cancellation.cancel()
            self.delivery.publish(
                chat_error(startup_error)
                if isinstance(startup_error, OnyxError)
                else StreamingError(
                    error="The response could not be started. Please try again.",
                    error_code="CHAT_STARTUP_ERROR",
                    is_retryable=True,
                )
            )
        for index, response in enumerate(self.setup.responses):
            persistence = ChatResponsePersistence(
                coordinator=AgentCoordinator(),
                history_store=get_chat_history_store(
                    message_id=response.message_id,
                    chat_session_id=self.setup.chat_session_id,
                    persist_content=record_mode_persists_content(
                        self.setup.incognito_record_mode
                    ),
                ),
                model_index=index,
                llm=response.llm,
                delivery=self.delivery,
                outcome=self._response_future
                if index == 0 and self._response_future is not None
                else Future[ChatResponseOutcome](),
            )
            emitter = Emitter(
                self._publish, persistence.model_index, self._query_observation
            )
            try:
                worker = start_thread_future(
                    lambda persistence=persistence, emitter=emitter: self._run_response(
                        persistence,
                        emitter,
                        startup_error=startup_error,
                    ),
                    name="chat-response",
                )
            except Exception as error:
                worker = Future[Run | None]()
                worker.set_result(
                    self._run_response(persistence, emitter, startup_error=error)
                )
            self._response_workers[worker] = persistence
            worker.add_done_callback(lambda _future: self._completion_changed.set())

        deadline = time.monotonic() + CHAT_EXECUTION_TIMEOUT_S
        timed_out = False
        while True:
            # Clear before checking state so a concurrent completion cannot be lost.
            self._completion_changed.clear()
            try:
                self._poll_control()
            except Exception:
                self.cancellation.cancel()
                logger.exception("Chat turn control failed; draining active work")
            try:
                self._poll_responses()
            except Exception:
                self.cancellation.cancel()
                logger.exception("Chat response polling failed; draining active work")
            if not timed_out and time.monotonic() >= deadline:
                timed_out = True
                logger.error("Chat turn exceeded its execution deadline")
                self.cancellation.cancel()
            with self._lock:
                stores = tuple(self._stores)
            if not self._response_workers and not any(
                store.has_owned_work for store in stores
            ):
                if not self.delivery.is_closing:
                    if self._stopped_by_user:
                        self.delivery.publish(
                            Packet(
                                placement=Placement(turn_index=0),
                                obj=OverallStop(stop_reason="user_cancelled"),
                            )
                        )
                    self.delivery.finish()
                if self.delivery.finished.done() and self._clear_processing_status():
                    return
            self._completion_changed.wait(_CANCEL_POLL_INTERVAL_S)

    def _poll_responses(self) -> None:
        for worker, persistence in tuple(self._response_workers.items()):
            run: Run | None = None
            worker_done = worker.done()
            try:
                if worker_done:
                    failure = worker.exception()
                    if failure is not None:
                        if isinstance(failure, Exception):
                            raise failure
                        raise RuntimeError("Chat response worker failed") from failure
                    run = worker.result()
                if not persistence.outcome.done():
                    persistence.expire_save()
                if not worker_done:
                    continue
                if run is not None:
                    if not run.status.is_terminal:
                        continue
                    try:
                        if not run.wait_for_idle(timeout=0):
                            continue
                    except Exception:
                        # An exceptional idle future reports failed cleanup after workers drain.
                        logger.exception("Chat response cleanup failed")
                        self.delivery.report_gap()
                    if run.delivery_failed:
                        self.delivery.report_gap()
                if not persistence.outcome.done():
                    raise RuntimeError(
                        "Chat response worker finished without an outcome"
                    )
            except Exception as failure:
                logger.exception("Chat response completion failed")
                self.cancellation.cancel()
                persistence.report_worker_failure(failure)
                if run is not None:
                    run.cancel()
                    continue
                if not worker_done:
                    continue
            del self._response_workers[worker]

    def _clear_processing_status(self) -> bool:
        try:
            self.setup.admission.release()
            return True
        except Exception:
            logger.exception("Failed to clear chat processing status; will retry")
            return False

    def _run_response(
        self,
        persistence: ChatResponsePersistence,
        emitter: Emitter,
        *,
        startup_error: BaseException | None = None,
    ) -> Run | None:
        index = persistence.model_index
        cancellation = CancellationSignal()
        links = ExitStack()
        links.enter_context(self.cancellation.on_cancel(cancellation.cancel))
        observation_token = CURRENT_QUERY_OBSERVATION.set(self._query_observation)
        try:
            if startup_error is not None:
                raise startup_error
            cancellation.check()
            chat_agent = create_chat_agent(
                self.setup, self.user, index, cancellation, self._auto_filters
            )
            persistence.tool_ids = {
                tool.name: tool.id for tool in chat_agent.application_tools
            }
            if isinstance(chat_agent, DeepResearchAgent):
                if self.setup.research_tool_id is None:
                    raise ValueError("Deep research tool configuration is missing")
                persistence.tool_ids[RESEARCH_AGENT_TOOL_NAME] = (
                    self.setup.research_tool_id
                )
            else:
                persistence.initial_citations = dict(chat_agent.initial_citations)
            branch = load_chat_branch(persistence.message_id)
            if branch.chat_session_id != self.setup.chat_session_id:
                raise ValueError("Response belongs to another chat session")
            persist_content = record_mode_persists_content(
                self.setup.incognito_record_mode
            )
            store = (
                ChatRunStore(
                    tenant_id=get_current_tenant_id(),
                    chat_session_id=self.setup.chat_session_id,
                    response_id=persistence.message_id,
                    visible_response_ids=branch.message_ids,
                    cache=get_cache_backend(),
                    root_response=persistence,
                )
                if persist_content
                else None
            )
            if store is not None:
                with self._lock:
                    self._stores.append(store)
            history_store = get_chat_history_store(
                message_id=persistence.message_id,
                chat_session_id=self.setup.chat_session_id,
                visible_message_ids=branch.message_ids,
                persist_content=persist_content,
                branch=branch,
            )
            saved_agents = history_store.list_agents()
            directory = ChatAgentDirectory(
                history_store=history_store,
                llm=persistence.llm,
                tools=chat_agent.application_tools,
                user_identity=self.setup.user_identity,
                store=store,
            )
            coordinator = (
                store.bind(
                    persistence.coordinator,
                    build_agent=partial(
                        restore_chat_agent,
                        llm=persistence.llm,
                        tools=chat_agent.application_tools,
                        user_identity=self.setup.user_identity,
                    ),
                    directory=directory,
                )
                if store is not None
                else persistence.coordinator.view(
                    directory=directory, store=persistence
                )
            )
            for info in saved_agents:
                coordinator.register(info)
            coordinator.register(
                AgentInfo(
                    id=chat_agent.id,
                    path="/root",
                    parent_id=None,
                    description="",
                    restoration_config=None,
                    latest_run_id=self.setup.previous_run_id,
                )
            )
            cancellation.check()
            research = (
                len(self.setup.responses) == 1 and self.setup.new_msg_req.deep_research
            )
            with trace(
                "run_deep_research" if research else "chat",
                group_id=str(self.setup.chat_session_id),
                metadata=ChatTraceMetadata(
                    chat_session_id=str(self.setup.chat_session_id),
                    user_id=self.setup.user_identity.user_id,
                ).model_dump(),
            ):
                run = chat_agent.start(
                    background=False,
                    messages=self.setup.input_messages,
                    max_steps=chat_agent.max_steps,
                    cancellation=cancellation,
                    coordinator=coordinator,
                    event_dispatcher=self.delivery.events,
                    on_event=ResponsePresenter(
                        emitter,
                        tool_ids={
                            tool.name: tool.id for tool in chat_agent.application_tools
                        },
                    ).consume,
                )

            def response_saved(completion: Future[RunState]) -> None:
                try:
                    if (
                        completion.exception() is not None
                        and not persistence.outcome.done()
                    ):
                        persistence.report_save_failure(run)
                finally:
                    links.close()
                    self._completion_changed.set()

            coordinator.completion(run.id).add_done_callback(response_saved)
            run.add_idle_callback(self._completion_changed.set)
            return run
        except BaseException as failure:
            try:
                persistence.save_failure(failure)
            except Exception:
                logger.exception(
                    "Response startup finalization failed for model %d", index
                )
            finally:
                links.close()
            return None
        finally:
            CURRENT_QUERY_OBSERVATION.reset(observation_token)

    def _poll_control(self) -> None:
        with self._lock:
            stores = tuple(self._stores)
        for store in stores:
            try:
                store.poll_control()
            except Exception:
                self.cancellation.cancel()
                logger.exception("Chat ownership control failed; will retry")

        now = time.monotonic()
        if (
            not self.cancellation.cancelled
            and now - self._last_stop_check >= _CANCEL_POLL_INTERVAL_S
        ):
            self._last_stop_check = now
            try:
                if is_stop_requested(
                    self.setup.chat_session_id,
                    self.setup.admission.cache,
                    stream_id=self.setup.stream_id,
                ):
                    self._stopped_by_user = True
                    self.cancellation.cancel()
            except Exception:
                logger.exception("Failed to read chat Stop request; will retry")
        if now - self._last_refresh >= PROCESSING_REFRESH_INTERVAL_S:
            self._last_refresh = now
            try:
                self.setup.admission.refresh()
            except CacheLockLostError:
                self.cancellation.cancel()
                logger.exception(
                    "Chat session admission was lost; draining active work"
                )
            except Exception:
                logger.exception("Failed to refresh chat processing status; will retry")


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
        filters = setup.new_msg_req.internal_search_filters
        source_types = filters.source_type if filters else None
        # Tools open DB sessions on demand, so model I/O cannot retain a connection.
        tools_by_type = construct_tools(
            configuration=setup.tool_configuration,
            user=user,
            llm=llm,
            selection_llm_factory=partial(
                get_search_selection_llm,
                fallback=llm,
                additional_headers=setup.litellm_additional_headers,
                policy_fn=partial(
                    incognito_llm_request_policy, setup.incognito_record_mode
                ),
            ),
            search_tool_config=SearchToolConfig(
                user_selected_filters=setup.new_msg_req.internal_search_filters,
                project_id_filter=setup.search_params.project_id_filter,
                persona_id_filter=setup.search_params.persona_id_filter,
                slack_context=setup.slack_context,
                enable_slack_search=(
                    source_types is not None and DocumentSource.SLACK in source_types
                )
                or (setup.persona_id == DEFAULT_PERSONA_ID and source_types is None),
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
            raise OnyxError(
                OnyxErrorCode.BAD_REQUEST,
                f"Forced tool {setup.forced_tool_id} not found in tools",
            )

        agent_id = str(setup.chat_session_id)

        if len(setup.responses) == 1 and setup.new_msg_req.deep_research:
            if setup.chat_session_project_id:
                raise OnyxError(
                    OnyxErrorCode.BAD_REQUEST,
                    "Deep research is not supported for projects",
                )
            if setup.research_tool_id is None:
                raise ValueError("Deep research tool configuration is missing")
            if llm.config.max_input_tokens < MIN_RESEARCH_CONTEXT_TOKENS:
                raise OnyxError(
                    OnyxErrorCode.BAD_REQUEST,
                    "Deep research requires a model with at least 50,000 input tokens",
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
