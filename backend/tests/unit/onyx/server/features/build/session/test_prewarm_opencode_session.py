from __future__ import annotations

from uuid import UUID
from uuid import uuid4

import pytest

from onyx.db.models import BuildSession
from onyx.server.features.build.session.manager import SessionManager


class _FakeSandboxManager:
    def __init__(self, result: str | None) -> None:
        self.result = result
        self.calls: list[dict[str, UUID | str | None]] = []

    def ensure_opencode_session(
        self,
        sandbox_id: UUID,
        session_id: UUID,
        opencode_session_id: str | None = None,
    ) -> str | None:
        self.calls.append(
            {
                "sandbox_id": sandbox_id,
                "session_id": session_id,
                "opencode_session_id": opencode_session_id,
            }
        )
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


def test_prewarm_opencode_session_persists_new_session_id() -> None:
    sandbox_id = uuid4()
    session = _build_session()
    sandbox_manager = _FakeSandboxManager("opencode-1")
    db_session = _FakeDbSession()

    _manager(sandbox_manager, db_session)._prewarm_opencode_session(sandbox_id, session)

    assert session.opencode_session_id == "opencode-1"
    assert db_session.flush_count == 1
    assert sandbox_manager.calls == [
        {
            "sandbox_id": sandbox_id,
            "session_id": session.id,
            "opencode_session_id": None,
        }
    ]


def test_prewarm_opencode_session_refreshes_stale_session_id() -> None:
    sandbox_id = uuid4()
    session = _build_session("stale-opencode")
    sandbox_manager = _FakeSandboxManager("fresh-opencode")
    db_session = _FakeDbSession()

    _manager(sandbox_manager, db_session)._prewarm_opencode_session(sandbox_id, session)

    assert session.opencode_session_id == "fresh-opencode"
    assert db_session.flush_count == 1
    assert sandbox_manager.calls == [
        {
            "sandbox_id": sandbox_id,
            "session_id": session.id,
            "opencode_session_id": "stale-opencode",
        }
    ]


def test_prewarm_opencode_session_keeps_valid_session_id_without_flush() -> None:
    sandbox_id = uuid4()
    session = _build_session("valid-opencode")
    sandbox_manager = _FakeSandboxManager("valid-opencode")
    db_session = _FakeDbSession()

    _manager(sandbox_manager, db_session)._prewarm_opencode_session(sandbox_id, session)

    assert session.opencode_session_id == "valid-opencode"
    assert db_session.flush_count == 0


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
