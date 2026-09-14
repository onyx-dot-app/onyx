"""Unit tests for multi-model streaming validation and DB helpers.

These are pure unit tests — no real database or LLM calls required.
The validation logic in handle_multi_model_stream fires before any external
calls, so we can trigger it with lightweight mocks.
"""

import threading
import time
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager
from typing import Any, cast
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from litellm.exceptions import ContextWindowExceededError

from onyx.chat.chat_state import PreparedModel
from onyx.chat.errors import EmptyLLMResponseError
from onyx.chat.models import StreamingError
from onyx.configs.constants import MessageType
from onyx.db.chat import set_preferred_response
from onyx.db.models import ChatMessage
from onyx.llm.cancellation import current_cancellation
from onyx.llm.interfaces import LLM, LLMUserIdentity
from onyx.llm.models import ToolChoiceOptions
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import (
    ChatHeartbeat,
    OverallStop,
    Packet,
    ReasoningStart,
)
from onyx.utils.variable_functionality import global_version

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
        user_msg = MagicMock()
        user_msg.message_type = MessageType.USER

        # First call returns user_msg, second call (for assistant) returns None
        db.get.side_effect = [user_msg, None]

        with pytest.raises(ValueError, match="not found"):
            set_preferred_response(
                db, user_message_id=1, preferred_assistant_message_id=2
            )

    def test_assistant_not_child_of_user(self) -> None:
        db = MagicMock()
        user_msg = MagicMock()
        user_msg.message_type = MessageType.USER

        assistant_msg = MagicMock()
        assistant_msg.parent_message_id = 999  # different parent

        db.get.side_effect = [user_msg, assistant_msg]

        with pytest.raises(ValueError, match="not a child"):
            set_preferred_response(
                db, user_message_id=1, preferred_assistant_message_id=2
            )

    def test_valid_call_sets_preferred_response_id(self) -> None:
        db = MagicMock()
        user_msg = MagicMock()
        user_msg.message_type = MessageType.USER

        assistant_msg = MagicMock()
        assistant_msg.parent_message_id = 1  # correct parent

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
# _run_models — drain loop behaviour
# ---------------------------------------------------------------------------


def _make_setup(n_models: int = 1) -> MagicMock:
    """Minimal ChatTurnSetup mock whose fields pass Pydantic validation in _run_model."""
    setup = MagicMock()
    setup.models = []
    for index in range(n_models):
        llm = MagicMock(spec=LLM)
        llm.info.max_input_tokens = 32_000
        llm.redact_error.side_effect = lambda text: text
        setup.models.append(
            PreparedModel(
                llm=llm, message_id=1000 + index, display_name=f"model-{index}"
            )
        )
    setup.incognito_record_mode = None
    setup.cache.exists.return_value = False
    setup.reserved_token_count = 100
    # Fields consumed by SearchToolConfig / CustomToolConfig / FileReaderToolConfig
    # constructors inside _run_model — must be typed correctly for Pydantic.
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
    setup.chat_session_id = uuid4()
    setup.chat_session_project_id = None
    setup.user_message_id = None
    setup.custom_tool_additional_headers = None
    setup.mcp_headers = None
    return setup


def _run_models_collect(setup: MagicMock) -> list:
    """Drive _run_models to completion and return all yielded items."""
    from onyx.chat.process_message import _run_models

    return list(_run_models(setup, MagicMock()))


class TestRunModels:
    """Tests for the _run_models worker-thread drain loop.

    All external dependencies (LLM, DB, tools) are patched out.  Worker threads
    still run but return immediately since agent is mocked.
    """

    def test_n1_overall_stop_from_llm_loop_passes_through(self) -> None:
        """OverallStop emitted by agent is passed through the drain loop unchanged."""

        def emit_stop(**kwargs: Any) -> None:
            kwargs["emitter"].emit(
                Packet(
                    placement=Placement(turn_index=0),
                    obj=OverallStop(stop_reason="complete"),
                )
            )

        with (
            patch_agent("onyx.chat.process_message.ChatAgent", side_effect=emit_stop),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response"),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(_make_setup(n_models=1))

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
                "onyx.chat.process_message.CHAT_HEARTBEAT_INTERVAL_S",
                0.05,
            ),
            patch_agent(
                "onyx.chat.process_message.ChatAgent",
                side_effect=sleep_then_return,
            ),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response"),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(_make_setup(n_models=1))

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
                Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
            )

        with (
            patch_agent("onyx.chat.process_message.ChatAgent", side_effect=emit_one),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response"),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(_make_setup(n_models=1))

        reasoning = [
            p
            for p in packets
            if isinstance(p, Packet) and isinstance(p.obj, ReasoningStart)
        ]
        assert len(reasoning) == 1
        assert reasoning[0].placement.model_index == 0

    def test_n2_each_model_packet_tagged_with_its_index(self) -> None:
        """Multi-model path: packets from model 0 get index=0, model 1 gets index=1."""

        def emit_one(**kwargs: Any) -> None:
            # _model_idx is set by _run_model based on position in setup.models
            emitter = kwargs["emitter"]
            emitter.emit(
                Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
            )

        with (
            patch_agent("onyx.chat.process_message.ChatAgent", side_effect=emit_one),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response"),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(_make_setup(n_models=2))

        reasoning = [
            p
            for p in packets
            if isinstance(p, Packet) and isinstance(p.obj, ReasoningStart)
        ]
        assert len(reasoning) == 2
        indices = {p.placement.model_index for p in reasoning}
        assert indices == {0, 1}

    def test_model_error_yields_streaming_error(self) -> None:
        """An exception inside a worker thread is surfaced as a StreamingError."""

        def always_fail(**_kwargs: Any) -> None:
            raise RuntimeError("intentional test failure")

        with (
            patch("onyx.chat.process_message.save_failed_chat_response"),
            patch_agent("onyx.chat.process_message.ChatAgent", side_effect=always_fail),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response"),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(_make_setup(n_models=1))

        errors = [p for p in packets if isinstance(p, StreamingError)]
        assert len(errors) == 1
        # A generic (non-litellm) worker exception surfaces as UNKNOWN_ERROR
        # with the original message preserved.
        assert errors[0].error_code == "UNKNOWN_ERROR"
        assert "intentional test failure" in errors[0].error

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
            patch("onyx.chat.process_message.save_failed_chat_response"),
            patch_agent("onyx.chat.process_message.ChatAgent", side_effect=overflow),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response"),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(_make_setup(n_models=1))

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
            patch("onyx.chat.process_message.save_failed_chat_response"),
            patch_agent("onyx.chat.process_message.ChatAgent", side_effect=refusal),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response"),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(_make_setup(n_models=1))

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
            if kwargs["llm"] is setup.models[0].llm:
                raise RuntimeError("model 0 failed")
            kwargs["emitter"].emit(
                Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
            )

        with (
            patch("onyx.chat.process_message.save_failed_chat_response"),
            patch_agent(
                "onyx.chat.process_message.ChatAgent",
                side_effect=fail_model_0_succeed_model_1,
            ),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response"),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(setup)

        errors = [p for p in packets if isinstance(p, StreamingError)]
        assert len(errors) == 1

        reasoning = [
            p
            for p in packets
            if isinstance(p, Packet) and isinstance(p.obj, ReasoningStart)
        ]
        assert len(reasoning) == 1
        assert reasoning[0].placement.model_index == 1

    def test_cancellation_yields_user_cancelled_stop(self) -> None:
        """A cached Stop request ends the turn with user_cancelled."""

        def slow_llm(**_kwargs: Any) -> None:
            time.sleep(0.2)  # Outlasts the 50 ms queue-poll interval

        setup = _make_setup(n_models=1)
        setup.cache.exists.return_value = True
        completion_called = threading.Event()

        with (
            patch_agent("onyx.chat.process_message.ChatAgent", side_effect=slow_llm),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.save_chat_response",
                side_effect=lambda *_, **__: completion_called.set(),
            ),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(setup)
            # The cancelled coordinator saves after the reader returns, so
            # wait inside the patch context — otherwise it calls the real handler.
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
                i for i, model in enumerate(setup.models) if model.llm is kwargs["llm"]
            )
            signal = current_cancellation()
            assert signal is not None
            started[index].set()
            try:
                while time.monotonic() < deadline:
                    signal.check()
                    kwargs["emitter"].emit(
                        Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
                    )
                raise AssertionError("Stop did not reach the model worker")
            finally:
                stopped[index].set()

        with (
            patch_agent(
                "onyx.chat.process_message.ChatAgent",
                side_effect=emit_until_cancelled,
            ),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response") as persist,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(setup)
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
        """Stop-button exit yields immediately and persists each model once."""

        def slow_llm(**_kwargs: Any) -> None:
            time.sleep(0.2)

        setup = _make_setup(n_models=2)
        setup.cache.exists.return_value = True
        model_0_persisted = threading.Event()
        model_1_persisted = threading.Event()

        def mark_persisted(*_: Any, **kwargs: Any) -> None:
            if kwargs["message_id"] is setup.models[0].message_id:
                model_0_persisted.set()
            else:
                model_1_persisted.set()

        with (
            patch_agent("onyx.chat.process_message.ChatAgent", side_effect=slow_llm),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.save_chat_response",
                side_effect=mark_persisted,
            ) as mock_handle,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(setup)
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
        assert persisted_messages.count(setup.models[0].message_id) == 1
        assert persisted_messages.count(setup.models[1].message_id) == 1

    def test_completion_handle_called_for_each_successful_model(
        self, mock_compression: MagicMock
    ) -> None:
        """Normal completion persists each successful model once."""
        setup = _make_setup(n_models=2)

        with (
            patch_agent("onyx.chat.process_message.ChatAgent"),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response") as mock_handle,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            _run_models_collect(setup)

        assert mock_handle.call_count == 2
        persisted_messages = [
            call.kwargs["message_id"] for call in mock_handle.call_args_list
        ]
        assert persisted_messages.count(setup.models[0].message_id) == 1
        assert persisted_messages.count(setup.models[1].message_id) == 1
        mock_compression.assert_called_once()

    def test_completion_handle_not_called_for_failed_model(self) -> None:
        """save_chat_response must be skipped for a model that raised."""

        def always_fail(**_kwargs: Any) -> None:
            raise RuntimeError("fail")

        with (
            patch_agent("onyx.chat.process_message.ChatAgent", side_effect=always_fail),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response") as mock_handle,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            _run_models_collect(_make_setup(n_models=1))

        mock_handle.assert_not_called()

    def test_compression_falls_to_first_successful_model_when_model_0_errors(
        self,
        mock_compression: MagicMock,
    ) -> None:
        """Compression ownership goes to the first non-errored completion, not
        a fixed model index — a model-0 failure must not skip compression."""
        setup = _make_setup(n_models=2)

        def fail_model_0(**kwargs: Any) -> None:
            if kwargs["llm"] is setup.models[0].llm:
                raise RuntimeError("fail")

        with (
            patch_agent(
                "onyx.chat.process_message.ChatAgent", side_effect=fail_model_0
            ),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response") as mock_handle,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            _run_models_collect(setup)

        assert mock_handle.call_count == 1
        call = mock_handle.call_args_list[0]
        assert call.kwargs["message_id"] is setup.models[1].message_id
        mock_compression.assert_called_once()
        assert mock_compression.call_args.args[1] is setup.models[1].llm

    def test_http_disconnect_completion_via_generator_exit(self) -> None:
        """Worker-thread completion survives HTTP disconnect."""

        completion_called = threading.Event()
        client_gone = threading.Event()

        def emit_then_block_until_drain(**kwargs: Any) -> None:
            emitter = kwargs["emitter"]
            emitter.emit(
                Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
            )
            client_gone.wait(timeout=5)

        setup = _make_setup(n_models=1)
        setup.cache.exists.return_value = False

        with (
            patch_agent(
                "onyx.chat.process_message.ChatAgent",
                side_effect=emit_then_block_until_drain,
            ),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.save_chat_response",
                side_effect=lambda *_, **__: completion_called.set(),
            ) as mock_handle,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            from onyx.chat.process_message import _run_models

            gen = cast(Generator, _run_models(setup, MagicMock()))
            first = next(gen)
            assert isinstance(first, Packet)
            gen.close()
            client_gone.set()

            assert completion_called.wait(timeout=5), (
                "coordinator must save completion for the successful model"
            )
            assert mock_handle.call_count == 1

    def test_http_disconnect_error_saves_message_once(self) -> None:
        """Disconnecting during an erroring run saves the errored message once."""

        client_gone = threading.Event()

        def emit_then_raise_after_drain(**kwargs: Any) -> None:
            emitter = kwargs["emitter"]
            emitter.emit(
                Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
            )
            client_gone.wait(timeout=5)
            raise RuntimeError("disconnect failure")

        setup = _make_setup(n_models=1)
        setup.cache.exists.return_value = False
        commit_called = threading.Event()
        db_session = MagicMock()
        db_session.get.return_value = MagicMock()
        db_session.commit.side_effect = lambda: commit_called.set()
        session_ctx = MagicMock()
        session_ctx.__enter__.return_value = db_session
        session_ctx.__exit__.return_value = None

        with (
            patch_agent(
                "onyx.chat.process_message.ChatAgent",
                side_effect=emit_then_raise_after_drain,
            ),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response") as mock_handle,
            patch(
                "onyx.db.agent_transcript.get_session_with_current_tenant",
                return_value=session_ctx,
            ) as mock_get_session,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            from onyx.chat.process_message import _run_models

            gen = cast(Generator, _run_models(setup, MagicMock()))
            first = next(gen)
            assert isinstance(first, Packet)
            gen.close()
            client_gone.set()

            assert commit_called.wait(timeout=5)
            mock_handle.assert_not_called()
            assert mock_get_session.call_count == 1
            assert db_session.commit.call_count == 1
            db_session.get.assert_called_once_with(
                ChatMessage,
                setup.models[0].message_id,
            )

    def test_b1_race_disconnect_handler_completes_already_finished_model(self) -> None:
        """A finished worker is not persisted again after a later disconnect."""

        completion_called = threading.Event()

        def emit_and_return_immediately(**kwargs: Any) -> None:
            # Emit one packet so the drain loop has something to yield, then return
            # immediately — no blocking.  The worker will be done in microseconds.
            kwargs["emitter"].emit(
                Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
            )

        setup = _make_setup(n_models=1)
        setup.cache.exists.return_value = False

        with (
            patch_agent(
                "onyx.chat.process_message.ChatAgent",
                side_effect=emit_and_return_immediately,
            ),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.save_chat_response",
                side_effect=lambda *_, **__: completion_called.set(),
            ) as mock_handle,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            from onyx.chat.process_message import _run_models

            gen = cast(Generator, _run_models(setup, MagicMock()))
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
                Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
            )
            if llm is setup.models[1].llm:
                client_gone.wait(timeout=5)

        setup = _make_setup(n_models=2)
        setup.cache.exists.return_value = False
        model_0_persisted = threading.Event()
        model_1_persisted = threading.Event()

        def mark_persisted(*_: Any, **kwargs: Any) -> None:
            if kwargs["message_id"] is setup.models[0].message_id:
                model_0_persisted.set()
            else:
                model_1_persisted.set()

        with (
            patch_agent(
                "onyx.chat.process_message.ChatAgent",
                side_effect=emit_and_maybe_block,
            ),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.save_chat_response",
                side_effect=mark_persisted,
            ) as mock_handle,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            from onyx.chat.process_message import _run_models

            gen = cast(Generator, _run_models(setup, MagicMock()))
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
        assert persisted_messages.count(setup.models[0].message_id) == 1
        assert persisted_messages.count(setup.models[1].message_id) == 1

    def test_disconnect_buffers_full_stream_and_marks_done(self) -> None:
        """After a disconnect the writer keeps buffering to the end and marks done."""

        client_gone = threading.Event()

        def emit_then_block(**kwargs: Any) -> None:
            kwargs["emitter"].emit(
                Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
            )
            client_gone.wait(timeout=5)
            kwargs["emitter"].emit(
                Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
            )

        setup = _make_setup(n_models=1)
        setup.cache.exists.return_value = False
        stream_buffer = MagicMock()
        done_marked = threading.Event()
        stream_buffer.mark_done.side_effect = lambda: done_marked.set()

        with (
            patch_agent(
                "onyx.chat.process_message.ChatAgent",
                side_effect=emit_then_block,
            ),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response"),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            from onyx.chat.process_message import _run_models

            gen = cast(
                Generator,
                _run_models(setup, MagicMock(), stream_buffer=stream_buffer),
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
        assert buffered.count("reasoning_start") == 2

    def test_stop_button_does_not_call_completion_for_errored_model(self) -> None:
        """Stop-button completion skips errored models."""

        def fail_model_0(**kwargs: Any) -> None:
            if kwargs["llm"] is setup.models[0].llm:
                raise RuntimeError("model 0 errored")
            time.sleep(0.2)

        setup = _make_setup(n_models=2)
        setup.cache.exists.return_value = True
        model_1_persisted = threading.Event()

        with (
            patch_agent(
                "onyx.chat.process_message.ChatAgent", side_effect=fail_model_0
            ),
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.save_chat_response",
                side_effect=lambda *_, **__: model_1_persisted.set(),
            ) as mock_handle,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            _run_models_collect(setup)
            assert model_1_persisted.wait(timeout=5)
            assert mock_handle.call_count == 1

        for call in mock_handle.call_args_list:
            assert call.kwargs.get("llm") is not setup.models[0].llm, (
                "save_chat_response must not be called for the errored model"
            )

    def test_external_state_container_used_for_model_zero(self) -> None:
        """When provided, external_state_container is used as state_containers[0]."""
        from onyx.chat.chat_state import ChatStateContainer
        from onyx.chat.process_message import _run_models

        external = ChatStateContainer()
        setup = _make_setup(n_models=1)

        with (
            patch_agent("onyx.chat.process_message.ChatAgent") as mock_llm,
            patch("onyx.chat.process_message.run_deep_research"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.save_chat_response"),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            list(_run_models(setup, MagicMock(), external_state_container=external))

        # The state_container kwarg passed to agent must be the external one
        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs["state_container"] is external


def patch_agent(
    target: str, *, side_effect: Callable[..., Any] | BaseException | None = None
) -> AbstractContextManager[MagicMock]:
    def construct(*args: Any, **kwargs: Any) -> MagicMock:
        if isinstance(side_effect, BaseException):
            raise side_effect
        if side_effect:
            side_effect(*args, **kwargs)
        return MagicMock()

    return patch(target, side_effect=construct)


@pytest.fixture(autouse=True)
def mock_compression() -> Generator[MagicMock, None, None]:
    with (
        patch("onyx.chat.process_message.compress_chat_if_needed") as compress,
        patch("onyx.chat.process_message.load_settings"),
    ):
        yield compress


def test_persistence_failure_reaches_live_and_resumed_readers() -> None:
    from onyx.chat.process_message import _run_models

    setup = _make_setup()
    buffer = MagicMock()
    with (
        patch("onyx.chat.process_message._execute_model"),
        patch(
            "onyx.chat.process_message.save_chat_response",
            side_effect=RuntimeError("database unavailable"),
        ) as save,
    ):
        packets = list(_run_models(setup, MagicMock(), stream_buffer=buffer))

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


@pytest.mark.parametrize("failure_stage", ["submit", "coordinator"])
def test_startup_failure_uses_coordinator_to_finalize_every_reserved_response(
    failure_stage: str,
) -> None:
    from concurrent.futures import Future, ThreadPoolExecutor

    from onyx.chat.process_message import _run_models

    setup = _make_setup(2)
    buffer = MagicMock()
    started = threading.Event()
    exited = threading.Event()
    saved: list[tuple[str, Any]] = []
    original_submit = ThreadPoolExecutor.submit
    original_start = threading.Thread.start
    submissions = 0

    def execute(*args: Any) -> None:
        state, signal = args[3], args[5]
        state.set_answer_tokens("Partial answer")
        started.set()
        try:
            while not signal.cancelled:
                time.sleep(0.001)
            signal.check()
        finally:
            exited.set()

    def submit(executor: ThreadPoolExecutor, *args: Any, **kwargs: Any) -> Future[Any]:
        nonlocal submissions
        submissions += 1
        if failure_stage == "submit" and submissions == 2:
            assert started.wait(2)
            raise RuntimeError("submit failed")
        return original_submit(executor, *args, **kwargs)

    def start(thread: threading.Thread) -> None:
        if failure_stage == "coordinator" and thread.name == "chat-coordinator":
            assert started.wait(2)
            raise RuntimeError("coordinator failed")
        original_start(thread)

    with (
        patch.object(ThreadPoolExecutor, "submit", submit),
        patch.object(threading.Thread, "start", start),
        patch("onyx.chat.process_message._execute_model", side_effect=execute),
        patch(
            "onyx.chat.process_message.save_chat_response",
            side_effect=lambda **kwargs: saved.append(
                ("partial", kwargs["message_id"])
            ),
        ) as save,
        patch(
            "onyx.chat.process_message.save_failed_chat_response",
            side_effect=lambda setup, index, _state, _error: saved.append(
                ("error", setup.models[index].message_id)
            ),
        ) as failure,
        patch(
            "onyx.chat.process_message.chat_error",
            return_value=StreamingError(
                error="Could not start", error_code="START_FAILED"
            ),
        ),
        patch("onyx.chat.process_message.set_processing_status") as fence,
    ):
        packets = list(_run_models(setup, MagicMock(), stream_buffer=buffer))
        assert exited.wait(2)

    assert len(saved) == 2
    assert {message_id for _, message_id in saved} == {
        model.message_id for model in setup.models
    }
    assert save.call_count + failure.call_count == 2
    assert all(call.kwargs["response"].cancelled for call in save.call_args_list)
    assert any(
        isinstance(packet, StreamingError) and packet.error_code == "CHAT_STARTUP_ERROR"
        for packet in packets
    )
    assert not any(
        isinstance(packet, Packet)
        and isinstance(packet.obj, OverallStop)
        and packet.obj.stop_reason == "user_cancelled"
        for packet in packets
    )
    buffer.mark_done.assert_called_once()
    assert fence.call_args.kwargs["value"] is False


def test_disconnect_during_initial_packets_closes_unstarted_reader() -> None:
    from onyx.chat.process_message import _ChatStream, _stream_chat_turn
    from onyx.server.query_and_chat.streaming_models import heartbeat_packet

    setup = _make_setup()
    first = heartbeat_packet()
    setup.initial_packets = [first]
    reader = _ChatStream()
    reader.publish(heartbeat_packet())
    with (
        patch("onyx.chat.process_message.prepare_chat_turn", return_value=setup),
        patch("onyx.chat.process_message.get_session_with_current_tenant"),
        patch("onyx.chat.process_message.StreamBufferWriter"),
        patch("onyx.chat.process_message._run_models", return_value=reader),
    ):
        stream = cast(
            Generator[Any, None, None], _stream_chat_turn(_make_request(), MagicMock())
        )
        assert next(stream) is first
        stream.close()

    reader.publish(heartbeat_packet())
    with pytest.raises(StopIteration):
        next(reader)


def test_stop_cancels_compression_without_saving_responses_twice() -> None:
    from onyx.chat.process_message import _run_models

    setup = _make_setup(2)
    buffer = MagicMock()
    compression_started = threading.Event()
    compression_exited = threading.Event()
    fence_refreshed = threading.Event()
    stop_requested = threading.Event()
    setup.cache.exists.side_effect = lambda _key: stop_requested.is_set()

    def compress(*_args: Any) -> None:
        signal = current_cancellation()
        assert signal is not None
        cancelled = threading.Event()
        try:
            with signal.on_cancel(cancelled.set):
                compression_started.set()
                assert fence_refreshed.wait(2)
                stop_requested.set()
                assert cancelled.wait(2), (
                    "Stop must reach the compression model request"
                )
                signal.check()
        finally:
            compression_exited.set()

    def update_fence(**kwargs: Any) -> None:
        if kwargs["value"] and compression_started.is_set():
            fence_refreshed.set()

    with (
        patch("onyx.chat.process_message._execute_model"),
        patch("onyx.chat.process_message.save_chat_response") as save,
        patch(
            "onyx.chat.process_message.compress_chat_if_needed", side_effect=compress
        ) as compression,
        patch(
            "onyx.chat.process_message.set_processing_status", side_effect=update_fence
        ) as fence,
        patch("onyx.chat.process_message._FENCE_REFRESH_INTERVAL_S", 0.01),
    ):
        packets = list(_run_models(setup, MagicMock(), stream_buffer=buffer))
        assert compression_exited.wait(2)

    compression.assert_called_once()
    assert save.call_count == 2
    assert all(not call.kwargs["response"].cancelled for call in save.call_args_list)
    stops = [
        packet.obj
        for packet in packets
        if isinstance(packet, Packet) and isinstance(packet.obj, OverallStop)
    ]
    assert len(stops) == 1
    assert stops[0].stop_reason == "user_cancelled"
    assert not any(isinstance(packet, StreamingError) for packet in packets)
    buffer.mark_done.assert_called_once()
    assert fence.call_args.kwargs["value"] is False
    assert fence_refreshed.is_set()


@pytest.mark.parametrize(
    "blocked_storage,save_fails",
    [("response", False), ("response", True), ("stream", False)],
)
def test_stop_reaches_other_model_before_blocked_storage_resumes(
    blocked_storage: str,
    save_fails: bool,
) -> None:
    from contextvars import ContextVar

    from onyx.chat.process_message import _run_models
    from onyx.server.query_and_chat.streaming_models import heartbeat_packet

    setup = _make_setup(2)
    buffer = MagicMock()
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
        index, state, emitter, signal = args[2:6]
        state.set_answer_tokens("Partial answer")
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
            and kwargs["message_id"] == setup.models[0].message_id
        ):
            block()
            if save_fails:
                raise RuntimeError("database unavailable")

    if blocked_storage == "stream":
        buffer.append_line.side_effect = lambda _line: block()

    try:
        with (
            patch("onyx.chat.process_message._execute_model", side_effect=execute),
            patch(
                "onyx.chat.process_message.save_chat_response", side_effect=save
            ) as persist,
            patch("onyx.chat.process_message._CANCEL_POLL_INTERVAL_S", 0.01),
        ):
            reader = _run_models(setup, MagicMock(), stream_buffer=buffer)
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
