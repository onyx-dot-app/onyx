"""Unit tests for multi-model streaming validation and DB helpers.

These are pure unit tests — no real database or LLM calls required.
The validation logic in handle_multi_model_stream fires before any external
calls, so we can trigger it with lightweight mocks.
"""

import asyncio
import threading
import time
from collections.abc import Callable, Generator
from concurrent.futures import Future
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import Any, cast
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from litellm.exceptions import ContextWindowExceededError

from onyx.agents.agent_coordination import AgentCoordinator
from onyx.agents.events import AgentEvent
from onyx.agents.execution_records import RunStatus
from onyx.agents.runtime import Agent, Run
from onyx.agents.tools import AgentTool, InputMode, PendingToolInput
from onyx.chat.agent import ChatAgent
from onyx.chat.emitter import Emitter
from onyx.chat.errors import EmptyLLMResponseError
from onyx.chat.execution import (
    ActiveChatTurns,
    ChatTurnExecution,
    start_chat_turn,
)
from onyx.chat.models import (
    PERSISTENCE_ERROR_MESSAGES,
    AnswerStreamPart,
    ChatResponseOutcome,
    ChatResponseSnapshot,
    ChatTurnSetup,
    PersistenceStatus,
    ReservedChatResponse,
    StreamingError,
)
from onyx.chat.process_message import (
    _stream_chat_turn,
    gather_stream_full,
)
from onyx.chat.run_store import ChatRunStore
from onyx.chat.stream_buffer import ChatStream, StreamBufferWriter
from onyx.configs.constants import MessageType
from onyx.db.chat import set_preferred_response
from onyx.db.models import ChatMessage, ChatSession, User
from onyx.file_store.models import ExtractedContextFiles
from onyx.llm.cancellation import (
    CancellationSignal,
    cancellation_scope,
    current_cancellation,
)
from onyx.llm.exceptions import ClassifiedLLMError
from onyx.llm.interfaces import LLM, LLMConfig, LLMUserIdentity
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    TextContent,
    ToolCall,
    ToolChoiceOptions,
)
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import MessageResponseIDInfo, SendMessageRequest
from onyx.server.query_and_chat.streaming_models import (
    ChatHeartbeat,
    ItemUpdate,
    OverallStop,
    Packet,
    ReasoningItem,
)
from onyx.utils.threadpool_concurrency import (
    ContextThreadPoolExecutor,
)
from onyx.utils.variable_functionality import global_version
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.unit.onyx.agents.fakes import FakeModelClient, FakeRunOwnership, FakeRunStore

MODEL_REFUSAL_ERROR_CODE = "MODEL_REFUSAL"
CONTENT_FILTER_FINISH_REASON = "content_filter"


@pytest.fixture(autouse=True)
def _restore_ee_version() -> Generator[None, None, None]:
    """Reset EE global state after each test.

    Importing onyx.chat.process_message triggers set_is_ee_based_on_env_variable()
    (via the celery client import chain).  Without this fixture, the EE flag stays
    True for the rest of the session and breaks unrelated tests that mock Confluence
    or other connectors and assume EE is disabled.
    """
    original = global_version._is_ee
    yield
    global_version._is_ee = original


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(**kwargs: Any) -> SendMessageRequest:
    defaults: dict[str, Any] = {
        "message": "hello",
        "chat_session_id": uuid4(),
    }
    defaults.update(kwargs)
    return SendMessageRequest(**defaults)


def _make_override(provider: str = "openai", version: str = "gpt-4") -> LLMOverride:
    return LLMOverride(model_provider=provider, model_version=version)


def _first_from_stream(req: SendMessageRequest, overrides: list[LLMOverride]) -> Any:
    """Return the first item yielded by handle_multi_model_stream."""
    from onyx.chat.process_message import handle_multi_model_stream

    user = MagicMock()
    user.is_anonymous = False
    user.email = "test@example.com"

    gen = handle_multi_model_stream(req, user, overrides)
    return next(gen)


# ---------------------------------------------------------------------------
# handle_multi_model_stream — validation
# ---------------------------------------------------------------------------


class TestRunMultiModelStreamValidation:
    def test_single_override_yields_error(self) -> None:
        """Exactly 1 override is not multi-model — yields StreamingError."""
        req = _make_request()
        result = _first_from_stream(req, [_make_override()])
        assert isinstance(result, StreamingError)
        assert "2-3" in result.error

    def test_four_overrides_yields_error(self) -> None:
        """4 overrides exceeds maximum — yields StreamingError."""
        req = _make_request()
        result = _first_from_stream(
            req,
            [
                _make_override("openai", "gpt-4"),
                _make_override("anthropic", "claude-3"),
                _make_override("google", "gemini-pro"),
                _make_override("cohere", "command-r"),
            ],
        )
        assert isinstance(result, StreamingError)
        assert "2-3" in result.error

    def test_zero_overrides_yields_error(self) -> None:
        """Empty override list yields StreamingError."""
        req = _make_request()
        result = _first_from_stream(req, [])
        assert isinstance(result, StreamingError)
        assert "2-3" in result.error

    def test_deep_research_yields_error(self) -> None:
        """deep_research=True is incompatible with multi-model — yields StreamingError."""
        req = _make_request(deep_research=True)
        result = _first_from_stream(
            req, [_make_override(), _make_override("anthropic", "claude-3")]
        )
        assert isinstance(result, StreamingError)
        assert "not supported" in result.error

    def test_exactly_two_overrides_is_minimum(self) -> None:
        """Boundary: 1 override yields error, 2 overrides passes validation."""
        req = _make_request()
        # 1 override must yield a StreamingError
        result = _first_from_stream(req, [_make_override()])
        assert isinstance(result, StreamingError), (
            "1 override should yield StreamingError"
        )
        # 2 overrides must NOT yield a validation StreamingError (may raise later due to
        # missing session, that's OK — validation itself passed)
        try:
            result2 = _first_from_stream(
                req, [_make_override(), _make_override("anthropic", "claude-3")]
            )
            if isinstance(result2, StreamingError) and "2-3" in result2.error:
                pytest.fail(
                    f"2 overrides should pass validation, got StreamingError: {result2.error}"
                )
        except Exception:
            pass  # Any non-validation error means validation passed


# ---------------------------------------------------------------------------
# set_preferred_response — validation (mocked db)
# ---------------------------------------------------------------------------


class TestSetPreferredResponseValidation:
    def test_user_message_not_found(self) -> None:
        db = MagicMock()
        db.get.return_value = None

        with pytest.raises(ValueError, match="not found"):
            set_preferred_response(
                db, user_message_id=999, preferred_assistant_message_id=1
            )

    def test_wrong_message_type(self) -> None:
        """Cannot set preferred response on a non-USER message."""
        db = MagicMock()
        user_msg = MagicMock()
        user_msg.message_type = MessageType.ASSISTANT  # wrong type

        db.get.return_value = user_msg

        with pytest.raises(ValueError, match="not a user message"):
            set_preferred_response(
                db, user_message_id=1, preferred_assistant_message_id=2
            )

    def test_assistant_message_not_found(self) -> None:
        db = MagicMock()
        user_msg = ChatMessage(
            message_type=MessageType.USER,
            summary_covered_count=None,
            last_summarized_message_id=None,
            chat_session=ChatSession(spawned_by_message_id=None),
        )

        # First call returns user_msg, second call (for assistant) returns None
        db.get.side_effect = [user_msg, None]

        with pytest.raises(ValueError, match="not found"):
            set_preferred_response(
                db, user_message_id=1, preferred_assistant_message_id=2
            )

    def test_assistant_not_child_of_user(self) -> None:
        db = MagicMock()
        user_msg = ChatMessage(
            message_type=MessageType.USER,
            summary_covered_count=None,
            last_summarized_message_id=None,
            chat_session=ChatSession(spawned_by_message_id=None),
        )

        assistant_msg = ChatMessage(parent_message_id=999)

        db.get.side_effect = [user_msg, assistant_msg]

        with pytest.raises(ValueError, match="not a child"):
            set_preferred_response(
                db, user_message_id=1, preferred_assistant_message_id=2
            )

    def test_valid_call_sets_preferred_response_id(self) -> None:
        db = MagicMock()
        user_msg = ChatMessage(
            message_type=MessageType.USER,
            summary_covered_count=None,
            last_summarized_message_id=None,
            chat_session=ChatSession(spawned_by_message_id=None),
        )

        assistant_msg = ChatMessage(
            parent_message_id=1,
            message_type=MessageType.ASSISTANT,
            summary_covered_count=None,
            last_summarized_message_id=None,
        )

        db.get.side_effect = [user_msg, assistant_msg]

        set_preferred_response(db, user_message_id=1, preferred_assistant_message_id=2)

        assert user_msg.preferred_response_id == 2
        assert user_msg.latest_child_message_id == 2


# ---------------------------------------------------------------------------
# LLMOverride — display_name field
# ---------------------------------------------------------------------------


class TestLLMOverrideDisplayName:
    def test_display_name_defaults_none(self) -> None:
        override = LLMOverride(model_provider="openai", model_version="gpt-4")
        assert override.display_name is None

    def test_display_name_set(self) -> None:
        override = LLMOverride(
            model_provider="openai",
            model_version="gpt-4",
            display_name="GPT-4 Turbo",
        )
        assert override.display_name == "GPT-4 Turbo"

    def test_display_name_serializes(self) -> None:
        override = LLMOverride(
            model_provider="anthropic",
            model_version="claude-opus-4-6",
            display_name="Claude Opus",
        )
        d = override.model_dump()
        assert d["display_name"] == "Claude Opus"


# ---------------------------------------------------------------------------
# Chat turn delivery
# ---------------------------------------------------------------------------


def _make_setup(n_models: int = 1) -> MagicMock:
    """Chat setup with concrete values required by response preparation."""
    setup = MagicMock()
    setup.responses = []
    for index in range(n_models):
        llm = MagicMock(spec=LLM)
        llm.config = LLMConfig(
            model_provider="openai",
            model_name="test-model",
            max_input_tokens=32_000,
            temperature=0,
        )
        llm.redact_error.side_effect = lambda text: text
        setup.responses.append(
            ReservedChatResponse(
                llm=llm, message_id=1000 + index, display_name=f"model-{index}"
            )
        )
    setup.incognito_record_mode = None
    setup.cache.exists.return_value = False
    # Fields consumed by SearchToolConfig / CustomToolConfig / FileReaderToolConfig
    # constructors during model preparation — must be typed correctly for Pydantic.
    setup.new_msg_req.deep_research = False
    setup.new_msg_req.internal_search_filters = None
    setup.new_msg_req.allowed_tool_ids = None
    setup.new_msg_req.include_citations = True
    setup.search_params.project_id_filter = None
    setup.search_params.persona_id_filter = None
    setup.slack_context = None
    setup.available_files.user_file_ids = []
    setup.available_files.chat_file_ids = []
    setup.user_identity = LLMUserIdentity(
        user_id="test-user", session_id="test-session"
    )
    setup.forced_tool_id = None
    setup.messages = []
    setup.input_messages = []
    setup.chat_session_id = uuid4()
    setup.chat_session_project_id = None
    setup.user_message_id = None
    setup.custom_tool_additional_headers = None
    setup.mcp_headers = None
    return setup


def _wait_for_stop() -> None:
    signal = current_cancellation()
    assert signal is not None
    stopped = threading.Event()
    with signal.on_cancel(stopped.set):
        assert stopped.wait(timeout=5)


def _chat_agent(agent: Agent, max_steps: int = 1) -> ChatAgent:
    chat_agent = ChatAgent(
        messages=[],
        tools=[],
        custom_agent_prompt=None,
        base_system_prompt="",
        context_files=ExtractedContextFiles(
            file_texts=[],
            image_files=[],
            use_as_search_filter=False,
            total_token_count=0,
            file_metadata=[],
            uncapped_token_count=None,
        ),
        persona=None,
        user_memory_context=None,
        llm=agent.llm,
        token_counter=len,
    )
    chat_agent.agent = agent
    chat_agent.max_steps = max_steps
    return chat_agent


def _start_chat_turn(
    setup: ChatTurnSetup,
    user: User,
    response_future: Future[ChatResponseOutcome] | None = None,
    stream_buffer: StreamBufferWriter | None = None,
) -> ChatStream:
    return start_chat_turn(
        setup,
        user,
        response_future,
        stream_buffer,
    )


def _collect_chat_turn(setup: MagicMock) -> list:
    """Collect packets until chat delivery finishes."""

    return list(_start_chat_turn(setup, MagicMock()))


class TestRunModels:
    """Tests for merged chat delivery and response ownership.

    All external dependencies (LLM, DB, tools) are patched out.  Worker threads
    still run but return immediately since agent is mocked.
    """

    def test_n1_overall_stop_from_llm_loop_passes_through(self) -> None:
        """OverallStop emitted by agent is passed through the drain loop unchanged."""

        def emit_stop(**kwargs: Any) -> None:
            kwargs["emitter"].emit(
                Packet(
                    obj=OverallStop(stop_reason="complete"),
                )
            )

        with (
            patch_execution(side_effect=emit_stop),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db"),
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _collect_chat_turn(_make_setup(n_models=1))

        stops = [
            p
            for p in packets
            if isinstance(p, Packet) and isinstance(p.obj, OverallStop)
        ]
        assert len(stops) == 1
        stop_obj = stops[0].obj
        assert isinstance(stop_obj, OverallStop)
        assert stop_obj.stop_reason == "complete"

    def test_idle_gap_emits_chat_heartbeat(self) -> None:
        """Idle gaps in the drain loop emit ChatHeartbeat packets."""

        def sleep_then_return(**_kwargs: Any) -> None:
            time.sleep(0.2)

        with (
            patch(
                "onyx.chat.stream_buffer.CHAT_HEARTBEAT_INTERVAL_S",
                0.05,
            ),
            patch_execution(
                side_effect=sleep_then_return,
            ),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db"),
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _collect_chat_turn(_make_setup(n_models=1))

        heartbeats = [
            p
            for p in packets
            if isinstance(p, Packet) and isinstance(p.obj, ChatHeartbeat)
        ]
        assert heartbeats

    def test_n1_emitted_packet_has_model_index_zero(self) -> None:
        """Single-model path: model_index is 0 (Emitter defaults model_idx=0)."""

        def emit_one(**kwargs: Any) -> None:
            kwargs["emitter"].emit(
                Packet(
                    obj=ItemUpdate(item=ReasoningItem()),
                )
            )

        with (
            patch_execution(side_effect=emit_one),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db"),
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _collect_chat_turn(_make_setup(n_models=1))

        reasoning = [
            p
            for p in packets
            if isinstance(p, Packet)
            and isinstance(p.obj, ItemUpdate)
            and isinstance(p.obj.item, ReasoningItem)
        ]
        assert len(reasoning) == 1
        assert reasoning[0].model_index == 0

    def test_n2_each_model_packet_tagged_with_its_index(self) -> None:
        """Multi-model path: packets from model 0 get index=0, model 1 gets index=1."""

        def emit_one(**kwargs: Any) -> None:
            # _model_idx is set by _run_model based on position in setup.responses
            emitter = kwargs["emitter"]
            emitter.emit(
                Packet(
                    obj=ItemUpdate(item=ReasoningItem()),
                )
            )

        with (
            patch_execution(side_effect=emit_one),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db"),
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _collect_chat_turn(_make_setup(n_models=2))

        reasoning = [
            p
            for p in packets
            if isinstance(p, Packet)
            and isinstance(p.obj, ItemUpdate)
            and isinstance(p.obj.item, ReasoningItem)
        ]
        assert len(reasoning) == 2
        indices = {p.model_index for p in reasoning}
        assert indices == {0, 1}

    def test_preparation_error_yields_streaming_error(self) -> None:
        """An exception inside a worker thread is surfaced as a StreamingError."""

        with (
            patch(
                "onyx.chat.execution.create_chat_agent",
                side_effect=RuntimeError("intentional test failure"),
            ),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db"),
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _collect_chat_turn(_make_setup(n_models=1))

        errors = [p for p in packets if isinstance(p, StreamingError)]
        assert len(errors) == 1
        # Internal exception details must not reach clients.
        assert errors[0].error_code == "UNKNOWN_ERROR"
        assert "intentional test failure" not in errors[0].error

    def test_context_window_overflow_surfaces_as_context_too_long(self) -> None:
        """A provider context-window rejection in a worker surfaces as
        CONTEXT_TOO_LONG and non-retryable through the _run_model -> drain path."""

        def overflow(**_kwargs: Any) -> None:
            raise ContextWindowExceededError(
                "This model's maximum context length is 8192 tokens",
                model="gpt-4",
                llm_provider="openai",
            )

        with (
            patch_execution(side_effect=overflow),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db"),
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _collect_chat_turn(_make_setup(n_models=1))

        errors = [p for p in packets if isinstance(p, StreamingError)]
        assert len(errors) == 1
        assert errors[0].error_code == "CONTEXT_TOO_LONG"
        assert errors[0].is_retryable is False

    def test_model_refusal_preserves_error_classification(self) -> None:
        refusal_message = "The selected model declined to respond."
        refusal = EmptyLLMResponseError(
            provider="anthropic",
            model="claude-fable-5",
            tool_choice=ToolChoiceOptions.AUTO,
            client_error_msg=refusal_message,
            error_code=MODEL_REFUSAL_ERROR_CODE,
            is_retryable=False,
            finish_reason=CONTENT_FILTER_FINISH_REASON,
        )

        with (
            patch("onyx.chat.execution.create_chat_agent", side_effect=refusal),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db"),
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _collect_chat_turn(_make_setup(n_models=1))

        errors = [packet for packet in packets if isinstance(packet, StreamingError)]
        assert len(errors) == 1
        assert errors[0].error == refusal_message
        assert errors[0].error_code == MODEL_REFUSAL_ERROR_CODE
        assert errors[0].is_retryable is False
        assert errors[0].details is not None
        assert errors[0].details["finish_reason"] == CONTENT_FILTER_FINISH_REASON

    def test_one_model_error_does_not_stop_other_models(self) -> None:
        """A failing model yields StreamingError; the surviving model's packets still arrive."""
        setup = _make_setup(n_models=2)

        def fail_model_0_succeed_model_1(**kwargs: Any) -> None:
            if kwargs["llm"] is setup.responses[0].llm:
                raise RuntimeError("model 0 failed")
            kwargs["emitter"].emit(
                Packet(
                    obj=ItemUpdate(item=ReasoningItem()),
                )
            )

        with (
            patch_execution(
                side_effect=fail_model_0_succeed_model_1,
            ),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db"),
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _collect_chat_turn(setup)

        errors = [p for p in packets if isinstance(p, StreamingError)]
        assert len(errors) == 1

        reasoning = [
            p
            for p in packets
            if isinstance(p, Packet)
            and isinstance(p.obj, ItemUpdate)
            and isinstance(p.obj.item, ReasoningItem)
        ]
        assert len(reasoning) == 1
        assert reasoning[0].model_index == 1

    def test_cancellation_yields_user_cancelled_stop(self) -> None:
        """A cached Stop request ends the turn with user_cancelled."""

        def slow_llm(**_kwargs: Any) -> None:
            _wait_for_stop()

        setup = _make_setup(n_models=1)
        setup.cache.exists.return_value = True
        completion_called = threading.Event()

        with (
            patch_execution(side_effect=slow_llm),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch(
                "onyx.chat.history_store.save_chat_response_to_db",
                side_effect=lambda *_, **__: completion_called.set(),
            ),
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _collect_chat_turn(setup)
            assert completion_called.wait(timeout=5)

        stops = [
            p
            for p in packets
            if isinstance(p, Packet) and isinstance(p.obj, OverallStop)
        ]
        assert any(
            isinstance(s.obj, OverallStop) and s.obj.stop_reason == "user_cancelled"
            for s in stops
        )

    def test_stop_interrupts_workers_during_continuous_output(self) -> None:
        setup = _make_setup(n_models=2)
        started = [threading.Event(), threading.Event()]
        stopped = [threading.Event(), threading.Event()]
        deadline = time.monotonic() + 5

        def stop_requested(_key: str) -> bool:
            return all(event.is_set() for event in started)

        setup.cache.exists.side_effect = stop_requested

        def emit_until_cancelled(**kwargs: Any) -> None:
            index = next(
                i
                for i, model in enumerate(setup.responses)
                if model.llm is kwargs["llm"]
            )
            signal = current_cancellation()
            assert signal is not None
            started[index].set()
            try:
                while time.monotonic() < deadline:
                    time.sleep(0.001)
                    signal.check()
                    kwargs["emitter"].emit(
                        Packet(
                            obj=ItemUpdate(item=ReasoningItem()),
                        )
                    )
                raise AssertionError("Stop did not reach the model worker")
            finally:
                stopped[index].set()

        with (
            patch_execution(
                side_effect=emit_until_cancelled,
            ),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db") as persist,
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _collect_chat_turn(setup)
            assert all(event.wait(2) for event in stopped)
            assert persist.call_count == 2
        assert not any(isinstance(packet, StreamingError) for packet in packets)
        assert any(
            isinstance(packet, Packet)
            and isinstance(packet.obj, OverallStop)
            and packet.obj.stop_reason == "user_cancelled"
            for packet in packets
        )

    def test_stop_button_calls_completion_for_all_models(self) -> None:
        """Stop persists each model once."""

        def slow_llm(**_kwargs: Any) -> None:
            _wait_for_stop()

        setup = _make_setup(n_models=2)
        setup.cache.exists.return_value = True
        model_0_persisted = threading.Event()
        model_1_persisted = threading.Event()

        def mark_persisted(*_: Any, **kwargs: Any) -> None:
            if kwargs["message_id"] is setup.responses[0].message_id:
                model_0_persisted.set()
            else:
                model_1_persisted.set()

        with (
            patch_execution(side_effect=slow_llm),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch(
                "onyx.chat.history_store.save_chat_response_to_db",
                side_effect=mark_persisted,
            ) as mock_handle,
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _collect_chat_turn(setup)
            assert model_0_persisted.wait(timeout=5)
            assert model_1_persisted.wait(timeout=5)
            assert mock_handle.call_count == 2

        stops = [
            p
            for p in packets
            if isinstance(p, Packet) and isinstance(p.obj, OverallStop)
        ]
        assert any(
            isinstance(stop.obj, OverallStop)
            and stop.obj.stop_reason == "user_cancelled"
            for stop in stops
        )
        persisted_messages = [
            call.kwargs["message_id"] for call in mock_handle.call_args_list
        ]
        assert persisted_messages.count(setup.responses[0].message_id) == 1
        assert persisted_messages.count(setup.responses[1].message_id) == 1

    def test_completion_handle_called_for_each_successful_model(self) -> None:
        """Normal completion persists each successful model once."""
        setup = _make_setup(n_models=2)

        with (
            patch_execution(),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db") as mock_handle,
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            _collect_chat_turn(setup)

        assert mock_handle.call_count == 2
        persisted_messages = [
            call.kwargs["message_id"] for call in mock_handle.call_args_list
        ]
        assert persisted_messages.count(setup.responses[0].message_id) == 1
        assert persisted_messages.count(setup.responses[1].message_id) == 1

    def test_failed_preparation_persists_snapshot_with_error(self) -> None:

        with (
            patch(
                "onyx.chat.execution.create_chat_agent",
                side_effect=RuntimeError("fail"),
            ),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db") as mock_handle,
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            _collect_chat_turn(_make_setup(n_models=1))

        mock_handle.assert_called_once()
        assert mock_handle.call_args.kwargs["response"].error == (
            "An unexpected error occurred while processing your request. Please try again later."
        )
        assert mock_handle.call_args.kwargs["message_id"] == 1000
        assert mock_handle.call_args.kwargs["response"].answer is None

    def test_http_disconnect_completion_via_generator_exit(self) -> None:
        """Worker-thread completion survives HTTP disconnect."""

        completion_called = threading.Event()
        client_gone = threading.Event()

        def emit_then_block_until_drain(**kwargs: Any) -> None:
            emitter = kwargs["emitter"]
            emitter.emit(
                Packet(
                    obj=ItemUpdate(item=ReasoningItem()),
                )
            )
            client_gone.wait(timeout=5)

        setup = _make_setup(n_models=1)
        setup.cache.exists.return_value = False

        with (
            patch_execution(
                side_effect=emit_then_block_until_drain,
            ),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch(
                "onyx.chat.history_store.save_chat_response_to_db",
                side_effect=lambda *_, **__: completion_called.set(),
            ) as mock_handle,
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            gen = cast(Generator, _start_chat_turn(setup, MagicMock()))
            first = next(gen)
            assert isinstance(first, Packet)
            gen.close()
            client_gone.set()

            assert completion_called.wait(timeout=5), (
                "Response execution must save the successful model"
            )
            assert mock_handle.call_count == 1

    def test_http_disconnect_error_saves_message_once(self) -> None:
        """Disconnecting during an erroring run saves the errored message once."""

        client_gone = threading.Event()

        def emit_then_raise_after_drain(**kwargs: Any) -> None:
            emitter = kwargs["emitter"]
            emitter.emit(
                Packet(
                    obj=ItemUpdate(item=ReasoningItem()),
                )
            )
            client_gone.wait(timeout=5)
            raise ClassifiedLLMError(
                client_error_msg="disconnect failure",
                error_code="MODEL_ERROR",
                is_retryable=True,
            )

        setup = _make_setup(n_models=1)
        setup.cache.exists.return_value = False
        commit_called = threading.Event()
        with (
            patch_execution(
                side_effect=emit_then_raise_after_drain,
            ),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch(
                "onyx.chat.history_store.save_chat_response_to_db",
                side_effect=lambda **_kwargs: commit_called.set(),
            ) as mock_handle,
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            gen = cast(Generator, _start_chat_turn(setup, MagicMock()))
            first = next(gen)
            assert isinstance(first, Packet)
            gen.close()
            client_gone.set()

            assert commit_called.wait(timeout=5)
            mock_handle.assert_called_once()
            assert (
                mock_handle.call_args.kwargs["message_id"]
                == setup.responses[0].message_id
            )
            assert (
                "disconnect failure" in mock_handle.call_args.kwargs["response"].error
            )

    def test_b1_race_disconnect_handler_completes_already_finished_model(self) -> None:
        """A finished worker is not persisted again after a later disconnect."""

        completion_called = threading.Event()

        def emit_and_return_immediately(**kwargs: Any) -> None:
            # Emit one packet so the drain loop has something to yield, then return
            # immediately — no blocking.  The worker will be done in microseconds.
            kwargs["emitter"].emit(
                Packet(
                    obj=ItemUpdate(item=ReasoningItem()),
                )
            )

        setup = _make_setup(n_models=1)
        setup.cache.exists.return_value = False

        with (
            patch_execution(
                side_effect=emit_and_return_immediately,
            ),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch(
                "onyx.chat.history_store.save_chat_response_to_db",
                side_effect=lambda *_, **__: completion_called.set(),
            ) as mock_handle,
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            gen = cast(Generator, _start_chat_turn(setup, MagicMock()))
            first = next(gen)
            assert isinstance(first, Packet)
            assert completion_called.wait(timeout=5)
            gen.close()

            assert completion_called.wait(timeout=5), (
                "completed model should stay persisted"
            )
            assert mock_handle.call_count == 1, "completion must be called exactly once"

    def test_http_disconnect_persists_each_model_once(self) -> None:
        """Disconnecting mid-run persists each model once, even with staggered exits."""

        client_gone = threading.Event()

        def emit_and_maybe_block(**kwargs: Any) -> None:
            emitter = kwargs["emitter"]
            llm = kwargs["llm"]
            emitter.emit(
                Packet(
                    obj=ItemUpdate(item=ReasoningItem()),
                )
            )
            if llm is setup.responses[1].llm:
                client_gone.wait(timeout=5)

        setup = _make_setup(n_models=2)
        setup.cache.exists.return_value = False
        model_0_persisted = threading.Event()
        model_1_persisted = threading.Event()

        def mark_persisted(*_: Any, **kwargs: Any) -> None:
            if kwargs["message_id"] is setup.responses[0].message_id:
                model_0_persisted.set()
            else:
                model_1_persisted.set()

        with (
            patch_execution(
                side_effect=emit_and_maybe_block,
            ),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch(
                "onyx.chat.history_store.save_chat_response_to_db",
                side_effect=mark_persisted,
            ) as mock_handle,
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            gen = cast(Generator, _start_chat_turn(setup, MagicMock()))
            first = next(gen)
            assert isinstance(first, Packet)
            assert model_0_persisted.wait(timeout=5)
            gen.close()
            client_gone.set()
            assert model_1_persisted.wait(timeout=5)

        assert mock_handle.call_count == 2
        persisted_messages = [
            call.kwargs["message_id"] for call in mock_handle.call_args_list
        ]
        assert persisted_messages.count(setup.responses[0].message_id) == 1
        assert persisted_messages.count(setup.responses[1].message_id) == 1

    def test_disconnect_buffers_full_stream_and_marks_done(self) -> None:
        """After a disconnect the writer keeps buffering to the end and marks done."""

        client_gone = threading.Event()

        def emit_then_block(**kwargs: Any) -> None:
            kwargs["emitter"].emit(
                Packet(
                    obj=ItemUpdate(item=ReasoningItem()),
                )
            )
            client_gone.wait(timeout=5)
            kwargs["emitter"].emit(
                Packet(
                    obj=ItemUpdate(item=ReasoningItem()),
                )
            )

        setup = _make_setup(n_models=1)
        setup.cache.exists.return_value = False
        stream_buffer = MagicMock(truncated=False)
        done_marked = threading.Event()
        stream_buffer.mark_done.side_effect = lambda: done_marked.set()

        with (
            patch_execution(
                side_effect=emit_then_block,
            ),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db"),
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            gen = cast(
                Generator,
                _start_chat_turn(setup, MagicMock(), stream_buffer=stream_buffer),
            )
            first = next(gen)
            assert isinstance(first, Packet)
            gen.close()
            client_gone.set()

            assert done_marked.wait(timeout=5), (
                "writer must mark the buffer done after the run finishes"
            )

        buffered = "".join(
            call.args[0] for call in stream_buffer.append_line.call_args_list
        )
        # Both packets reached the buffer — including the one emitted after the
        # client was gone.
        assert buffered.count("item_update") == 2

    def test_stop_preserves_failed_and_cancelled_model_snapshots(self) -> None:

        def fail_model_0(**kwargs: Any) -> None:
            if kwargs["llm"] is setup.responses[0].llm:
                raise ClassifiedLLMError(
                    client_error_msg="model 0 errored",
                    error_code="MODEL_ERROR",
                    is_retryable=True,
                )
            _wait_for_stop()

        setup = _make_setup(n_models=2)
        setup.cache.exists.return_value = True
        model_1_persisted = threading.Event()

        with (
            patch_execution(side_effect=fail_model_0),
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch(
                "onyx.chat.history_store.save_chat_response_to_db",
                side_effect=lambda *_, **__: model_1_persisted.set(),
            ) as mock_handle,
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            _collect_chat_turn(setup)
            assert model_1_persisted.wait(timeout=5)
            assert mock_handle.call_count == 2

        persisted = {
            call.kwargs["message_id"]: call.kwargs
            for call in mock_handle.call_args_list
        }
        assert (
            "model 0 errored"
            in persisted[setup.responses[0].message_id]["response"].error
        )
        assert persisted[setup.responses[1].message_id]["response"].cancelled

    def test_response_future_used_for_model_zero(self) -> None:
        """When provided, response_future is used as response_futures[0]."""

        external = Future[ChatResponseOutcome]()
        setup = _make_setup(n_models=1)

        with (
            patch_execution() as mock_llm,
            patch("onyx.chat.prepare.construct_tools", return_value={}),
            patch("onyx.chat.history_store.save_chat_response_to_db"),
            patch(
                "onyx.chat.prepare.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            list(_start_chat_turn(setup, MagicMock(), response_future=external))

        assert mock_llm.call_args.args[3] is external


type ModelExecution = Callable[
    [
        ChatTurnSetup,
        User,
        int,
        Future[ChatResponseOutcome],
        Emitter,
        CancellationSignal,
        bool,
    ],
    None,
]


@contextmanager
def mock_model_execution(
    *, side_effect: ModelExecution | BaseException | None = None
) -> Generator[MagicMock, None, None]:
    model = MagicMock(side_effect=side_effect)
    captured: dict[int, tuple[Future[ChatResponseOutcome], Emitter]] = {}
    lock = threading.Lock()
    original_execute = ChatTurnExecution._run_response

    def execute(
        turn: ChatTurnExecution,
        index: int,
        emitter: Emitter,
        *,
        startup_error: BaseException | None = None,
    ) -> None:
        with lock:
            captured[index] = (turn._response_futures[index], emitter)
        original_execute(
            turn,
            index,
            emitter,
            startup_error=startup_error,
        )

    def prepare(
        setup: ChatTurnSetup,
        user: User,
        index: int,
        _cancellation: CancellationSignal,
        auto_filters: bool,
    ) -> ChatAgent:
        with lock:
            response_future, emitter = captured[index]

        def generate(
            _request: GenerationRequest, signal: CancellationSignal
        ) -> AssistantMessage:
            model(setup, user, index, response_future, emitter, signal, auto_filters)
            return AssistantMessage(content=[TextContent(text="Partial answer")])

        agent = Agent(FakeModelClient(generate))
        return _chat_agent(agent)

    with (
        patch.object(ChatTurnExecution, "_run_response", execute),
        patch("onyx.chat.execution.create_chat_agent", side_effect=prepare),
        patch("onyx.chat.execution.ResponsePresenter"),
    ):
        yield model


def patch_execution(
    *, side_effect: Callable[..., Any] | BaseException | None = None
) -> AbstractContextManager[MagicMock]:
    def execute(
        setup: ChatTurnSetup,
        _user: User,
        index: int,
        state: Future[ChatResponseOutcome],
        emitter: Emitter,
        cancellation: CancellationSignal,
        _auto_filters: bool,
    ) -> None:
        with cancellation_scope(cancellation):
            if isinstance(side_effect, BaseException):
                raise side_effect
            if side_effect:
                side_effect(
                    emitter=emitter,
                    llm=setup.responses[index].llm,
                    response_future=state,
                )
            cancellation.check()

    return mock_model_execution(side_effect=execute)


@pytest.fixture(autouse=True)
def mock_settings() -> Generator[None, None, None]:
    with (
        patch("onyx.chat.execution.load_settings"),
        patch(
            "onyx.chat.execution.create_chat_agent_coordinator",
            side_effect=lambda *_args, **kwargs: AgentCoordinator(
                store=kwargs["response_store"]
            ),
        ),
    ):
        yield


def test_persistence_failure_reaches_live_and_resumed_readers() -> None:

    setup = _make_setup()
    buffer = MagicMock(truncated=False)
    with (
        mock_model_execution(),
        patch(
            "onyx.chat.history_store.save_chat_response_to_db",
            side_effect=RuntimeError("database unavailable"),
        ) as save,
    ):
        packets = list(_start_chat_turn(setup, MagicMock(), stream_buffer=buffer))

    errors = [packet for packet in packets if isinstance(packet, StreamingError)]
    assert len(errors) == 1
    assert errors[0].error_code == "RESPONSE_SAVE_ERROR"
    assert errors[0].details == {"model_index": 0}
    assert "database unavailable" not in errors[0].error
    assert any(
        "RESPONSE_SAVE_ERROR" in call.args[0]
        for call in buffer.append_line.call_args_list
    )
    assert save.call_count == 1
    buffer.mark_done.assert_called_once()


@pytest.mark.parametrize("failure_stage", ["startup", "worker", "launch"])
def test_startup_failure_finishes_every_response(failure_stage: str) -> None:
    setup = _make_setup(2)
    buffer = MagicMock(truncated=False)
    from onyx.utils.threadpool_concurrency import start_thread_future

    def start_job(operation: Callable[[], None], **kwargs: Any) -> Future[None]:
        name = kwargs.get("name")
        if (failure_stage == "worker" and name == "chat-response") or (
            failure_stage == "launch" and name == "chat-control"
        ):
            raise RuntimeError("Startup failed")
        return start_thread_future(operation, **kwargs)

    with (
        patch("onyx.chat.execution.start_thread_future", side_effect=start_job),
        patch(
            "onyx.chat.execution.ChatTurnExecution.begin",
            side_effect=RuntimeError("Startup failed"),
        )
        if failure_stage == "startup"
        else nullcontext(),
        patch("onyx.chat.execution.create_chat_agent") as prepare,
        patch("onyx.chat.history_store.save_chat_response_to_db") as save,
    ):
        if failure_stage == "launch":
            with pytest.raises(RuntimeError, match="Startup failed"):
                _start_chat_turn(setup, MagicMock(), stream_buffer=buffer)
            save.assert_not_called()
        else:
            packets = list(_start_chat_turn(setup, MagicMock(), stream_buffer=buffer))
            assert save.call_count == 2
            assert {call.kwargs["message_id"] for call in save.call_args_list} == {
                1000,
                1001,
            }
            assert all(call.kwargs["response"].error for call in save.call_args_list)
            assert any(isinstance(packet, StreamingError) for packet in packets)
        prepare.assert_not_called()
    buffer.mark_done.assert_called_once()


def test_disconnect_during_initial_packets_closes_unstarted_reader() -> None:
    from onyx.chat.process_message import _stream_chat_turn
    from onyx.chat.stream_buffer import ChatStream
    from onyx.server.query_and_chat.streaming_models import heartbeat_packet

    setup = _make_setup()
    first = heartbeat_packet()
    setup.initial_packets = [first]
    reader = ChatStream()
    reader.publish(heartbeat_packet())
    with (
        patch("onyx.chat.process_message.prepare_chat_turn", return_value=setup),
        patch("onyx.chat.process_message.StreamBufferWriter"),
        patch("onyx.chat.process_message.start_chat_turn", return_value=reader),
    ):
        stream = cast(
            Generator[Any, None, None], _stream_chat_turn(_make_request(), MagicMock())
        )
        assert next(stream) is first
        stream.close()

    reader.publish(heartbeat_packet())
    with pytest.raises(StopIteration):
        next(reader)


@pytest.mark.parametrize(
    "blocked_storage,save_fails",
    [("response", False), ("response", True), ("stream", False)],
)
def test_stop_reaches_other_model_before_blocked_storage_resumes(
    blocked_storage: str,
    save_fails: bool,
) -> None:
    from contextvars import ContextVar

    from onyx.server.query_and_chat.streaming_models import heartbeat_packet

    setup = _make_setup(2)
    buffer = MagicMock(truncated=False)
    provider_started = threading.Event()
    provider_cancelled = threading.Event()
    storage_started = threading.Event()
    release_storage = threading.Event()
    stop_requested = threading.Event()
    setup.cache.exists.side_effect = lambda _key: stop_requested.is_set()
    request_context: ContextVar[str] = ContextVar(
        "storage_test_context", default="unset"
    )
    token = request_context.set("request")

    def execute(*args: Any) -> None:
        index, _state, emitter, signal = args[2:6]
        if index == 0:
            assert provider_started.wait(2)
            emitter.emit(heartbeat_packet())
            return
        with signal.on_cancel(provider_cancelled.set):
            provider_started.set()
            assert provider_cancelled.wait(5)
            signal.check()

    def block() -> None:
        assert request_context.get() == "request"
        storage_started.set()
        assert release_storage.wait(5)

    def save(**kwargs: Any) -> None:
        assert request_context.get() == "request"
        if (
            blocked_storage == "response"
            and kwargs["message_id"] == setup.responses[0].message_id
        ):
            block()
            if save_fails:
                raise RuntimeError("database unavailable")

    if blocked_storage == "stream":
        buffer.append_line.side_effect = lambda _line: block()

    try:
        with (
            mock_model_execution(side_effect=execute),
            patch(
                "onyx.chat.history_store.save_chat_response_to_db", side_effect=save
            ) as persist,
            patch("onyx.chat.execution._CANCEL_POLL_INTERVAL_S", 0.01),
        ):
            reader = _start_chat_turn(setup, MagicMock(), stream_buffer=buffer)
            try:
                assert storage_started.wait(2)
                stop_requested.set()
                cancelled_before_release = provider_cancelled.wait(2)
            finally:
                stop_requested.set()
                release_storage.set()
                packets = list(reader)
        assert cancelled_before_release, (
            "Storage must not block Stop delivery to the provider"
        )
        assert persist.call_count == 2
        assert {call.kwargs["message_id"] for call in persist.call_args_list} == {
            1000,
            1001,
        }
        errors = [packet for packet in packets if isinstance(packet, StreamingError)]
        assert [error.error_code for error in errors] == (
            ["RESPONSE_SAVE_ERROR"] if save_fails else []
        )
        buffer.mark_done.assert_called_once()
    finally:
        request_context.reset(token)


def test_slow_reader_receives_gap_instead_of_incomplete_success() -> None:
    from onyx.chat.stream_buffer import _STREAM_QUEUE_CAPACITY, ChatStream
    from onyx.server.query_and_chat.streaming_models import heartbeat_packet

    reader = ChatStream()
    for _ in range(_STREAM_QUEUE_CAPACITY + 1):
        reader.publish(heartbeat_packet())
    items = list(reader)
    assert len(items) == 1
    assert isinstance(items[0], StreamingError)
    assert items[0].error_code == "STREAM_GAP"


def test_overflowed_stream_storage_finishes_retention_cleanup() -> None:
    from onyx.chat.emitter import Emitter
    from onyx.chat.models import ChatTurnSetup
    from onyx.llm.cancellation import CancellationSignal

    writing = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    overflowed = threading.Event()
    buffer = MagicMock(truncated=False)
    turns = ActiveChatTurns()

    def append(_line: str) -> None:
        writing.set()
        assert release.wait(3)

    buffer.append_line.side_effect = append
    buffer.mark_done.side_effect = closed.set
    buffer.mark_truncated.side_effect = lambda: setattr(buffer, "truncated", True)

    def execute(
        _setup: ChatTurnSetup,
        _user: User,
        _index: int,
        _state: Future[ChatResponseOutcome],
        emitter: Emitter,
        _signal: CancellationSignal,
        _filters: bool,
    ) -> None:
        emitter.emit(Packet(obj=ItemUpdate(item=ReasoningItem())))
        assert writing.wait(2)
        for _ in range(10):
            emitter.emit(Packet(obj=ItemUpdate(item=ReasoningItem())))
        overflowed.set()

    with (
        patch("onyx.chat.stream_buffer._BUFFER_WORK_CAPACITY", 1),
        patch("onyx.agents.concurrency.CLEANUP_SECONDS", 0.02),
        mock_model_execution(side_effect=execute),
        patch("onyx.chat.history_store.save_chat_response_to_db") as save,
    ):
        try:
            reader = start_chat_turn(
                _make_setup(1),
                MagicMock(),
                stream_buffer=buffer,
                active_chat_turns=turns,
            )
            assert overflowed.wait(2)
            with patch("onyx.chat.execution._CHAT_SHUTDOWN_WAIT_SECONDS", 0.01):
                assert not turns.close()
            list(reader)
            assert save.call_count == 1
            assert buffer.append_line.call_count == 1
        finally:
            release.set()
        assert closed.wait(2)
        assert turns.close()
    buffer.mark_truncated.assert_called_once()
    buffer.mark_done.assert_called_once()


def test_cache_failure_does_not_finalize_active_execution() -> None:
    release = threading.Event()
    cache_failed = threading.Event()
    buffer = MagicMock(truncated=False)

    def fail_cache(_line: str) -> None:
        cache_failed.set()
        raise RuntimeError("Cache unavailable")

    def execute(
        _setup: ChatTurnSetup,
        _user: User,
        _index: int,
        _state: Future[ChatResponseOutcome],
        emitter: Emitter,
        _signal: CancellationSignal,
        _filters: bool,
    ) -> None:
        emitter.emit(Packet(obj=ItemUpdate(item=ReasoningItem())))
        assert release.wait(5)

    buffer.append_line.side_effect = fail_cache
    buffer.mark_truncated.side_effect = lambda: setattr(buffer, "truncated", True)
    with (
        mock_model_execution(side_effect=execute),
        patch("onyx.chat.history_store.save_chat_response_to_db") as persist,
    ):
        reader = _start_chat_turn(_make_setup(), MagicMock(), stream_buffer=buffer)
        try:
            assert cache_failed.wait(2)
            first = next(reader)
            second = next(reader)
            assert isinstance(first, Packet)
            assert isinstance(second, StreamingError)
            assert second.error_code == "STREAM_GAP"
            persist.assert_not_called()
        finally:
            release.set()
            list(reader)
        persist.assert_called_once()
    buffer.mark_done.assert_called_once()
    buffer.mark_truncated.assert_called_once()


def test_full_response_waits_for_execution_after_delivery_ends() -> None:
    entered = threading.Event()
    release = threading.Event()
    response_future = Future[ChatResponseOutcome]()

    def reply(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        entered.set()
        assert release.wait(5)
        return AssistantMessage(content=[TextContent(text="Finished answer")])

    chat_agent = _chat_agent(Agent(FakeModelClient(reply)))

    with (
        patch("onyx.chat.execution.create_chat_agent", return_value=chat_agent),
        patch("onyx.chat.history_store.save_chat_response_to_db") as persist,
        ContextThreadPoolExecutor(max_workers=1) as executor,
    ):
        reader = _start_chat_turn(
            _make_setup(), MagicMock(), response_future=response_future
        )
        try:
            assert entered.wait(2)
            ended_delivery: list[AnswerStreamPart] = [
                MessageResponseIDInfo(
                    user_message_id=41, reserved_assistant_message_id=42
                ),
                StreamingError(error="Delivery gap", error_code="STREAM_GAP"),
            ]
            full = executor.submit(
                lambda: gather_stream_full(iter(ended_delivery), response_future)
            )
            with pytest.raises(TimeoutError):
                full.result(timeout=0.05)
            persist.assert_not_called()
            release.set()
            response = full.result(timeout=5)
            assert response.answer == "Finished answer"
            assert response.error_msg == "Delivery gap"
            list(reader)
            assert (
                persist.call_args.kwargs["response"]
                is response_future.result().response
            )
        finally:
            release.set()
            list(reader)


@pytest.mark.parametrize("failure_stage", ["execution", "projection"])
def test_failed_response_releases_full_response_waiter(failure_stage: str) -> None:
    response_future: Future[ChatResponseOutcome] = Future()
    with (
        mock_model_execution(
            side_effect=RuntimeError("Execution failed"),
        ),
        patch(
            "onyx.chat.persistence.chat_error",
            return_value=StreamingError(
                error="Execution failed", error_code="GENERATION_FAILED"
            ),
        ),
        patch("onyx.chat.history_store.save_chat_response_to_db"),
        patch(
            "onyx.chat.persistence.project_response",
            side_effect=ValueError("Invalid projection"),
        )
        if failure_stage == "projection"
        else nullcontext(),
    ):
        list(
            _start_chat_turn(
                _make_setup(), MagicMock(), response_future=response_future
            )
        )
        if failure_stage == "projection":
            with pytest.raises(ValueError, match="Invalid projection"):
                response_future.result()
        else:
            response = gather_stream_full(
                iter(
                    [
                        MessageResponseIDInfo(
                            user_message_id=41, reserved_assistant_message_id=42
                        )
                    ]
                ),
                response_future,
            )
            assert response.answer == ""
            assert response.error_msg == "Execution failed"


@pytest.mark.parametrize(
    "save_behavior,execution_fails",
    [
        ("saved", False),
        ("failed", False),
        ("failed", True),
        ("late_success", False),
        ("late_failure", False),
    ],
)
def test_full_response_reports_save_outcome_after_delivery_ends(
    save_behavior: str,
    execution_fails: bool,
) -> None:
    response_future = Future[ChatResponseOutcome]()
    save_started = threading.Event()
    release_save = threading.Event()
    save_finished = threading.Event()
    is_late = save_behavior.startswith("late_")

    def save(
        *, message_id: int, response: ChatResponseSnapshot, **_kwargs: Any
    ) -> None:
        assert message_id == 1000
        assert response.answer == ("" if execution_fails else "Partial answer")
        save_started.set()
        try:
            assert release_save.wait(5)
            if save_behavior in {"failed", "late_failure"}:
                raise RuntimeError("Database unavailable")
        finally:
            save_finished.set()

    with (
        mock_model_execution(
            side_effect=RuntimeError("Generation failed") if execution_fails else None,
        ),
        patch(
            "onyx.chat.persistence.chat_error",
            return_value=StreamingError(
                error="Generation failed", error_code="GENERATION_FAILED"
            ),
        ),
        patch("onyx.chat.history_store.save_chat_response_to_db", side_effect=save),
        patch(
            "onyx.chat.persistence.PERSISTENCE_WAIT_SECONDS",
            0.15 if is_late else 5,
        ),
        ContextThreadPoolExecutor(max_workers=1) as executor,
    ):
        reader = _start_chat_turn(
            _make_setup(), MagicMock(), response_future=response_future
        )
        try:
            assert save_started.wait(2)
            ended_delivery: list[AnswerStreamPart] = [
                MessageResponseIDInfo(
                    user_message_id=41, reserved_assistant_message_id=1000
                ),
                StreamingError(error="Delivery gap", error_code="STREAM_GAP"),
            ]
            full = executor.submit(
                lambda: gather_stream_full(iter(ended_delivery), response_future)
            )
            with pytest.raises(TimeoutError):
                full.result(timeout=0.03)
            if not is_late:
                release_save.set()
            response = full.result(timeout=2)
            outcome = response_future.result()
            expected = (
                PersistenceStatus.UNCONFIRMED
                if is_late
                else (
                    PersistenceStatus.FAILED
                    if save_behavior == "failed"
                    else PersistenceStatus.SAVED
                )
            )
            assert outcome.persistence_status == expected
            assert outcome.response.error == (
                "Generation failed" if execution_fails else None
            )
            assert response.answer == ("" if execution_fails else "Partial answer")
            expected_errors = ["Generation failed"] if execution_fails else []
            if expected != PersistenceStatus.SAVED:
                expected_errors.append(PERSISTENCE_ERROR_MESSAGES[expected])
            assert response.error_msg == (
                "\n".join(expected_errors) if expected_errors else "Delivery gap"
            )
            packets = list(reader)
            save_errors = [
                packet
                for packet in packets
                if isinstance(packet, StreamingError)
                and packet.error_code == "RESPONSE_SAVE_ERROR"
            ]
            assert len(save_errors) == (0 if expected == PersistenceStatus.SAVED else 1)
            if is_late:
                assert not save_finished.is_set()
                release_save.set()
                assert save_finished.wait(2)
                assert response_future.result() is outcome
        finally:
            release_save.set()
            assert save_finished.wait(2)
            list(reader)


def test_blocked_responses_do_not_prevent_new_chat_turns() -> None:
    release = threading.Event()
    started = [threading.Event() for _ in range(35)]
    readers: list[ChatStream] = []

    def execute(
        setup: ChatTurnSetup,
        _user: User,
        _index: int,
        _state: Future[ChatResponseOutcome],
        _emitter: Emitter,
        _signal: CancellationSignal,
        _filters: bool,
    ) -> None:
        started[setup.responses[0].message_id - 1000].set()
        assert release.wait(10)

    with (
        mock_model_execution(side_effect=execute),
        patch("onyx.chat.history_store.save_chat_response_to_db"),
    ):
        try:
            for index in range(len(started)):
                setup = _make_setup()
                setup.responses[0] = setup.responses[0].model_copy(
                    update={"message_id": 1000 + index}
                )
                readers.append(_start_chat_turn(setup, MagicMock()))
            assert all(event.wait(5) for event in started)
        finally:
            release.set()
            for reader in readers:
                list(reader)


def test_preparation_failure_reports_error_before_delivery() -> None:
    request = SendMessageRequest(message="Question", chat_session_id=uuid4())
    with (
        patch(
            "onyx.chat.process_message.prepare_chat_turn",
            side_effect=ValueError("Preparation failed"),
        ) as prepare,
        patch("onyx.chat.process_message.StreamBufferWriter") as delivery,
    ):
        packets = list(_stream_chat_turn(request, MagicMock(spec=User)))
    prepare.assert_called_once()
    delivery.assert_not_called()
    assert any(isinstance(packet, StreamingError) for packet in packets)


def test_api_execution_uses_threads_and_preserves_tenant_after_reader_closes() -> None:
    from onyx.agents.tools import AgentTool, ToolInvocation
    from onyx.llm.models import ToolCall, ToolResult

    async def exercise() -> None:
        api_thread = threading.get_ident()
        tool_entered = threading.Event()
        release_tool = threading.Event()
        saved = threading.Event()
        tenant = "stream-lifecycle-tenant"

        def tool(_invocation: ToolInvocation) -> ToolResult:
            assert threading.get_ident() != api_thread
            assert CURRENT_TENANT_ID_CONTEXTVAR.get() == tenant
            tool_entered.set()
            assert release_tool.wait(timeout=5)
            return ToolResult(content="Finished")

        replies = iter(
            [
                AssistantMessage(
                    content=[ToolCall(id="work", name="work", arguments={})]
                ),
                AssistantMessage(content=[TextContent(text="Answer")]),
            ]
        )
        agent = Agent(
            FakeModelClient(lambda *_: next(replies)),
            tools=[AgentTool(name="work", description="", parameters={}, execute=tool)],
        )
        prepared = _chat_agent(agent, max_steps=2)
        tasks = ActiveChatTurns()
        setup = _make_setup()
        response_future = Future[ChatResponseOutcome]()
        token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant)
        try:
            with (
                patch("onyx.chat.execution.create_chat_agent", return_value=prepared),
                patch(
                    "onyx.chat.history_store.save_chat_response_to_db",
                    side_effect=lambda **_: saved.set(),
                ),
                ContextThreadPoolExecutor(max_workers=1) as worker,
            ):
                reader = await asyncio.wrap_future(
                    worker.submit(
                        lambda: start_chat_turn(
                            setup, MagicMock(), response_future, active_chat_turns=tasks
                        )
                    )
                )
                try:
                    assert await asyncio.wrap_future(
                        worker.submit(lambda: tool_entered.wait(5))
                    )
                    reader.close()
                finally:
                    release_tool.set()
                outcome = await asyncio.wrap_future(
                    worker.submit(lambda: response_future.result(timeout=5))
                )
                assert outcome.response.answer == "Answer"
                assert saved.is_set()
                assert await asyncio.wrap_future(worker.submit(tasks.close))
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(token)

    asyncio.run(exercise())


def test_stop_retains_turn_while_preparation_drains() -> None:
    entered, release, saved = threading.Event(), threading.Event(), threading.Event()
    agent = Agent(
        FakeModelClient(
            lambda *_: pytest.fail("Cancelled preparation must not run the model")
        )
    )
    prepared = _chat_agent(agent)

    def prepare(
        _setup: ChatTurnSetup,
        _user: User,
        _index: int,
        _cancellation: CancellationSignal,
        _auto_filters: bool,
    ) -> ChatAgent:
        entered.set()
        assert release.wait(5)
        return prepared

    tasks = ActiveChatTurns()
    response_future = Future[ChatResponseOutcome]()
    with (
        patch("onyx.chat.execution.create_chat_agent", side_effect=prepare),
        patch(
            "onyx.chat.history_store.save_chat_response_to_db",
            side_effect=lambda **_: saved.set(),
        ),
    ):
        turn = ChatTurnExecution(_make_setup(), MagicMock(), response_future)
        turn.begin()
        tasks.start(turn)
        try:
            assert entered.wait(timeout=3)
            turn.cancellation.cancel()
            assert not turn.finished.done()
            assert not saved.is_set()
        finally:
            release.set()
            turn.delivery.reader.close()
        assert tasks.close()
        assert response_future.result(timeout=1).response.cancelled
        assert saved.is_set()


def test_model_failure_does_not_cancel_comparison_response() -> None:

    def fail(
        _request: GenerationRequest, _signal: CancellationSignal
    ) -> AssistantMessage:
        raise ValueError("Invalid model response")

    def succeed(
        _request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        time.sleep(0.05)
        signal.check()
        return AssistantMessage(content=[TextContent(text="Independent answer")])

    prepared = [_chat_agent(Agent(FakeModelClient(reply))) for reply in (fail, succeed)]

    def prepare(
        _setup: ChatTurnSetup,
        _user: User,
        index: int,
        _cancellation: CancellationSignal,
        _auto_filters: bool,
    ) -> ChatAgent:
        return prepared[index]

    setup = _make_setup(2)
    setup.input_messages = []
    with (
        patch("onyx.chat.execution.create_chat_agent", side_effect=prepare),
        patch("onyx.chat.history_store.save_chat_response_to_db") as save,
    ):
        packets = list(_start_chat_turn(setup, MagicMock()))
    responses = {
        call.kwargs["message_id"]: call.kwargs["response"]
        for call in save.call_args_list
    }
    assert responses[setup.responses[0].message_id].error
    assert responses[setup.responses[1].message_id].answer == "Independent answer"
    assert not responses[setup.responses[1].message_id].cancelled
    assert (
        len([packet for packet in packets if isinstance(packet, StreamingError)]) == 1
    )


def test_renderer_attachment_failure_cancels_run_before_saving() -> None:
    agent = Agent(
        FakeModelClient(lambda *_: pytest.fail("Unbound response must not generate"))
    )
    prepared = _chat_agent(agent)
    setup = _make_setup()
    setup.responses[0] = setup.responses[0].model_copy(update={"llm": agent.llm})
    with (
        patch("onyx.chat.execution.create_chat_agent", return_value=prepared),
        patch(
            "onyx.chat.execution.ResponsePresenter",
            side_effect=ValueError("Renderer unavailable"),
        ),
        patch("onyx.chat.history_store.save_chat_response_to_db") as save,
    ):
        packets = list(_start_chat_turn(setup, MagicMock()))
        save.assert_called_once()
        assert save.call_args.kwargs["response"].error
        assert any(isinstance(packet, StreamingError) for packet in packets)
    assert not agent.state.messages


def test_response_cancelled_before_entry_is_saved() -> None:
    response_future: Future[ChatResponseOutcome] = Future()
    tasks = ActiveChatTurns()
    with (
        patch("onyx.chat.execution.create_chat_agent") as create_agent,
        patch("onyx.chat.history_store.save_chat_response_to_db") as save,
    ):
        turn = ChatTurnExecution(_make_setup(), MagicMock(), response_future)
        turn.begin()
        turn.cancellation.cancel()
        tasks.start(turn)
        assert tasks.close()
        create_agent.assert_not_called()
        save.assert_called_once()
        assert save.call_args.kwargs["response"].cancelled
        assert response_future.result(timeout=1).response.cancelled
        assert turn.finished.done()


def test_closed_chat_supervisor_rejects_without_starting_storage() -> None:
    active_chat_turns = ActiveChatTurns()
    assert active_chat_turns.close()
    response_future: Future[ChatResponseOutcome] = Future()
    with (
        patch("onyx.chat.execution.create_chat_agent") as create_agent,
        patch("onyx.chat.history_store.save_chat_response_to_db") as save,
    ):
        with pytest.raises(RuntimeError, match="shutting down"):
            start_chat_turn(
                _make_setup(),
                MagicMock(),
                response_future,
                active_chat_turns=active_chat_turns,
            )
        with pytest.raises(RuntimeError, match="shutting down"):
            response_future.result(timeout=1)
        create_agent.assert_not_called()
        save.assert_not_called()


def test_response_workers_execute_models_and_share_one_event_consumer() -> None:
    setup = _make_setup(n_models=2)
    tasks = ActiveChatTurns()
    models_entered = threading.Barrier(2)
    model_threads: dict[int, int] = {}
    preparation_threads: dict[int, int] = {}
    observer_threads: set[int] = set()
    lock = threading.Lock()

    def prepare(
        _setup: ChatTurnSetup,
        _user: User,
        index: int,
        _cancellation: CancellationSignal,
        _auto_filters: bool,
    ) -> ChatAgent:
        with lock:
            preparation_threads[index] = threading.get_ident()

        def generate(
            _request: GenerationRequest, _signal: CancellationSignal
        ) -> AssistantMessage:
            with lock:
                model_threads[index] = threading.get_ident()
            models_entered.wait(timeout=5)
            return AssistantMessage(content=[TextContent(text=f"answer {index}")])

        return _chat_agent(Agent(FakeModelClient(generate)))

    def observe(_event: AgentEvent) -> None:
        with lock:
            observer_threads.add(threading.get_ident())

    with (
        patch("onyx.chat.execution.create_chat_agent", side_effect=prepare),
        patch("onyx.chat.execution.ResponsePresenter") as presenter,
        patch("onyx.chat.history_store.save_chat_response_to_db") as save,
    ):
        presenter.return_value.consume.side_effect = observe
        reader = start_chat_turn(setup, MagicMock(), active_chat_turns=tasks)
        try:
            list(reader)
            assert tasks.close()
        finally:
            reader.close()
        assert save.call_count == 2
    assert model_threads == preparation_threads
    assert len(set(model_threads.values())) == 2
    assert len(observer_threads) == 1
    assert observer_threads.isdisjoint(model_threads.values())


def test_stop_after_suspension_retains_root_cancellation_and_saves_once() -> None:
    setup = _make_setup()
    tasks = ActiveChatTurns()
    started = threading.Event()
    runs: list[Run] = []
    response_future = Future[ChatResponseOutcome]()

    def register(run: Run) -> None:
        runs.append(run)
        started.set()

    coordinator = AgentCoordinator(ownership=FakeRunOwnership(register=register))
    agent = Agent(
        FakeModelClient(
            lambda *_: AssistantMessage(
                content=[ToolCall(id="question", name="question", arguments={})]
            )
        ),
        tools=[
            AgentTool(
                name="question",
                description="",
                parameters={},
                execute=lambda _: PendingToolInput(
                    request_id="answer", prompt="Question", mode=InputMode.RESULT
                ),
            )
        ],
    )
    with (
        patch("onyx.chat.execution.create_chat_agent", return_value=_chat_agent(agent)),
        patch(
            "onyx.chat.execution.create_chat_agent_coordinator",
            side_effect=lambda *_args, **kwargs: coordinator.view(
                store=kwargs["response_store"],
                ownership=FakeRunOwnership(register=register),
            ),
        ),
        patch("onyx.chat.history_store.save_chat_response_to_db") as save,
    ):
        reader = start_chat_turn(
            setup, MagicMock(), response_future, active_chat_turns=tasks
        )
        try:
            assert started.wait(5)
            assert runs[0].wait_until_settled(5).status == RunStatus.SUSPENDED
            assert runs[0].wait_for_idle(5)
            assert not response_future.done()
            setup.cache.exists.return_value = True
            outcome = response_future.result(timeout=5)
            assert outcome.response.cancelled
            assert outcome.persistence_status == PersistenceStatus.SAVED
            list(reader)
            assert tasks.close()
            assert save.call_count == 1
        finally:
            reader.close()
            assert coordinator.close(5)


def test_stop_cache_failure_retries_and_keeps_polling_ownership() -> None:
    setup = _make_setup()
    provider_entered = threading.Event()
    cache_failed = threading.Event()
    cache_recovered = threading.Event()
    polled_after_completion = threading.Event()
    outcome = Future[ChatResponseOutcome]()
    tasks = ActiveChatTurns()
    store = MagicMock(spec=ChatRunStore)
    store.has_owned_work = True

    def generate(
        _request: GenerationRequest, signal: CancellationSignal
    ) -> AssistantMessage:
        cancelled = threading.Event()
        with signal.on_cancel(cancelled.set):
            provider_entered.set()
            assert cancelled.wait(5)
        signal.check()
        raise AssertionError("Cancelled provider must not produce an answer")

    def stop_read(_key: str) -> bool:
        if cache_recovered.is_set():
            return True
        if provider_entered.is_set():
            cache_failed.set()
            raise ConnectionError("Cache unavailable")
        return False

    def poll_owned_runs() -> None:
        if turn._delivery_closed:
            polled_after_completion.set()
            store.has_owned_work = False

    store.poll_control.side_effect = poll_owned_runs
    setup.cache.exists.side_effect = stop_read
    turn = ChatTurnExecution(setup, MagicMock(), outcome)
    turn._register_store(store)
    with (
        patch(
            "onyx.chat.execution.create_chat_agent",
            return_value=_chat_agent(Agent(FakeModelClient(generate))),
        ),
        patch("onyx.chat.history_store.save_chat_response_to_db") as save,
        patch("onyx.chat.execution._CANCEL_POLL_INTERVAL_S", 0.01),
        patch("onyx.chat.execution.PROCESSING_REFRESH_INTERVAL_S", 0),
        patch("onyx.chat.execution.set_processing_status") as processing,
    ):
        turn.begin()
        tasks.start(turn)
        try:
            assert cache_failed.wait(5)
            assert not turn.cancellation.cancelled
            assert not outcome.done()
            cache_recovered.set()
            assert outcome.result(timeout=5).response.cancelled
            assert polled_after_completion.wait(5)
            turn.finished.result(timeout=5)
            assert save.call_count == 1
            processing_values = [
                call.kwargs["value"] for call in processing.call_args_list
            ]
            assert processing_values[-1] is False
            assert False not in processing_values[:-1]
        finally:
            turn.delivery.reader.close()
            assert tasks.close()


def test_storage_ownership_failure_reports_failed_response_without_writing() -> None:
    setup = _make_setup()
    outcome = Future[ChatResponseOutcome]()
    tasks = ActiveChatTurns()

    def reject_save(_run: Run) -> None:
        raise RuntimeError("Response ownership was lost")

    coordinator = AgentCoordinator(store=FakeRunStore(save=reject_save))
    with (
        mock_model_execution(),
        patch(
            "onyx.chat.execution.create_chat_agent_coordinator",
            return_value=coordinator,
        ),
        patch("onyx.chat.history_store.save_chat_response_to_db") as save,
    ):
        reader = start_chat_turn(setup, MagicMock(), outcome, active_chat_turns=tasks)
        try:
            result = outcome.result(timeout=5)
            assert result.persistence_status == PersistenceStatus.FAILED
            assert result.response.answer == "Partial answer"
            errors = [packet for packet in reader if isinstance(packet, StreamingError)]
            assert len(errors) == 1
            assert errors[0].error_code == "RESPONSE_SAVE_ERROR"
            assert "ownership" not in errors[0].error
            save.assert_not_called()
            assert tasks.close()
        finally:
            reader.close()
            assert coordinator.close(5)


def test_blocked_stream_status_does_not_block_ownership_polling() -> None:
    setup = _make_setup()
    entered = threading.Event()
    release = threading.Event()

    def stop_read(_key: str) -> bool:
        entered.set()
        assert release.wait(5)
        return False

    setup.cache.exists.side_effect = stop_read
    store = MagicMock(spec=ChatRunStore)
    turn = ChatTurnExecution(setup, MagicMock())
    turn._register_store(store)
    turn._last_stop_check = 0
    try:
        turn._poll_control()
        assert entered.wait(5)
        turn._poll_control()
        assert store.poll_control.call_count == 2
        assert not turn.cancellation.cancelled
    finally:
        release.set()
        assert turn._stream_status is not None
        turn._stream_status.result(timeout=5)


def test_processing_marker_failure_does_not_cancel_chat() -> None:
    turn = ChatTurnExecution(_make_setup(), MagicMock())
    with patch(
        "onyx.chat.execution.set_processing_status",
        side_effect=[ConnectionError("offline"), None],
    ) as processing:
        turn._last_refresh = 0
        turn._poll_stream_status()
        assert not turn.cancellation.cancelled
        turn._last_refresh = 0
        turn._poll_stream_status()
        assert processing.call_count == 2
        assert not turn.cancellation.cancelled


def test_last_response_drain_settles_turn_after_status_cleanup() -> None:
    turn = ChatTurnExecution(_make_setup(), MagicMock())
    turn._delivery_finished = True
    turn._finish_response(0)
    assert turn.finished.done()


def test_control_failure_retains_turn_and_polls_ownership_until_workers_drain() -> None:
    entered = threading.Event()
    release = threading.Event()
    polled_after_failure = threading.Event()
    outcome = Future[ChatResponseOutcome]()
    tasks = ActiveChatTurns()
    store = MagicMock(spec=ChatRunStore)
    store.has_owned_work = True
    turn = ChatTurnExecution(_make_setup(), MagicMock(), outcome)
    turn._register_store(store)
    prepared = _chat_agent(
        Agent(
            FakeModelClient(
                lambda *_: pytest.fail("Cancelled preparation must not generate")
            )
        )
    )

    def prepare(*_args: object) -> ChatAgent:
        entered.set()
        assert release.wait(5)
        return prepared

    failed = False
    poll_control = turn._poll_control

    def poll() -> None:
        nonlocal failed
        if entered.is_set() and not failed:
            failed = True
            raise RuntimeError("Control iteration failed")
        poll_control()

    def poll_ownership() -> None:
        if turn.cancellation.cancelled:
            polled_after_failure.set()
        if outcome.done():
            store.has_owned_work = False

    store.poll_control.side_effect = poll_ownership
    with (
        patch("onyx.chat.execution.create_chat_agent", side_effect=prepare),
        patch("onyx.chat.history_store.save_chat_response_to_db"),
        patch.object(turn, "_poll_control", side_effect=poll),
        patch("onyx.chat.execution._CANCEL_POLL_INTERVAL_S", 0.01),
    ):
        turn.begin()
        tasks.start(turn)
        try:
            assert entered.wait(5)
            assert polled_after_failure.wait(5)
            assert not turn.finished.done()
            assert not outcome.done()
            release.set()
            assert outcome.result(timeout=5).response.cancelled
            turn.finished.result(timeout=5)
        finally:
            release.set()
            turn.delivery.reader.close()
            assert tasks.close()


def test_failed_ownership_poll_does_not_starve_other_stores() -> None:
    turn = ChatTurnExecution(_make_setup(), MagicMock())
    turn._delivery_closed = True
    failed = MagicMock(spec=ChatRunStore)
    healthy = MagicMock(spec=ChatRunStore)
    failed.poll_control.side_effect = RuntimeError("Ownership poll failed")
    turn._register_store(failed)
    turn._register_store(healthy)
    turn._poll_control()
    assert turn.cancellation.cancelled
    healthy.poll_control.assert_called_once()
    failed.poll_control.side_effect = None
    turn._poll_control()
    assert failed.poll_control.call_count == 2
    assert healthy.poll_control.call_count == 2
