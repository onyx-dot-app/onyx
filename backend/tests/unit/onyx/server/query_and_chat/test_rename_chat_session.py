"""Tests for rename_chat_session (#8330).

Verifies the auto-name LLM is resolved from the chat session's own model
selection rather than always defaulting to the global default LLM, which
previously caused model swaps on VRAM-constrained self-hosted GPU setups.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest

from onyx.llm.override_models import LLMOverride


def _build_chat_session(
    llm_override: LLMOverride | None = None,
    current_alternate_model: str | None = None,
) -> MagicMock:
    """Return a MagicMock standing in for a ChatSession DB row."""
    session = MagicMock()
    session.llm_override = llm_override
    session.current_alternate_model = current_alternate_model
    session.persona = MagicMock()
    return session


@pytest.fixture
def patched_rename_deps() -> Any:
    """Patch every collaborator of rename_chat_session.

    Yields a dict of the active patch objects so tests can set return values
    and assert call arguments without repeating the boilerplate.
    """
    with (
        patch(
            "onyx.server.query_and_chat.chat_backend.get_chat_session_by_id"
        ) as mock_get_session,
        patch(
            "onyx.server.query_and_chat.chat_backend.get_llm_for_persona"
        ) as mock_get_llm_for_persona,
        patch(
            "onyx.server.query_and_chat.chat_backend.get_default_llm"
        ) as mock_get_default_llm,
        patch(
            "onyx.server.query_and_chat.chat_backend.check_llm_cost_limit_for_provider"
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.create_chat_history_chain",
            return_value=[],
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.convert_chat_history_basic",
            return_value=[],
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_llm_token_counter",
            return_value=lambda _s: 0,
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.generate_chat_session_name",
            return_value="Named!",
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.update_chat_session"
        ) as mock_update,
        patch("onyx.server.query_and_chat.chat_backend.ensure_trace"),
        patch(
            "onyx.server.query_and_chat.chat_backend.get_current_tenant_id",
            return_value="tenant",
        ),
        patch(
            "onyx.server.query_and_chat.chat_backend.extract_headers",
            return_value={},
        ),
    ):
        llm = MagicMock()
        llm.config.api_key = "k"
        mock_get_llm_for_persona.return_value = llm
        mock_get_default_llm.return_value = llm

        yield {
            "get_session": mock_get_session,
            "get_llm_for_persona": mock_get_llm_for_persona,
            "get_default_llm": mock_get_default_llm,
            "update": mock_update,
        }


def _call_rename(
    name: str | None = None,
) -> Any:
    """Invoke rename_chat_session with a minimal fake request + user."""
    from onyx.server.query_and_chat.chat_backend import rename_chat_session
    from onyx.server.query_and_chat.models import ChatRenameRequest

    rename_req = ChatRenameRequest(chat_session_id=uuid4(), name=name)
    request = MagicMock()
    request.headers = {}
    user = MagicMock()
    user.id = uuid4()
    db_session = MagicMock()

    return rename_chat_session(rename_req, request, user, db_session)


def test_rename_uses_session_llm_override_when_set(patched_rename_deps: Any) -> None:
    override = LLMOverride(model_provider="openai", model_version="gpt-4o")
    patched_rename_deps["get_session"].return_value = _build_chat_session(
        llm_override=override
    )

    _call_rename(name=None)

    patched_rename_deps["get_llm_for_persona"].assert_called_once()
    kwargs = patched_rename_deps["get_llm_for_persona"].call_args.kwargs
    assert kwargs["llm_override"] is override


def test_rename_uses_current_alternate_model_when_llm_override_none(
    patched_rename_deps: Any,
) -> None:
    patched_rename_deps["get_session"].return_value = _build_chat_session(
        llm_override=None, current_alternate_model="nemotron-3-nano"
    )

    _call_rename(name=None)

    kwargs = patched_rename_deps["get_llm_for_persona"].call_args.kwargs
    override = kwargs["llm_override"]
    assert isinstance(override, LLMOverride)
    assert override.model_version == "nemotron-3-nano"
    assert override.model_provider is None


def test_rename_llm_override_wins_over_alternate_model(
    patched_rename_deps: Any,
) -> None:
    override = LLMOverride(model_provider="openai", model_version="gpt-4o")
    patched_rename_deps["get_session"].return_value = _build_chat_session(
        llm_override=override, current_alternate_model="nemotron-3-nano"
    )

    _call_rename(name=None)

    kwargs = patched_rename_deps["get_llm_for_persona"].call_args.kwargs
    assert kwargs["llm_override"] is override


def test_rename_falls_back_to_persona_defaults_when_neither_set(
    patched_rename_deps: Any,
) -> None:
    patched_rename_deps["get_session"].return_value = _build_chat_session(
        llm_override=None, current_alternate_model=None
    )

    _call_rename(name=None)

    patched_rename_deps["get_llm_for_persona"].assert_called_once()
    kwargs = patched_rename_deps["get_llm_for_persona"].call_args.kwargs
    assert kwargs["llm_override"] is None
    patched_rename_deps["get_default_llm"].assert_not_called()


def test_rename_falls_back_to_default_llm_when_get_llm_for_persona_raises(
    patched_rename_deps: Any,
) -> None:
    patched_rename_deps["get_session"].return_value = _build_chat_session()
    patched_rename_deps["get_llm_for_persona"].side_effect = ValueError(
        "No model name found"
    )

    _call_rename(name=None)

    patched_rename_deps["get_default_llm"].assert_called_once()
    patched_rename_deps["update"].assert_called()


def test_rename_does_not_call_default_llm_on_happy_path(
    patched_rename_deps: Any,
) -> None:
    """Regression: the bug was rename always hitting get_default_llm."""
    patched_rename_deps["get_session"].return_value = _build_chat_session(
        llm_override=LLMOverride(model_version="gpt-4o")
    )

    _call_rename(name=None)

    patched_rename_deps["get_default_llm"].assert_not_called()


def test_rename_with_explicit_name_skips_llm_resolution(
    patched_rename_deps: Any,
) -> None:
    """When the user passes a name, rename is a plain DB update — no LLM."""
    response = _call_rename(name="My chat")

    patched_rename_deps["get_session"].assert_not_called()
    patched_rename_deps["get_llm_for_persona"].assert_not_called()
    patched_rename_deps["get_default_llm"].assert_not_called()
    assert response.new_name == "My chat"
