"""Locks the ``expect_existing_opencode_session`` wiring in
``streaming.yield_sandbox_events``.

The flag is what makes history loss loud (OpencodeSessionLostError) instead
of silently minting a fresh opencode session — it must be set exactly when
(a) the backend persists the opencode store across re-provisions, (b) a
session id was persisted, and (c) the agent has already responded.
"""

from __future__ import annotations

from typing import Any
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session as DBSession

from onyx.server.features.build.session import streaming
from tests.common.craft.stubs import StubSandboxManager


def _drive(
    stub: StubSandboxManager,
    *,
    opencode_session_id: str | None,
) -> dict[str, Any]:
    stub.send_message_events = []
    list(
        streaming.yield_sandbox_events(
            # The db session only reaches the monkeypatched history helper.
            cast(DBSession, object()),
            stub,
            uuid4(),
            uuid4(),
            "hello",
            opencode_session_id=opencode_session_id,
            agent_provider=None,
            agent_model=None,
        )
    )
    assert stub.last_send_message_payload is not None
    return stub.last_send_message_payload


@pytest.mark.parametrize(
    ("has_assistant_messages", "opencode_session_id", "expected"),
    [
        pytest.param(True, "ses_persisted", True, id="history-present"),
        pytest.param(False, "ses_persisted", False, id="no-assistant-messages"),
        pytest.param(True, None, False, id="no-persisted-id"),
    ],
)
def test_expect_existing_set_from_history_and_persisted_id(
    has_assistant_messages: bool,
    opencode_session_id: str | None,
    expected: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        streaming,
        "session_has_assistant_messages",
        lambda *_args: has_assistant_messages,
    )
    stub = StubSandboxManager()

    payload = _drive(stub, opencode_session_id=opencode_session_id)

    assert payload["expect_existing_opencode_session"] is expected


def test_session_lost_error_clears_persisted_id_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """History loss is loud once, then recoverable: the turn fails with
    OpencodeSessionLostError, and the dangling id is cleared so the next
    turn mints a fresh opencode session instead of erroring forever."""
    from onyx.server.features.build.sandbox.opencode.serve_client import (
        OpencodeSessionLostError,
    )

    monkeypatch.setattr(
        streaming, "session_has_assistant_messages", lambda *_args: True
    )
    cleared: list[Any] = []
    monkeypatch.setattr(
        streaming,
        "_clear_opencode_session_id",
        lambda _db, sid: cleared.append(sid),
    )
    stub = StubSandboxManager()

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise OpencodeSessionLostError("history lost")
        yield  # makes this a generator function

    monkeypatch.setattr(stub, "send_message", _raise)

    session_id = uuid4()
    with pytest.raises(OpencodeSessionLostError):
        list(
            streaming.yield_sandbox_events(
                cast(DBSession, object()),
                stub,
                uuid4(),
                session_id,
                "hello",
                opencode_session_id="ses_persisted",
                agent_provider=None,
                agent_model=None,
            )
        )
    assert cleared == [session_id]


def test_expect_existing_false_without_history_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backends that don't restore the opencode store (Docker) must keep the
    silent mint-a-fresh-session behavior — a stale id after sleep is
    expected there, and a hard error would permanently brick the session."""
    helper_calls: list[object] = []
    monkeypatch.setattr(
        streaming,
        "session_has_assistant_messages",
        lambda *args: helper_calls.append(args) or True,
    )
    stub = StubSandboxManager()
    stub.supports_opencode_history_persistence = False

    payload = _drive(stub, opencode_session_id="ses_persisted")

    assert payload["expect_existing_opencode_session"] is False
    # Capability short-circuits before the DB is consulted.
    assert helper_calls == []
