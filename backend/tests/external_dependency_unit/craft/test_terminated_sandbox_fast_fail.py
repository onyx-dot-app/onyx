"""Cross-replica fast-fail for sandboxes with no live backend.

A fresh ``StubSandboxManager`` (empty local tombstone) stands in for a peer
replica, so bus creation is driven purely off the DB ``Sandbox.status``:
TERMINATED / FAILED / SLEEPING are refused, RUNNING / PROVISIONING proceed.
"""

from __future__ import annotations

from typing import Callable

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.sandbox.opencode.event_bus import PodEventBus
from tests.external_dependency_unit.craft.stubs import StubSandboxManager


class TestTerminatedSandboxFastFail:
    def test_terminal_sandbox_refused_on_peer_replica(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
        sandbox: Callable[..., Sandbox],
    ) -> None:
        # Empty local tombstone (fresh manager); DB status must still refuse.
        row = sandbox(user=test_user, status=SandboxStatus.TERMINATED)
        manager = StubSandboxManager()
        assert row.id not in manager._terminated_sandboxes

        with pytest.raises(RuntimeError, match="no live backend"):
            manager._get_or_create_event_bus(row.id, f"/workspace/sessions/{row.id}")

    def test_failed_sandbox_refused_on_peer_replica(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
        sandbox: Callable[..., Sandbox],
    ) -> None:
        # FAILED is also terminal (SandboxStatus.is_terminal) — same refusal.
        row = sandbox(user=test_user, status=SandboxStatus.FAILED)
        manager = StubSandboxManager()

        with pytest.raises(RuntimeError, match="no live backend"):
            manager._get_or_create_event_bus(row.id, f"/workspace/sessions/{row.id}")

    def test_sleeping_sandbox_refused_on_peer_replica(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
        sandbox: Callable[..., Sandbox],
    ) -> None:
        # SLEEPING = pod torn down (snapshot in S3); backend is gone, so refuse.
        row = sandbox(user=test_user, status=SandboxStatus.SLEEPING)
        manager = StubSandboxManager()

        with pytest.raises(RuntimeError, match="no live backend"):
            manager._get_or_create_event_bus(row.id, f"/workspace/sessions/{row.id}")

    def test_running_sandbox_builds_bus(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
        sandbox: Callable[..., Sandbox],
    ) -> None:
        # RUNNING is healthy — bus creation proceeds.
        row = sandbox(user=test_user, status=SandboxStatus.RUNNING)
        manager = StubSandboxManager()

        bus = manager._get_or_create_event_bus(row.id, f"/workspace/sessions/{row.id}")
        try:
            assert isinstance(bus, PodEventBus)
            assert not bus.closed
        finally:
            bus.close()

    def test_provisioning_sandbox_not_fast_failed(
        self,
        db_session: Session,  # noqa: ARG002
        test_user: User,
        sandbox: Callable[..., Sandbox],
    ) -> None:
        # PROVISIONING is not-yet-ready, not gone — must not be fast-failed.
        row = sandbox(user=test_user, status=SandboxStatus.PROVISIONING)
        manager = StubSandboxManager()

        bus = manager._get_or_create_event_bus(row.id, f"/workspace/sessions/{row.id}")
        try:
            assert isinstance(bus, PodEventBus)
        finally:
            bus.close()
