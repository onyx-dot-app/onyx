"""State-machine coverage for ``SessionManager.ensure_sandbox_running``.

The headless entry point (``manager.py:ensure_sandbox_running``) delegates to
``ensure_sandbox_ready`` (``sandbox_lifecycle.py:197``) under the ``POLL``
provisioning policy. These tests drive the public ``SessionManager`` API
against the real Postgres DB (via ``db_session``) and the in-memory
``StubSandboxManager``, exercising every branch of the state machine:

* No sandbox row -> create + provision.
* ``RUNNING`` + pod healthy -> return as-is (hot path; no provision/terminate).
* ``RUNNING`` + pod unhealthy -> terminate + re-provision.
* ``SLEEPING`` / ``TERMINATED`` / ``FAILED`` -> re-provision in place.
* ``PROVISIONING`` that flips RUNNING mid-wait -> return RUNNING, no provision.
* ``PROVISIONING`` with a 0s wait window -> ``SandboxProvisioningError``.

No real cluster is touched; the stub raises loudly for any unconfigured
manager method, so each test must declare the slice of the manager it uses.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.session.errors import SandboxProvisioningError
from onyx.server.features.build.session.manager import SessionManager
from tests.common.craft.stubs import StubSandboxManager


def _running_info(sandbox_id: UUID) -> SandboxInfo:
    """A ``provision``-style ``SandboxInfo`` that lands the row at RUNNING."""
    return SandboxInfo(
        sandbox_id=sandbox_id,
        directory_path="/tmp/sandbox",
        status=SandboxStatus.RUNNING,
        last_heartbeat=None,
    )


def test_creates_sandbox_when_none_exists(
    db_session: Session,
    test_user: User,
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    """No sandbox row -> a row is created and provisioned to RUNNING."""
    stub_sandbox_manager.provision_returns = _running_info(uuid4())

    result = session_manager_with_stub.ensure_sandbox_running(test_user.id)
    db_session.commit()

    assert result.user_id == test_user.id
    assert result.status == SandboxStatus.RUNNING
    assert stub_sandbox_manager.provision_count == 1
    # Exactly one row now exists for the user.
    rows = db_session.query(Sandbox).filter(Sandbox.user_id == test_user.id).all()
    assert len(rows) == 1
    assert rows[0].id == result.id


def test_running_and_healthy_returns_as_is(
    test_user: User,
    sandbox: Callable[..., Sandbox],
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    """RUNNING + ``health_check`` True -> returned untouched (no provision/terminate)."""
    existing = sandbox(user=test_user, status=SandboxStatus.RUNNING)
    stub_sandbox_manager.health_check_returns = True
    # ``provision_returns``/``terminate_silent`` left unset: the stub raises
    # if either is invoked, which would fail this test.

    result = session_manager_with_stub.ensure_sandbox_running(test_user.id)

    assert result.id == existing.id
    assert result.status == SandboxStatus.RUNNING
    assert stub_sandbox_manager.provision_count == 0
    assert stub_sandbox_manager.terminate_count == 0


def test_running_but_unhealthy_recovers_via_terminate_then_provision(
    db_session: Session,
    test_user: User,
    sandbox: Callable[..., Sandbox],
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    """RUNNING in DB but pod unhealthy -> terminate + re-provision back to RUNNING."""
    existing = sandbox(user=test_user, status=SandboxStatus.RUNNING)
    stub_sandbox_manager.health_check_returns = False
    stub_sandbox_manager.terminate_silent = True
    stub_sandbox_manager.provision_returns = _running_info(existing.id)

    result = session_manager_with_stub.ensure_sandbox_running(test_user.id)
    db_session.commit()

    assert result.id == existing.id
    assert result.status == SandboxStatus.RUNNING
    assert stub_sandbox_manager.terminate_count == 1
    assert stub_sandbox_manager.last_terminate_sandbox_id == existing.id
    assert stub_sandbox_manager.provision_count == 1


@pytest.mark.parametrize(
    "initial_status",
    [
        SandboxStatus.SLEEPING,
        SandboxStatus.TERMINATED,
        SandboxStatus.FAILED,
    ],
)
def test_wakes_dormant_sandbox(
    db_session: Session,
    test_user: User,
    sandbox: Callable[..., Sandbox],
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
    initial_status: SandboxStatus,
) -> None:
    """SLEEPING / TERMINATED / FAILED -> re-provision the existing row in place."""
    existing = sandbox(user=test_user, status=initial_status)
    stub_sandbox_manager.provision_returns = _running_info(existing.id)

    result = session_manager_with_stub.ensure_sandbox_running(test_user.id)
    db_session.commit()

    assert result.id == existing.id
    assert result.status == SandboxStatus.RUNNING
    assert stub_sandbox_manager.provision_count == 1
    # No health_check on the wake path: the row was never RUNNING.
    assert stub_sandbox_manager.health_check_count == 0


def test_provisioning_transitions_to_running_during_wait(
    db_session: Session,
    test_user: User,
    sandbox: Callable[..., Sandbox],
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent provisioner finishes mid-wait: re-enter the state machine on
    the new RUNNING status and return it without provisioning ourselves."""
    existing = sandbox(user=test_user, status=SandboxStatus.PROVISIONING)

    # Simulate the "other" provisioner finishing: the poll loop's first
    # ``time.sleep`` flips the row to RUNNING and commits so the next
    # ``db_session.refresh`` sees the transition.
    flipped: list[bool] = [False]

    def _flipping_sleep(_seconds: float) -> None:
        if flipped[0]:
            return
        flipped[0] = True
        existing.status = SandboxStatus.RUNNING
        db_session.commit()

    monkeypatch.setattr(
        "onyx.server.features.build.session.sandbox_lifecycle.time.sleep",
        _flipping_sleep,
    )

    # After the wait, the row is RUNNING and the hot path health-checks it.
    stub_sandbox_manager.health_check_returns = True

    result = session_manager_with_stub.ensure_sandbox_running(
        test_user.id,
        provisioning_wait_seconds=10.0,
    )

    assert result.id == existing.id
    assert result.status == SandboxStatus.RUNNING
    # We must NOT provision ourselves — the concurrent provisioner owned it.
    assert stub_sandbox_manager.provision_count == 0


def test_provisioning_times_out_raises(
    db_session: Session,
    test_user: User,
    sandbox: Callable[..., Sandbox],
    stub_sandbox_manager: StubSandboxManager,
    session_manager_with_stub: SessionManager,
) -> None:
    """Stuck PROVISIONING + 0s wait -> ``SandboxProvisioningError`` without provisioning.

    This is the deterministic-timeout contract that
    ``test_scheduled_task_executor.py::test_run_fails_when_wake_fails`` relies on.
    """
    existing = sandbox(user=test_user, status=SandboxStatus.PROVISIONING)

    with pytest.raises(SandboxProvisioningError):
        session_manager_with_stub.ensure_sandbox_running(
            test_user.id,
            provisioning_wait_seconds=0.0,
        )

    assert stub_sandbox_manager.provision_count == 0
    # Row is untouched: still PROVISIONING.
    db_session.expire_all()
    refreshed = get_sandbox_by_user_id(db_session, test_user.id)
    assert refreshed is not None
    assert refreshed.id == existing.id
    assert refreshed.status == SandboxStatus.PROVISIONING
