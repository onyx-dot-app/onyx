"""Unit tests for multi-model streaming validation and DB helpers.

These are pure unit tests — no real database or LLM calls required.
The validation logic in handle_multi_model_stream fires before any external
calls, so we can trigger it with lightweight mocks.
"""

import threading
import time
from collections.abc import Generator
from typing import Any
from typing import cast
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from litellm.exceptions import ContextWindowExceededError

from onyx.chat.models import StreamingError
from onyx.configs.constants import MessageType
from onyx.db.chat import set_preferred_response
from onyx.db.models import ChatMessage
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import SendMessageRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import ChatHeartbeat
from onyx.server.query_and_chat.streaming_models import OverallStop
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import ReasoningStart
from onyx.utils.variable_functionality import global_version


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
    setup.llms = [MagicMock() for _ in range(n_models)]
    setup.model_display_names = [f"model-{i}" for i in range(n_models)]
    setup.check_is_connected = MagicMock(return_value=True)
    setup.reserved_messages = [MagicMock() for _ in range(n_models)]
    setup.reserved_token_count = 100
    # Fields consumed by SearchToolConfig / CustomToolConfig / FileReaderToolConfig
    # constructors inside _run_model — must be typed correctly for Pydantic.
    setup.new_msg_req.deep_research = False
    setup.new_msg_req.internal_search_filters = None
    setup.new_msg_req.allowed_tool_ids = None
    setup.new_msg_req.include_citations = True
    setup.search_params.project_id_filter = None
    setup.search_params.persona_id_filter = None
    setup.bypass_acl = False
    setup.slack_context = None
    setup.available_files.user_file_ids = []
    setup.available_files.chat_file_ids = []
    setup.forced_tool_id = None
    setup.simple_chat_history = []
    setup.chat_session.id = uuid4()
    setup.user_message.id = None
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
    still run but return immediately since run_llm_loop is mocked.
    """

    def test_n1_overall_stop_from_llm_loop_passes_through(self) -> None:
        """OverallStop emitted by run_llm_loop is passed through the drain loop unchanged."""

        def emit_stop(**kwargs: Any) -> None:
            kwargs["emitter"].emit(
                Packet(
                    placement=Placement(turn_index=0),
                    obj=OverallStop(stop_reason="complete"),
                )
            )

        with (
            patch("onyx.chat.process_message.run_llm_loop", side_effect=emit_stop),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.llm_loop_completion_handle"),
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
            patch(
                "onyx.chat.process_message.run_llm_loop",
                side_effect=sleep_then_return,
            ),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.llm_loop_completion_handle"),
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
            patch("onyx.chat.process_message.run_llm_loop", side_effect=emit_one),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.llm_loop_completion_handle"),
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
            # _model_idx is set by _run_model based on position in setup.llms
            emitter = kwargs["emitter"]
            emitter.emit(
                Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
            )

        with (
            patch("onyx.chat.process_message.run_llm_loop", side_effect=emit_one),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.llm_loop_completion_handle"),
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
            patch("onyx.chat.process_message.run_llm_loop", side_effect=always_fail),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.llm_loop_completion_handle"),
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
            patch("onyx.chat.process_message.run_llm_loop", side_effect=overflow),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.llm_loop_completion_handle"),
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

    def test_one_model_error_does_not_stop_other_models(self) -> None:
        """A failing model yields StreamingError; the surviving model's packets still arrive."""
        setup = _make_setup(n_models=2)

        def fail_model_0_succeed_model_1(**kwargs: Any) -> None:
            if kwargs["llm"] is setup.llms[0]:
                raise RuntimeError("model 0 failed")
            kwargs["emitter"].emit(
                Packet(placement=Placement(turn_index=0), obj=ReasoningStart())
            )

        with (
            patch(
                "onyx.chat.process_message.run_llm_loop",
                side_effect=fail_model_0_succeed_model_1,
            ),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.llm_loop_completion_handle"),
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
        """If check_is_connected returns False, drain loop emits user_cancelled."""

        def slow_llm(**_kwargs: Any) -> None:
            time.sleep(0.2)  # Outlasts the 50 ms queue-poll interval

        setup = _make_setup(n_models=1)
        setup.check_is_connected = MagicMock(return_value=False)
        completion_called = threading.Event()

        with (
            patch("onyx.chat.process_message.run_llm_loop", side_effect=slow_llm),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.llm_loop_completion_handle",
                side_effect=lambda *_, **__: completion_called.set(),
            ),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            packets = _run_models_collect(setup)
            # The cancelled worker self-persists after the generator returns, so
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

    def test_stop_button_calls_completion_for_all_models(self) -> None:
        """Stop-button exit yields immediately and persists each model once."""

        def slow_llm(**_kwargs: Any) -> None:
            time.sleep(0.2)

        setup = _make_setup(n_models=2)
        setup.check_is_connected = MagicMock(return_value=False)
        model_0_persisted = threading.Event()
        model_1_persisted = threading.Event()

        def mark_persisted(*_: Any, **kwargs: Any) -> None:
            if kwargs["llm"] is setup.llms[0]:
                model_0_persisted.set()
            else:
                model_1_persisted.set()

        with (
            patch("onyx.chat.process_message.run_llm_loop", side_effect=slow_llm),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.llm_loop_completion_handle",
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
        persisted_llms = [call.kwargs["llm"] for call in mock_handle.call_args_list]
        assert persisted_llms.count(setup.llms[0]) == 1
        assert persisted_llms.count(setup.llms[1]) == 1

    def test_completion_handle_called_for_each_successful_model(self) -> None:
        """Normal completion persists each successful model once."""
        setup = _make_setup(n_models=2)

        with (
            patch("onyx.chat.process_message.run_llm_loop"),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.llm_loop_completion_handle"
            ) as mock_handle,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            _run_models_collect(setup)

        assert mock_handle.call_count == 2
        persisted_llms = [call.kwargs["llm"] for call in mock_handle.call_args_list]
        assert persisted_llms.count(setup.llms[0]) == 1
        assert persisted_llms.count(setup.llms[1]) == 1

    def test_completion_handle_not_called_for_failed_model(self) -> None:
        """llm_loop_completion_handle must be skipped for a model that raised."""

        def always_fail(**_kwargs: Any) -> None:
            raise RuntimeError("fail")

        with (
            patch("onyx.chat.process_message.run_llm_loop", side_effect=always_fail),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.llm_loop_completion_handle"
            ) as mock_handle,
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            _run_models_collect(_make_setup(n_models=1))

        mock_handle.assert_not_called()

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
        setup.check_is_connected = MagicMock(return_value=True)

        with (
            patch(
                "onyx.chat.process_message.run_llm_loop",
                side_effect=emit_then_block_until_drain,
            ),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.llm_loop_completion_handle",
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
                "worker thread must call completion for the successful model"
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
        setup.check_is_connected = MagicMock(return_value=True)
        commit_called = threading.Event()
        db_session = MagicMock()
        db_session.get.return_value = MagicMock()
        db_session.commit.side_effect = lambda: commit_called.set()
        session_ctx = MagicMock()
        session_ctx.__enter__.return_value = db_session
        session_ctx.__exit__.return_value = None

        with (
            patch(
                "onyx.chat.process_message.run_llm_loop",
                side_effect=emit_then_raise_after_drain,
            ),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.llm_loop_completion_handle"
            ) as mock_handle,
            patch(
                "onyx.chat.process_message.get_session_with_current_tenant",
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
                setup.reserved_messages[0].id,
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
        setup.check_is_connected = MagicMock(return_value=True)

        with (
            patch(
                "onyx.chat.process_message.run_llm_loop",
                side_effect=emit_and_return_immediately,
            ),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.llm_loop_completion_handle",
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
            if llm is setup.llms[1]:
                client_gone.wait(timeout=5)

        setup = _make_setup(n_models=2)
        setup.check_is_connected = MagicMock(return_value=True)
        model_0_persisted = threading.Event()
        model_1_persisted = threading.Event()

        def mark_persisted(*_: Any, **kwargs: Any) -> None:
            if kwargs["llm"] is setup.llms[0]:
                model_0_persisted.set()
            else:
                model_1_persisted.set()

        with (
            patch(
                "onyx.chat.process_message.run_llm_loop",
                side_effect=emit_and_maybe_block,
            ),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.llm_loop_completion_handle",
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
        persisted_llms = [call.kwargs["llm"] for call in mock_handle.call_args_list]
        assert persisted_llms.count(setup.llms[0]) == 1
        assert persisted_llms.count(setup.llms[1]) == 1

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
        setup.check_is_connected = MagicMock(return_value=True)
        stream_buffer = MagicMock()
        done_marked = threading.Event()
        stream_buffer.mark_done.side_effect = lambda: done_marked.set()

        with (
            patch(
                "onyx.chat.process_message.run_llm_loop",
                side_effect=emit_then_block,
            ),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.llm_loop_completion_handle"),
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
            if kwargs["llm"] is setup.llms[0]:
                raise RuntimeError("model 0 errored")
            time.sleep(0.2)

        setup = _make_setup(n_models=2)
        setup.check_is_connected = lambda: False
        model_1_persisted = threading.Event()

        with (
            patch("onyx.chat.process_message.run_llm_loop", side_effect=fail_model_0),
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch(
                "onyx.chat.process_message.llm_loop_completion_handle",
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
            assert call.kwargs.get("llm") is not setup.llms[0], (
                "llm_loop_completion_handle must not be called for the errored model"
            )

    def test_external_state_container_used_for_model_zero(self) -> None:
        """When provided, external_state_container is used as state_containers[0]."""
        from onyx.chat.chat_state import ChatStateContainer
        from onyx.chat.process_message import _run_models

        external = ChatStateContainer()
        setup = _make_setup(n_models=1)

        with (
            patch("onyx.chat.process_message.run_llm_loop") as mock_llm,
            patch("onyx.chat.process_message.run_deep_research_llm_loop"),
            patch("onyx.chat.process_message.construct_tools", return_value={}),
            patch("onyx.chat.process_message.llm_loop_completion_handle"),
            patch(
                "onyx.chat.process_message.get_llm_token_counter",
                return_value=lambda _: 0,
            ),
        ):
            list(_run_models(setup, MagicMock(), external_state_container=external))

        # The state_container kwarg passed to run_llm_loop must be the external one
        call_kwargs = mock_llm.call_args.kwargs
        assert call_kwargs["state_container"] is external
