from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from onyx.db.enums import SandboxStatus
from onyx.server.features.build.sandbox.models import FilesystemEntry
from onyx.server.features.build.session.manager import SessionManager
from tests.common.craft.stubs import StubSandboxManager


def _manager(sandbox_manager: StubSandboxManager) -> SessionManager:
    manager = SessionManager.__new__(SessionManager)
    manager._db_session = MagicMock()
    manager._sandbox_manager = sandbox_manager
    return manager


def _get_webapp_info(
    manager: SessionManager,
    *,
    session: SimpleNamespace,
    sandbox: SimpleNamespace | None,
    session_id: UUID,
    user_id: UUID,
) -> dict[str, object] | None:
    with (
        patch(
            "onyx.server.features.build.session.manager.get_build_session",
            return_value=session,
        ),
        patch(
            "onyx.server.features.build.session.manager.get_sandbox_by_user_id",
            return_value=sandbox,
        ),
    ):
        return manager.get_webapp_info(session_id, user_id)


def _session() -> SimpleNamespace:
    return SimpleNamespace(nextjs_port=3010, sharing_scope="private")


def test_reserved_port_without_scaffold_is_not_a_webapp() -> None:
    sandbox_manager = StubSandboxManager()
    sandbox_manager.list_directory_returns_by_path = {}
    manager = _manager(sandbox_manager)
    session_id = uuid4()
    user_id = uuid4()
    sandbox = SimpleNamespace(id=uuid4(), status=SandboxStatus.RUNNING)

    with patch.object(manager, "_check_nextjs_ready") as check_ready:
        info = _get_webapp_info(
            manager,
            session=_session(),
            sandbox=sandbox,
            session_id=session_id,
            user_id=user_id,
        )

    assert info is not None
    assert info["has_webapp"] is False
    assert info["webapp_url"] is None
    assert info["ready"] is False
    assert sandbox_manager.last_list_directory_payload == {
        "sandbox_id": sandbox.id,
        "session_id": session_id,
        "path": "outputs/web",
    }
    check_ready.assert_not_called()


def test_scaffold_marker_enables_readiness_probe() -> None:
    sandbox_manager = StubSandboxManager()
    sandbox_manager.list_directory_returns_by_path = {
        "outputs/web": [
            FilesystemEntry(
                name="package.json",
                path="outputs/web/package.json",
                is_directory=False,
            )
        ]
    }
    manager = _manager(sandbox_manager)
    session_id = uuid4()
    user_id = uuid4()
    sandbox = SimpleNamespace(id=uuid4(), status=SandboxStatus.RUNNING)

    with patch.object(manager, "_check_nextjs_ready", return_value=True) as check_ready:
        info = _get_webapp_info(
            manager,
            session=_session(),
            sandbox=sandbox,
            session_id=session_id,
            user_id=user_id,
        )

    assert info is not None
    assert info["has_webapp"] is True
    assert info["ready"] is True
    check_ready.assert_called_once_with(sandbox.id, session_id, 3010)


def test_sleeping_sandbox_reports_webapp_existence_as_unknown() -> None:
    sandbox_manager = StubSandboxManager()
    manager = _manager(sandbox_manager)
    session_id = uuid4()
    user_id = uuid4()
    sandbox = SimpleNamespace(id=uuid4(), status=SandboxStatus.SLEEPING)

    with patch.object(manager, "_check_nextjs_ready") as check_ready:
        info = _get_webapp_info(
            manager,
            session=_session(),
            sandbox=sandbox,
            session_id=session_id,
            user_id=user_id,
        )

    assert info is not None
    assert info["has_webapp"] is None
    assert info["ready"] is False
    assert sandbox_manager.list_directory_count == 0
    check_ready.assert_not_called()


def test_session_without_sandbox_reports_webapp_existence_as_unknown() -> None:
    sandbox_manager = StubSandboxManager()
    manager = _manager(sandbox_manager)

    info = _get_webapp_info(
        manager,
        session=_session(),
        sandbox=None,
        session_id=uuid4(),
        user_id=uuid4(),
    )

    assert info is not None
    assert info["has_webapp"] is None
    assert info["status"] == "no_sandbox"
    assert info["ready"] is False


def test_transient_scaffold_check_failure_reports_unknown() -> None:
    sandbox_manager = StubSandboxManager()
    manager = _manager(sandbox_manager)
    session_id = uuid4()
    user_id = uuid4()
    sandbox = SimpleNamespace(id=uuid4(), status=SandboxStatus.RUNNING)

    with (
        patch.object(
            sandbox_manager,
            "list_directory",
            side_effect=RuntimeError("sidecar unavailable"),
        ),
        patch.object(manager, "_check_nextjs_ready") as check_ready,
    ):
        info = _get_webapp_info(
            manager,
            session=_session(),
            sandbox=sandbox,
            session_id=session_id,
            user_id=user_id,
        )

    assert info is not None
    assert info["has_webapp"] is None
    assert info["webapp_url"] is None
    assert info["ready"] is False
    check_ready.assert_not_called()
