"""Unit tests for multi-model streaming validation and DB helpers.

These are pure unit tests — no real database or LLM calls required.
The validation logic in run_multi_model_stream fires before any external
calls, so we can trigger it with lightweight mocks.
"""

from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from onyx.configs.constants import MessageType
from onyx.db.chat import set_preferred_response
from onyx.llm.override_models import LLMOverride
from onyx.server.query_and_chat.models import SendMessageRequest


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


def _start_stream(req: SendMessageRequest, overrides: list[LLMOverride]) -> None:
    """Advance the generator one step to trigger early validation."""
    from onyx.chat.process_message import run_multi_model_stream

    user = MagicMock()
    user.is_anonymous = False
    user.email = "test@example.com"
    db = MagicMock()

    gen = run_multi_model_stream(req, user, db, overrides)
    # Calling next() executes until the first yield OR raises.
    # Validation errors are raised before any yield.
    next(gen)


# ---------------------------------------------------------------------------
# run_multi_model_stream — validation
# ---------------------------------------------------------------------------


class TestRunMultiModelStreamValidation:
    def test_single_override_raises(self) -> None:
        """Exactly 1 override is not multi-model — must raise."""
        req = _make_request()
        with pytest.raises(ValueError, match="2-3"):
            _start_stream(req, [_make_override()])

    def test_four_overrides_raises(self) -> None:
        """4 overrides exceeds maximum — must raise."""
        req = _make_request()
        with pytest.raises(ValueError, match="2-3"):
            _start_stream(
                req,
                [
                    _make_override("openai", "gpt-4"),
                    _make_override("anthropic", "claude-3"),
                    _make_override("google", "gemini-pro"),
                    _make_override("cohere", "command-r"),
                ],
            )

    def test_zero_overrides_raises(self) -> None:
        """Empty override list raises."""
        req = _make_request()
        with pytest.raises(ValueError, match="2-3"):
            _start_stream(req, [])

    def test_deep_research_raises(self) -> None:
        """deep_research=True is incompatible with multi-model."""
        req = _make_request(deep_research=True)
        with pytest.raises(ValueError, match="not supported"):
            _start_stream(
                req, [_make_override(), _make_override("anthropic", "claude-3")]
            )

    def test_exactly_two_overrides_is_minimum(self) -> None:
        """Boundary: 1 override fails, 2 passes — ensures fence-post is correct."""
        req = _make_request()
        # 1 override must fail
        with pytest.raises(ValueError, match="2-3"):
            _start_stream(req, [_make_override()])
        # 2 overrides must NOT raise ValueError (may raise later due to missing session, that's OK)
        try:
            _start_stream(
                req, [_make_override(), _make_override("anthropic", "claude-3")]
            )
        except ValueError as exc:
            pytest.fail(f"2 overrides should pass validation, got ValueError: {exc}")
        except Exception:
            pass  # Any other error means validation passed


# ---------------------------------------------------------------------------
# set_preferred_response — validation (mocked db)
# ---------------------------------------------------------------------------


class TestSetPreferredResponseValidation:
    def test_user_message_not_found(self) -> None:
        db = MagicMock()
        db.query.return_value.get.return_value = None

        with pytest.raises(ValueError, match="not found"):
            set_preferred_response(
                db, user_message_id=999, preferred_assistant_message_id=1
            )

    def test_wrong_message_type(self) -> None:
        """Cannot set preferred response on a non-USER message."""
        db = MagicMock()
        user_msg = MagicMock()
        user_msg.message_type = MessageType.ASSISTANT  # wrong type

        db.query.return_value.get.return_value = user_msg

        with pytest.raises(ValueError, match="not a user message"):
            set_preferred_response(
                db, user_message_id=1, preferred_assistant_message_id=2
            )

    def test_assistant_message_not_found(self) -> None:
        db = MagicMock()
        user_msg = MagicMock()
        user_msg.message_type = MessageType.USER

        # First call returns user_msg, second call (for assistant) returns None
        db.query.return_value.get.side_effect = [user_msg, None]

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

        db.query.return_value.get.side_effect = [user_msg, assistant_msg]

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

        db.query.return_value.get.side_effect = [user_msg, assistant_msg]

        set_preferred_response(db, user_message_id=1, preferred_assistant_message_id=2)

        assert user_msg.preferred_response_id == 2


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
