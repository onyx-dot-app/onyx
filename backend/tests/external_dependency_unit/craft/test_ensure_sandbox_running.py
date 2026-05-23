"""External-dependency unit tests for SessionManager.ensure_sandbox_running.

Exercises the headless sandbox state machine: creating a fresh sandbox
row, waking SLEEPING / TERMINATED / FAILED, recovering a RUNNING-but-
unhealthy pod, and polling a PROVISIONING sandbox to completion (or
timeout).

Uses the real Postgres DB (via the ``db_session`` fixture) and the real
``KubernetesSandboxManager`` against a kind cluster. Each test cleans
up its sandbox via ``mgr.terminate()`` so consecutive runs stay
hermetic. ``_get_llm_config`` is stubbed because the wake state machine
forwards the config opaquely to ``provision()`` and the test DB doesn't
seed a default LLM provider.

Gated to the K8s CI lane (``pr-craft-k8s-tests.yml``) since the local
sandbox backend was removed in
``docs/craft/2026-05-21-nuke-local-sandbox-manager.md``.
"""

from collections.abc import Generator
from unittest.mock import patch
from uuid import UUID

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import SandboxStatus
from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.db.sandbox import create_sandbox__no_commit
from onyx.server.features.build.db.sandbox import update_sandbox_status__no_commit
from onyx.server.features.build.sandbox.base import get_sandbox_manager
from onyx.server.features.build.sandbox.base import SandboxManager
from onyx.server.features.build.sandbox.models import LLMProviderConfig
from onyx.server.features.build.session.manager import SandboxProvisioningError
from onyx.server.features.build.session.manager import SessionManager
from tests.external_dependency_unit.constants import TEST_TENANT_ID

pytestmark = pytest.mark.skipif(
    SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
    reason="ensure_sandbox_running tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
)


def _make_session_manager(db_session: Session) -> SessionManager:
    """Construct a SessionManager wired to the env's real SandboxManager.

    ``_get_llm_config`` is stubbed because the wake state machine just
    forwards the config to ``provision()`` and the external-dependency
    test DB doesn't seed a default LLM provider.
    """
    sm = SessionManager(db_session)
    stub_config = LLMProviderConfig(
        provider="test",
        model_name="test-model",
        api_key="test-key",
        api_base=None,
    )
    setattr(sm, "_get_llm_config", lambda *_args, **_kwargs: stub_config)
    return sm


@pytest.fixture
def sandbox_cleanup() -> Generator[list[UUID], None, None]:
    """Track sandbox IDs created during a test and terminate them after.

    Goes through ``SandboxManager.terminate`` (matching real shutdown
    behavior) so the test stays valid on both Local and Kubernetes
    backends. Swallows errors during teardown — the goal is cleanup, not
    a second assertion surface.
    """
    tracked: list[UUID] = []
    yield tracked
    mgr = get_sandbox_manager()
    for sandbox_id in tracked:
        try:
            mgr.terminate(sandbox_id)
        except Exception:
            # Best-effort: the test may have already terminated it.
            pass


def _provision_real(
    mgr: SandboxManager,
    sandbox: Sandbox,
    user_id: UUID,
) -> None:
    """Bring a sandbox to RUNNING on the real backend.

    Used by tests that need the pod/dir to exist before calling
    ``ensure_sandbox_running`` (e.g. the "RUNNING + healthy" hot path).
    """
    mgr.provision(
        sandbox_id=sandbox.id,
        user_id=user_id,
        tenant_id=TEST_TENANT_ID,
        llm_config=LLMProviderConfig(
            provider="test",
            model_name="test-model",
            api_key="test-key",
            api_base=None,
        ),
        onyx_pat="ci-test-pat",
    )


def _seed_row(
    db_session: Session,
    user: User,
    status: SandboxStatus,
) -> Sandbox:
    """Create only the DB row — no pod/dir."""
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
        sandbox_cleanup: list[UUID],
    ) -> None:
        """No sandbox row → row is created and provisioned for real."""
        session_manager = _make_session_manager(db_session)

        sandbox = session_manager.ensure_sandbox_running(test_user.id)
        db_session.commit()
        sandbox_cleanup.append(sandbox.id)

        assert sandbox.user_id == test_user.id
        assert sandbox.status == SandboxStatus.RUNNING
        # The real provision() left the sandbox in a healthy state.
        assert session_manager._sandbox_manager.health_check(sandbox.id, timeout=5.0)

    def test_running_and_healthy_returns_as_is(
        self,
        db_session: Session,
        test_user: User,
        sandbox_cleanup: list[UUID],
    ) -> None:
        """RUNNING + health_check=True → no re-provision, no terminate."""
        session_manager = _make_session_manager(db_session)
        mgr = session_manager._sandbox_manager

        # Real seeded "healthy RUNNING" state: provision then make sure
        # the row is RUNNING.
        existing = create_sandbox__no_commit(
            db_session=db_session, user_id=test_user.id
        )
        _provision_real(mgr, existing, test_user.id)
        update_sandbox_status__no_commit(db_session, existing.id, SandboxStatus.RUNNING)
        db_session.commit()
        sandbox_cleanup.append(existing.id)

        with (
            patch.object(mgr, "provision", wraps=mgr.provision) as provision_spy,
            patch.object(mgr, "terminate", wraps=mgr.terminate) as terminate_spy,
        ):
            sandbox = session_manager.ensure_sandbox_running(test_user.id)

        assert sandbox.id == existing.id
        assert sandbox.status == SandboxStatus.RUNNING
        provision_spy.assert_not_called()
        terminate_spy.assert_not_called()

    def test_running_but_unhealthy_recovers_via_terminate_then_provision(
        self,
        db_session: Session,
        test_user: User,
        sandbox_cleanup: list[UUID],
    ) -> None:
        """RUNNING in DB but no pod/dir → health_check fails → terminate +
        re-provision."""
        # Seed RUNNING in the DB without actually provisioning, so the
        # real health_check fails (no pod, no directory).
        existing = _seed_row(db_session, test_user, SandboxStatus.RUNNING)
        sandbox_cleanup.append(existing.id)

        session_manager = _make_session_manager(db_session)
        mgr = session_manager._sandbox_manager

        with (
            patch.object(mgr, "terminate", wraps=mgr.terminate) as terminate_spy,
            patch.object(mgr, "provision", wraps=mgr.provision) as provision_spy,
        ):
            sandbox = session_manager.ensure_sandbox_running(test_user.id)
            db_session.commit()

        assert sandbox.id == existing.id
        assert sandbox.status == SandboxStatus.RUNNING
        terminate_spy.assert_called_once_with(existing.id)
        provision_spy.assert_called_once()
        # Real re-provision left the sandbox healthy.
        assert mgr.health_check(sandbox.id, timeout=5.0)

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
        sandbox_cleanup: list[UUID],
        initial_status: SandboxStatus,
    ) -> None:
        """SLEEPING / TERMINATED / FAILED → re-provision in place."""
        existing = _seed_row(db_session, test_user, initial_status)
        sandbox_cleanup.append(existing.id)

        session_manager = _make_session_manager(db_session)
        mgr = session_manager._sandbox_manager

        with patch.object(mgr, "provision", wraps=mgr.provision) as provision_spy:
            sandbox = session_manager.ensure_sandbox_running(test_user.id)
            db_session.commit()

        assert sandbox.id == existing.id
        assert sandbox.status == SandboxStatus.RUNNING
        provision_spy.assert_called_once()
        assert mgr.health_check(sandbox.id, timeout=5.0)

    def test_provisioning_transitions_to_running_during_wait(
        self,
        db_session: Session,
        test_user: User,
        sandbox_cleanup: list[UUID],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A concurrent provisioner finishes mid-wait: we return RUNNING
        without calling ``provision()`` ourselves."""
        existing = _seed_row(db_session, test_user, SandboxStatus.PROVISIONING)
        sandbox_cleanup.append(existing.id)

        session_manager = _make_session_manager(db_session)
        mgr = session_manager._sandbox_manager

        # Sleep-hook simulates the "other" provisioner finishing: flip
        # the DB row to RUNNING AND actually call the real provision so
        # the subsequent health_check sees a live pod/dir.
        #
        # Set the flag *before* calling _provision_real. The k8s manager
        # polls for pod readiness via ``time.sleep`` inside ``provision``,
        # and ``monkeypatch.setattr`` on ``time.sleep`` rebinds the
        # shared module attribute, so the inner sleep calls re-enter
        # this hook. Without the early flip, those re-entries would
        # recursively call ``_provision_real`` and blow the stack.
        flipped: list[bool] = [False]

        def _flipping_sleep(_seconds: float) -> None:
            if not flipped[0]:
                flipped[0] = True
                _provision_real(mgr, existing, test_user.id)
                update_sandbox_status__no_commit(
                    db_session, existing.id, SandboxStatus.RUNNING
                )
                db_session.commit()

        monkeypatch.setattr(
            "onyx.server.features.build.session.manager.time.sleep",
            _flipping_sleep,
        )

        with patch.object(mgr, "provision", wraps=mgr.provision) as provision_spy:
            sandbox = session_manager.ensure_sandbox_running(
                test_user.id,
                provisioning_wait_seconds=10.0,
            )

        assert sandbox.id == existing.id
        assert sandbox.status == SandboxStatus.RUNNING
        # Exactly one provision is expected — the one the sleep hook
        # makes to simulate the concurrent provisioner finishing. A
        # second call would mean session_manager re-provisioned after
        # the wait succeeded, which is what this test exists to prevent.
        assert provision_spy.call_count == 1

    def test_provisioning_times_out_raises(
        self,
        db_session: Session,
        test_user: User,
        sandbox_cleanup: list[UUID],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Stuck PROVISIONING → SandboxProvisioningError once the deadline
        elapses (without provisioning ourselves)."""
        existing = _seed_row(db_session, test_user, SandboxStatus.PROVISIONING)
        sandbox_cleanup.append(existing.id)

        session_manager = _make_session_manager(db_session)
        mgr = session_manager._sandbox_manager

        # No-op sleep keeps the test fast; real time.monotonic() still
        # advances, so the tiny wait deadline elapses on the first check.
        def _sleep_noop(_seconds: float) -> None:
            return None

        monkeypatch.setattr(
            "onyx.server.features.build.session.manager.time.sleep",
            _sleep_noop,
        )

        with patch.object(mgr, "provision", wraps=mgr.provision) as provision_spy:
            with pytest.raises(SandboxProvisioningError):
                session_manager.ensure_sandbox_running(
                    test_user.id,
                    provisioning_wait_seconds=0.0,
                )

        provision_spy.assert_not_called()
