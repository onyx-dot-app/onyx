from __future__ import annotations

from uuid import UUID
from uuid import uuid4

import pytest

from onyx.db.models import BuildSession
from onyx.server.features.build.session.manager import SessionManager


class _FakeSandboxManager:
    def __init__(self, result: str | None) -> None:
        self.result = result
        self.calls: list[tuple[UUID, UUID, str | None]] = []

    def ensure_opencode_session(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        opencode_session_id: str | None = None,
    ) -> str | None:
        self.calls.append((sandbox_id, session_id, opencode_session_id))
        return self.result


class _FakeDbSession:
    def __init__(self) -> None:
        self.flush_count = 0

    def flush(self) -> None:
        self.flush_count += 1


def _manager(
    sandbox_manager: _FakeSandboxManager, db_session: _FakeDbSession
) -> SessionManager:
    manager = SessionManager.__new__(SessionManager)
    manager._sandbox_manager = sandbox_manager
    manager._db_session = db_session
    return manager


def _build_session(opencode_session_id: str | None = None) -> BuildSession:
    return BuildSession(
        id=uuid4(),
        user_id=uuid4(),
        opencode_session_id=opencode_session_id,
    )


@pytest.mark.parametrize(
    ("initial_id", "resolved_id", "flush_count"),
    [
        pytest.param(None, "opencode-1", 1, id="new-id"),
        pytest.param("stale-opencode", "fresh-opencode", 1, id="stale-id"),
        pytest.param("valid-opencode", "valid-opencode", 0, id="valid-id"),
    ],
)
def test_prewarm_opencode_session_persists_resolved_id(
    initial_id: str | None,
    resolved_id: str,
    flush_count: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Empty session (no assistant messages) — prewarm may mint/replace.
    monkeypatch.setattr(
        "onyx.server.features.build.session.manager.session_has_assistant_messages",
        lambda *_args: False,
    )
    sandbox_id = uuid4()
    session = _build_session(initial_id)
    sandbox_manager = _FakeSandboxManager(resolved_id)
    db_session = _FakeDbSession()

    _manager(sandbox_manager, db_session)._prewarm_opencode_session(sandbox_id, session)

    assert session.opencode_session_id == resolved_id
    assert db_session.flush_count == flush_count
    assert sandbox_manager.calls == [(sandbox_id, session.id, initial_id)]


def test_prewarm_opencode_session_refuses_non_empty_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session with assistant history must keep its persisted opencode id:
    prewarm must not call ensure_opencode_session at all (a 404 there would
    mint a replacement and silently discard the chat history)."""
    monkeypatch.setattr(
        "onyx.server.features.build.session.manager.session_has_assistant_messages",
        lambda *_args: True,
    )
    sandbox_id = uuid4()
    session = _build_session("persisted-opencode")
    sandbox_manager = _FakeSandboxManager("fresh-opencode")
    db_session = _FakeDbSession()

    _manager(sandbox_manager, db_session)._prewarm_opencode_session(sandbox_id, session)

    assert session.opencode_session_id == "persisted-opencode"
    assert db_session.flush_count == 0
    assert sandbox_manager.calls == []


def test_prewarm_opencode_session_raises_when_runtime_returns_no_id() -> None:
    sandbox_id = uuid4()
    session = _build_session()
    sandbox_manager = _FakeSandboxManager(None)
    db_session = _FakeDbSession()

    with pytest.raises(RuntimeError, match="Failed to prewarm opencode session"):
        _manager(sandbox_manager, db_session)._prewarm_opencode_session(
            sandbox_id, session
        )

    assert session.opencode_session_id is None
    assert db_session.flush_count == 0
    assert sandbox_manager.calls == [(sandbox_id, session.id, None)]
