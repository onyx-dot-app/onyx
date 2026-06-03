"""Cross-replica fast-fail for sandboxes with no live backend.

``_ServeMixin._terminated_sandboxes`` is a per-process tombstone: it only
blocks racing subscribes on the replica that ran ``terminate``. A peer replica
has an empty tombstone, so it would happily build a doomed bus against the
deleted backend. The fix consults the authoritative DB ``Sandbox.status`` in
``_get_or_create_event_bus`` so the refusal fires on every replica — for every
state whose pod is gone: ``TERMINATED`` / ``FAILED`` (permanent) and
``SLEEPING`` (pod torn down, snapshot in S3).

These tests use a *fresh* ``StubSandboxManager`` (empty local tombstone) to
stand in for that peer replica, and drive bus creation purely off DB state.
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
        # TERMINATED row in the DB; the peer replica's local tombstone is empty
        # (fresh manager). The DB authority must still force a refusal.
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
        # SLEEPING = pod torn down, snapshot saved to S3. The backend is gone,
        # so a bus built against it is just as doomed as a terminal one and must
        # be refused (it would otherwise burn its full reconnect budget).
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
        # A RUNNING sandbox is healthy — the guard must let bus creation proceed.
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
        # Guard against conflating "not yet ready" with "terminated": a
        # PROVISIONING sandbox lacks a ready backend but is NOT terminal, so it
        # must be allowed to build a bus and proceed toward the readiness wait.
        row = sandbox(user=test_user, status=SandboxStatus.PROVISIONING)
        manager = StubSandboxManager()

        bus = manager._get_or_create_event_bus(row.id, f"/workspace/sessions/{row.id}")
        try:
            assert isinstance(bus, PodEventBus)
        finally:
            bus.close()
