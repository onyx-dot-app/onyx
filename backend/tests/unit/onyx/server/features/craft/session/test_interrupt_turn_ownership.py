from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.interactive_turns.state import (
    TURN_STATUS_SUCCEEDED,
    InteractiveTurnLockError,
    acquire_active_turn_lock,
    create_interactive_turn,
    finish_turn,
)
from onyx.server.features.build.session import manager as manager_module
from onyx.server.features.build.session.interrupt_signal import is_interrupt_requested
from tests.unit.fakes import FakeCache


@pytest.mark.parametrize("targeted", [False, True])
def test_stop_fence_belongs_to_active_turn_and_abort_holds_admission_lock(
    monkeypatch: pytest.MonkeyPatch, targeted: bool
) -> None:
    cache = FakeCache()
    session_id, user_id, sandbox_id = uuid4(), uuid4(), uuid4()
    turn = create_interactive_turn(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
        client_request_id="first",
        prompt="hello",
        turn_index=0,
    )
    sandbox_manager = MagicMock()

    def abort(*args: object) -> None:
        assert args == (sandbox_id, session_id, "opencode-session")
        assert is_interrupt_requested(turn.turn_id, cache)
        with pytest.raises(InteractiveTurnLockError):
            acquire_active_turn_lock(cache, session_id)

    sandbox_manager.abort_opencode_session.side_effect = abort
    monkeypatch.setattr(manager_module, "get_sandbox_manager", lambda: sandbox_manager)
    monkeypatch.setattr(manager_module, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(
        manager_module,
        "get_build_session",
        lambda *_: SimpleNamespace(opencode_session_id="opencode-session"),
    )
    monkeypatch.setattr(
        manager_module,
        "get_sandbox_by_user_id",
        lambda *_: SimpleNamespace(id=sandbox_id, status=SandboxStatus.RUNNING),
    )
    manager = manager_module.SessionManager(cast(Session, MagicMock()))
    assert manager.interrupt_message(
        session_id, user_id, turn.turn_id if targeted else None
    )
    sandbox_manager.abort_opencode_session.assert_called_once()
    finish_turn(cache=cache, turn_id=turn.turn_id, status=TURN_STATUS_SUCCEEDED)
    assert not manager.interrupt_message(session_id, user_id, turn.turn_id)
    sandbox_manager.abort_opencode_session.assert_called_once()
    successor = create_interactive_turn(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
        client_request_id="second",
        prompt="next",
        turn_index=1,
    )
    assert not is_interrupt_requested(successor.turn_id, cache)
    assert not manager.interrupt_message(session_id, user_id, turn.turn_id)
    assert not is_interrupt_requested(successor.turn_id, cache)
    sandbox_manager.abort_opencode_session.assert_called_once()


def test_stop_without_active_turn_never_leaves_a_future_fence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = FakeCache()
    session_id, user_id = uuid4(), uuid4()
    monkeypatch.setattr(manager_module, "get_sandbox_manager", MagicMock())
    monkeypatch.setattr(manager_module, "get_cache_backend", lambda: cache)
    monkeypatch.setattr(
        manager_module,
        "get_build_session",
        lambda *_: SimpleNamespace(opencode_session_id=None),
    )
    manager = manager_module.SessionManager(cast(Session, MagicMock()))
    assert not manager.interrupt_message(session_id, user_id)
    successor = create_interactive_turn(
        cache=cache,
        session_id=session_id,
        user_id=user_id,
        client_request_id="later",
        prompt="hello",
        turn_index=0,
    )
    assert not is_interrupt_requested(successor.turn_id, cache)
