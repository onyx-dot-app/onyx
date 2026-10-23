"""Synchronous best-effort abort without a future-turn cancellation fence."""

from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession, Sandbox, User
from onyx.server.features.build.session.manager import SessionManager
from tests.common.craft.stubs import StubSandboxManager


class TestInterruptMessageDirectAbort:
    def test_interrupt_fires_direct_abort_with_opencode_session(
        self,
        db_session: Session,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        build_session_with_user: Callable[..., BuildSession],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        sandbox_row = sandbox(user=test_user, status=SandboxStatus.RUNNING)
        build_session = build_session_with_user(user=test_user)
        build_session.opencode_session_id = "ses_abc123"
        db_session.commit()

        assert session_manager_with_stub.interrupt_message(
            build_session.id, test_user.id
        )

        assert stub_sandbox_manager.abort_calls == [
            (sandbox_row.id, build_session.id, "ses_abc123")
        ]

    def test_interrupt_skips_abort_without_opencode_session(
        self,
        test_user: User,
        sandbox: Callable[..., Sandbox],
        build_session_with_user: Callable[..., BuildSession],
        session_manager_with_stub: SessionManager,
        stub_sandbox_manager: StubSandboxManager,
    ) -> None:
        sandbox(user=test_user, status=SandboxStatus.RUNNING)
        build_session = build_session_with_user(user=test_user)
        assert build_session.opencode_session_id is None

        assert not session_manager_with_stub.interrupt_message(
            build_session.id, test_user.id
        )
        assert stub_sandbox_manager.abort_calls == []
