"""Interrupt-triggered direct abort of the in-flight opencode session.

``SessionManager.interrupt_message`` always sets the interrupt fence, and
additionally spawns a best-effort daemon thread that calls
``abort_opencode_session`` when the session has a live opencode session and
an active sandbox. These tests verify the abort fires (and with what args)
only when both conditions hold.
"""

from __future__ import annotations

import time
from typing import Callable

from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.session.manager import SessionManager
from tests.common.craft.stubs import StubSandboxManager

_POLL_TIMEOUT_SECONDS = 2.0
_POLL_INTERVAL_SECONDS = 0.05


def _wait_for_abort_calls(stub: StubSandboxManager) -> None:
    deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline and not stub.abort_calls:
        time.sleep(_POLL_INTERVAL_SECONDS)


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

        _wait_for_abort_calls(stub_sandbox_manager)
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

        assert session_manager_with_stub.interrupt_message(
            build_session.id, test_user.id
        )

        time.sleep(_POLL_INTERVAL_SECONDS * 4)
        assert stub_sandbox_manager.abort_calls == []
