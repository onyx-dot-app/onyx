"""External-dependency unit tests for SessionManager.ensure_sandbox_running.

Exercises the headless sandbox state machine: creating a fresh sandbox
row, waking SLEEPING / TERMINATED / FAILED, recovering a RUNNING-but-
unhealthy pod, and polling a PROVISIONING sandbox to completion (or
timeout).

Uses the real Postgres DB (via the ``db_session`` fixture) but mocks
``SandboxManager`` because real pod provisioning isn't available in this
test tier. ``_get_llm_config`` is also stubbed since the wake state
machine forwards the config opaquely to ``provision()`` and the test
DB doesn't seed a default LLM provider.
"""

from unittest.mock import MagicMock
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.db.sandbox import create_sandbox__no_commit
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.sandbox.models import SandboxInfo
from onyx.server.features.build.session.manager import SandboxProvisioningError
from onyx.server.features.build.session.manager import SessionManager


def _make_mock_sandbox_manager(*, healthy: bool = True) -> MagicMock:
    """Build a SandboxManager test double.

    ``provision()`` returns ``SandboxInfo(status=RUNNING)`` so the post-
    provision DB update (``update_sandbox_status__no_commit``) lands the
    row in RUNNING — matching real LocalSandboxManager behavior.
    ``health_check()`` returns ``healthy``; ``terminate()`` is a no-op.
    """
    mgr = MagicMock()

    def _provision(sandbox_id: UUID, **_kwargs: object) -> SandboxInfo:
        return SandboxInfo(
            sandbox_id=sandbox_id,
            directory_path=f"/tmp/{sandbox_id}",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )

    mgr.provision.side_effect = _provision
    mgr.health_check.return_value = healthy
    mgr.terminate.return_value = None
    return mgr


def _make_session_manager(
    db_session: Session,
    *,
    sandbox_manager: MagicMock,
) -> SessionManager:
    """Construct a SessionManager wired to a mock SandboxManager + stub LLM.

    Bypasses ``_get_llm_config`` because the wake state machine only
    forwards the config to ``provision()`` (which we mock).
    """
    sm = SessionManager(db_session)
    sm._sandbox_manager = sandbox_manager

    stub_config = LLMProviderConfig(
        provider="test",
        model_name="test-model",
        api_key="test-key",
        api_base=None,
    )
    # Use setattr so static type-checkers don't flag the method override.
    setattr(sm, "_get_llm_config", lambda *_args, **_kwargs: stub_config)
    return sm


def _seed_sandbox(
    db_session: Session,
    user: User,
    status: SandboxStatus,
) -> Sandbox:
    sandbox = create_sandbox__no_commit(db_session=db_session, user_id=user.id)
    update_sandbox_status__no_commit(db_session, sandbox.id, status)
    db_session.commit()
    db_session.refresh(sandbox)
    return sandbox


class TestEnsureSandboxRunning:
    """State-machine coverage for ``SessionManager.ensure_sandbox_running``."""

    def test_creates_sandbox_when_none_exists(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        """No sandbox row → row is created and provisioned."""
        mgr = _make_mock_sandbox_manager()
        session_manager = _make_session_manager(db_session, sandbox_manager=mgr)

        sandbox = session_manager.ensure_sandbox_running(test_user.id)
        db_session.commit()

        assert sandbox.user_id == test_user.id
        assert sandbox.status == SandboxStatus.RUNNING
        mgr.provision.assert_called_once()
        mgr.health_check.assert_not_called()
        mgr.terminate.assert_not_called()

    def test_running_and_healthy_returns_as_is(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        """RUNNING + health_check=True → no re-provision, no terminate."""
        existing = _seed_sandbox(db_session, test_user, SandboxStatus.RUNNING)
        mgr = _make_mock_sandbox_manager(healthy=True)
        session_manager = _make_session_manager(db_session, sandbox_manager=mgr)

        sandbox = session_manager.ensure_sandbox_running(test_user.id)

        assert sandbox.id == existing.id
        assert sandbox.status == SandboxStatus.RUNNING
        mgr.health_check.assert_called_once()
        mgr.provision.assert_not_called()
        mgr.terminate.assert_not_called()

    def test_running_but_unhealthy_recovers_via_terminate_then_provision(
        self,
        db_session: Session,
        test_user: User,
    ) -> None:
        """RUNNING + health_check=False → terminate + re-provision."""
        existing = _seed_sandbox(db_session, test_user, SandboxStatus.RUNNING)
        mgr = _make_mock_sandbox_manager(healthy=False)
        session_manager = _make_session_manager(db_session, sandbox_manager=mgr)

        sandbox = session_manager.ensure_sandbox_running(test_user.id)
        db_session.commit()

        assert sandbox.id == existing.id
        assert sandbox.status == SandboxStatus.RUNNING
        mgr.health_check.assert_called_once()
        mgr.terminate.assert_called_once_with(existing.id)
        mgr.provision.assert_called_once()

    @pytest.mark.parametrize(
        "initial_status",
        [
            SandboxStatus.SLEEPING,
            SandboxStatus.TERMINATED,
            SandboxStatus.FAILED,
        ],
    )
    def test_wakes_dormant_sandbox(
        self,
        db_session: Session,
        test_user: User,
        initial_status: SandboxStatus,
    ) -> None:
        """SLEEPING / TERMINATED / FAILED → re-provision in place."""
        existing = _seed_sandbox(db_session, test_user, initial_status)
        mgr = _make_mock_sandbox_manager()
        session_manager = _make_session_manager(db_session, sandbox_manager=mgr)

        sandbox = session_manager.ensure_sandbox_running(test_user.id)
        db_session.commit()

        assert sandbox.id == existing.id
        assert sandbox.status == SandboxStatus.RUNNING
        mgr.provision.assert_called_once()
        mgr.health_check.assert_not_called()
        mgr.terminate.assert_not_called()

    def test_provisioning_transitions_to_running_during_wait(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A concurrent provisioner finishes mid-wait: we return RUNNING
        without calling ``provision()`` ourselves."""
        existing = _seed_sandbox(db_session, test_user, SandboxStatus.PROVISIONING)
        mgr = _make_mock_sandbox_manager(healthy=True)
        session_manager = _make_session_manager(db_session, sandbox_manager=mgr)

        # Use the sleep hook to simulate the concurrent provisioner
        # committing: between the first and second refresh, flip the row
        # to RUNNING. The next refresh sees the committed value.
        flipped: list[bool] = [False]

        def _flipping_sleep(_seconds: float) -> None:
            if not flipped[0]:
                update_sandbox_status__no_commit(
                    db_session, existing.id, SandboxStatus.RUNNING
                )
                db_session.commit()
                flipped[0] = True

        monkeypatch.setattr(
            "onyx.server.features.build.session.manager.time.sleep",
            _flipping_sleep,
        )

        sandbox = session_manager.ensure_sandbox_running(
            test_user.id,
            provisioning_wait_seconds=10.0,
        )

        assert sandbox.id == existing.id
        assert sandbox.status == SandboxStatus.RUNNING
        # Health check runs because the row reached RUNNING during the wait.
        mgr.health_check.assert_called_once()
        # We did NOT provision — the (mocked) concurrent caller did.
        mgr.provision.assert_not_called()
        mgr.terminate.assert_not_called()

    def test_provisioning_times_out_raises(
        self,
        db_session: Session,
        test_user: User,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Stuck PROVISIONING → SandboxProvisioningError once the deadline
        elapses (without provisioning ourselves)."""
        _seed_sandbox(db_session, test_user, SandboxStatus.PROVISIONING)
        mgr = _make_mock_sandbox_manager()
        session_manager = _make_session_manager(db_session, sandbox_manager=mgr)

        # No-op sleep keeps the test fast; real time.monotonic() still
        # advances on each iteration, so a tiny wait deadline elapses on
        # the first check.
        def _sleep_noop(_seconds: float) -> None:
            return None

        monkeypatch.setattr(
            "onyx.server.features.build.session.manager.time.sleep",
            _sleep_noop,
        )

        with pytest.raises(SandboxProvisioningError):
            session_manager.ensure_sandbox_running(
                test_user.id,
                provisioning_wait_seconds=0.0,
            )

        mgr.provision.assert_not_called()
        mgr.health_check.assert_not_called()
