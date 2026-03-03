"""External dependency unit tests for startup recovery (Step 10g).

Seeds ``UserFile`` records in stuck states (PROCESSING, DELETING,
needs_project_sync) then calls ``recover_stuck_user_files`` and verifies
the drain loops pick them up via ``FOR UPDATE SKIP LOCKED``.

Uses real PostgreSQL (via ``db_session`` / ``tenant_context`` fixtures).
The per-file ``*_impl`` functions are mocked so no real file store or
connector is needed — we only verify that recovery finds and dispatches
the correct files.
"""

from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from onyx.background.periodic_poller import recover_stuck_user_files
from onyx.db.enums import UserFileStatus
from onyx.db.models import UserFile
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.constants import TEST_TENANT_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_IMPL_MODULE = "onyx.background.celery.tasks.user_file_processing.tasks"


def _create_user_file(
    db_session: Session,
    user_id: object,
    *,
    status: UserFileStatus = UserFileStatus.PROCESSING,
    needs_project_sync: bool = False,
    needs_persona_sync: bool = False,
) -> UserFile:
    uf = UserFile(
        id=uuid4(),
        user_id=user_id,
        file_id=f"test_file_{uuid4().hex[:8]}",
        name=f"test_{uuid4().hex[:8]}.txt",
        file_type="text/plain",
        status=status,
        needs_project_sync=needs_project_sync,
        needs_persona_sync=needs_persona_sync,
    )
    db_session.add(uf)
    db_session.commit()
    db_session.refresh(uf)
    return uf


def _fake_delete_impl(
    user_file_id: str, tenant_id: str, redis_locking: bool  # noqa: ARG001
) -> None:
    """Mock side-effect: delete the row so the drain loop terminates."""
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    with get_session_with_current_tenant() as session:
        session.execute(sa.delete(UserFile).where(UserFile.id == UUID(user_file_id)))
        session.commit()


def _fake_sync_impl(
    user_file_id: str, tenant_id: str, redis_locking: bool  # noqa: ARG001
) -> None:
    """Mock side-effect: clear sync flags so the drain loop terminates."""
    from onyx.db.engine.sql_engine import get_session_with_current_tenant

    with get_session_with_current_tenant() as session:
        session.execute(
            sa.update(UserFile)
            .where(UserFile.id == UUID(user_file_id))
            .values(needs_project_sync=False, needs_persona_sync=False)
        )
        session.commit()


@pytest.fixture()
def _cleanup_user_files(db_session: Session) -> Generator[list[UserFile], None, None]:
    """Track created UserFile rows and delete them after each test."""
    created: list[UserFile] = []
    yield created
    for uf in created:
        existing = db_session.get(UserFile, uf.id)
        if existing:
            db_session.delete(existing)
    db_session.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRecoverProcessingFiles:
    """Files in PROCESSING status are re-processed via the processing drain loop."""

    def test_processing_files_recovered(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        _cleanup_user_files: list[UserFile],
    ) -> None:
        user = create_test_user(db_session, "recovery_proc")
        uf = _create_user_file(db_session, user.id, status=UserFileStatus.PROCESSING)
        _cleanup_user_files.append(uf)

        mock_impl = MagicMock()
        with patch(f"{_IMPL_MODULE}.process_user_file_impl", mock_impl):
            recover_stuck_user_files(TEST_TENANT_ID)

        called_ids = [call.kwargs["user_file_id"] for call in mock_impl.call_args_list]
        assert (
            str(uf.id) in called_ids
        ), f"Expected file {uf.id} to be recovered but got: {called_ids}"

    def test_completed_files_not_recovered(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        _cleanup_user_files: list[UserFile],
    ) -> None:
        user = create_test_user(db_session, "recovery_comp")
        uf = _create_user_file(db_session, user.id, status=UserFileStatus.COMPLETED)
        _cleanup_user_files.append(uf)

        mock_impl = MagicMock()
        with patch(f"{_IMPL_MODULE}.process_user_file_impl", mock_impl):
            recover_stuck_user_files(TEST_TENANT_ID)

        called_ids = [call.kwargs["user_file_id"] for call in mock_impl.call_args_list]
        assert (
            str(uf.id) not in called_ids
        ), f"COMPLETED file {uf.id} should not have been recovered"


class TestRecoverDeletingFiles:
    """Files in DELETING status are recovered via the delete drain loop."""

    def test_deleting_files_recovered(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        _cleanup_user_files: list[UserFile],
    ) -> None:
        user = create_test_user(db_session, "recovery_del")
        uf = _create_user_file(db_session, user.id, status=UserFileStatus.DELETING)
        # Row is deleted by _fake_delete_impl, so no cleanup needed.

        mock_impl = MagicMock(side_effect=_fake_delete_impl)
        with patch(f"{_IMPL_MODULE}.delete_user_file_impl", mock_impl):
            recover_stuck_user_files(TEST_TENANT_ID)

        called_ids = [call.kwargs["user_file_id"] for call in mock_impl.call_args_list]
        assert (
            str(uf.id) in called_ids
        ), f"Expected file {uf.id} to be recovered for deletion but got: {called_ids}"


class TestRecoverSyncFiles:
    """Files needing project/persona sync are recovered via the sync drain loop."""

    def test_needs_project_sync_recovered(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        _cleanup_user_files: list[UserFile],
    ) -> None:
        user = create_test_user(db_session, "recovery_sync")
        uf = _create_user_file(
            db_session,
            user.id,
            status=UserFileStatus.COMPLETED,
            needs_project_sync=True,
        )
        _cleanup_user_files.append(uf)

        mock_impl = MagicMock(side_effect=_fake_sync_impl)
        with patch(f"{_IMPL_MODULE}.project_sync_user_file_impl", mock_impl):
            recover_stuck_user_files(TEST_TENANT_ID)

        called_ids = [call.kwargs["user_file_id"] for call in mock_impl.call_args_list]
        assert (
            str(uf.id) in called_ids
        ), f"Expected file {uf.id} to be recovered for sync but got: {called_ids}"

    def test_needs_persona_sync_recovered(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        _cleanup_user_files: list[UserFile],
    ) -> None:
        user = create_test_user(db_session, "recovery_psync")
        uf = _create_user_file(
            db_session,
            user.id,
            status=UserFileStatus.COMPLETED,
            needs_persona_sync=True,
        )
        _cleanup_user_files.append(uf)

        mock_impl = MagicMock(side_effect=_fake_sync_impl)
        with patch(f"{_IMPL_MODULE}.project_sync_user_file_impl", mock_impl):
            recover_stuck_user_files(TEST_TENANT_ID)

        called_ids = [call.kwargs["user_file_id"] for call in mock_impl.call_args_list]
        assert (
            str(uf.id) in called_ids
        ), f"Expected file {uf.id} to be recovered for persona sync but got: {called_ids}"


class TestRecoveryMultipleFiles:
    """Recovery processes all stuck files in one pass, not just the first."""

    def test_multiple_processing_files(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        _cleanup_user_files: list[UserFile],
    ) -> None:
        user = create_test_user(db_session, "recovery_multi")
        files = []
        for _ in range(3):
            uf = _create_user_file(
                db_session, user.id, status=UserFileStatus.PROCESSING
            )
            _cleanup_user_files.append(uf)
            files.append(uf)

        mock_impl = MagicMock()
        with patch(f"{_IMPL_MODULE}.process_user_file_impl", mock_impl):
            recover_stuck_user_files(TEST_TENANT_ID)

        called_ids = {call.kwargs["user_file_id"] for call in mock_impl.call_args_list}
        expected_ids = {str(uf.id) for uf in files}
        assert expected_ids.issubset(called_ids), (
            f"Expected all {len(files)} files to be recovered. "
            f"Missing: {expected_ids - called_ids}"
        )


class TestTransientFailures:
    """Drain loops skip failed files, process the rest, and terminate."""

    def test_processing_failure_skips_and_continues(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        _cleanup_user_files: list[UserFile],
    ) -> None:
        user = create_test_user(db_session, "fail_proc")
        uf_fail = _create_user_file(
            db_session, user.id, status=UserFileStatus.PROCESSING
        )
        uf_ok = _create_user_file(db_session, user.id, status=UserFileStatus.PROCESSING)
        _cleanup_user_files.extend([uf_fail, uf_ok])

        fail_id = str(uf_fail.id)

        def side_effect(
            *, user_file_id: str, tenant_id: str, redis_locking: bool  # noqa: ARG001
        ) -> None:
            if user_file_id == fail_id:
                raise RuntimeError("transient failure")

        mock_impl = MagicMock(side_effect=side_effect)
        with patch(f"{_IMPL_MODULE}.process_user_file_impl", mock_impl):
            recover_stuck_user_files(TEST_TENANT_ID)

        called_ids = [call.kwargs["user_file_id"] for call in mock_impl.call_args_list]
        assert fail_id in called_ids, "Failed file should have been attempted"
        assert str(uf_ok.id) in called_ids, "Healthy file should have been processed"
        assert called_ids.count(fail_id) == 1, "Failed file retried — infinite loop"
        assert called_ids.count(str(uf_ok.id)) == 1

    def test_delete_failure_skips_and_continues(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        _cleanup_user_files: list[UserFile],
    ) -> None:
        user = create_test_user(db_session, "fail_del")
        uf_fail = _create_user_file(db_session, user.id, status=UserFileStatus.DELETING)
        uf_ok = _create_user_file(db_session, user.id, status=UserFileStatus.DELETING)
        _cleanup_user_files.append(uf_fail)

        fail_id = str(uf_fail.id)

        def side_effect(
            *, user_file_id: str, tenant_id: str, redis_locking: bool
        ) -> None:
            if user_file_id == fail_id:
                raise RuntimeError("transient failure")
            _fake_delete_impl(user_file_id, tenant_id, redis_locking)

        mock_impl = MagicMock(side_effect=side_effect)
        with patch(f"{_IMPL_MODULE}.delete_user_file_impl", mock_impl):
            recover_stuck_user_files(TEST_TENANT_ID)

        called_ids = [call.kwargs["user_file_id"] for call in mock_impl.call_args_list]
        assert fail_id in called_ids, "Failed file should have been attempted"
        assert str(uf_ok.id) in called_ids, "Healthy file should have been deleted"
        assert called_ids.count(fail_id) == 1, "Failed file retried — infinite loop"
        assert called_ids.count(str(uf_ok.id)) == 1

    def test_sync_failure_skips_and_continues(
        self,
        db_session: Session,
        tenant_context: None,  # noqa: ARG002
        _cleanup_user_files: list[UserFile],
    ) -> None:
        user = create_test_user(db_session, "fail_sync")
        uf_fail = _create_user_file(
            db_session,
            user.id,
            status=UserFileStatus.COMPLETED,
            needs_project_sync=True,
        )
        uf_ok = _create_user_file(
            db_session,
            user.id,
            status=UserFileStatus.COMPLETED,
            needs_persona_sync=True,
        )
        _cleanup_user_files.extend([uf_fail, uf_ok])

        fail_id = str(uf_fail.id)

        def side_effect(
            *, user_file_id: str, tenant_id: str, redis_locking: bool
        ) -> None:
            if user_file_id == fail_id:
                raise RuntimeError("transient failure")
            _fake_sync_impl(user_file_id, tenant_id, redis_locking)

        mock_impl = MagicMock(side_effect=side_effect)
        with patch(f"{_IMPL_MODULE}.project_sync_user_file_impl", mock_impl):
            recover_stuck_user_files(TEST_TENANT_ID)

        called_ids = [call.kwargs["user_file_id"] for call in mock_impl.call_args_list]
        assert fail_id in called_ids, "Failed file should have been attempted"
        assert str(uf_ok.id) in called_ids, "Healthy file should have been synced"
        assert called_ids.count(fail_id) == 1, "Failed file retried — infinite loop"
        assert called_ids.count(str(uf_ok.id)) == 1
