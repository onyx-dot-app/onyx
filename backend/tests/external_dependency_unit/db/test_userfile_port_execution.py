"""External dependency unit tests for the user-file port EXECUTION (PR2).

Covers the scope branch in run_port_attempt (a user attempt ports its files and does
NOT self-cancel down the cc_pair path), the scheduler's user loop + dedicated-queue
routing, the swap gate's user-scope gating (incl. a zero-connector tenant), the INSTANT
reclaim pin, and the user-scope orphan record/sweep. PortCopier is mocked, so these run
without OpenSearch / the model server (the copy internals have their own tests).
"""

from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import UUID
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.beat_schedule import BEAT_EXPIRES_DEFAULT
from onyx.background.celery.tasks.port import tasks as port_task
from onyx.background.celery.tasks.port.tasks import run_check_for_port
from onyx.background.celery.tasks.port.tasks import run_port_attempt
from onyx.configs.constants import OnyxCeleryQueues
from onyx.configs.constants import OnyxCeleryTask
from onyx.db.enums import PortAttemptStatus
from onyx.db.enums import UserFileStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import PortAttempt
from onyx.db.models import SearchSettings
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.port_attempt import _user_file_port_has_pending_work
from onyx.db.port_attempt import all_user_scopes_ported
from onyx.db.port_attempt import create_port_attempt
from onyx.db.port_attempt import mark_port_in_progress
from onyx.db.port_attempt import mark_port_succeeded
from onyx.db.port_orphan_candidate import clear_port_orphan_candidates
from onyx.db.port_orphan_candidate import get_port_orphan_candidate_doc_ids
from onyx.db.port_orphan_candidate import record_port_orphan_candidates_for_user_file
from onyx.db.search_settings import get_current_search_settings
from onyx.db.swap_index import _port_swap_ready
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_future_search_settings


def _make_user_file(
    db_session: Session,
    user_id: UUID,
    status: UserFileStatus = UserFileStatus.COMPLETED,
) -> UserFile:
    uf = UserFile(
        id=uuid4(),
        user_id=user_id,
        file_id=f"portexec_{uuid4().hex[:8]}",
        name=f"{uuid4().hex[:8]}.txt",
        file_type="text/plain",
        status=status,
    )
    db_session.add(uf)
    db_session.commit()
    db_session.refresh(uf)
    return uf


def _delete_user_and_files(db_session: Session, user_id: UUID) -> None:
    db_session.rollback()
    db_session.query(UserFile).filter(UserFile.user_id == user_id).delete(
        synchronize_session="fetch"
    )
    user = db_session.get(User, user_id)
    if user is not None:
        db_session.delete(user)
    db_session.commit()


@pytest.fixture
def port_user(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[User, None, None]:
    user = create_test_user(db_session, "portexec")
    try:
        yield user
    finally:
        _delete_user_and_files(db_session, user.id)


@pytest.fixture
def future_ss_id(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[int, None, None]:
    future_ss = make_future_search_settings(db_session, use_port_flow=True)
    # create_search_settings inherits use_port_flow from PRESENT, so force it on here.
    future_ss.use_port_flow = True
    db_session.commit()
    ss_id = future_ss.id
    try:
        yield ss_id
    finally:
        db_session.rollback()
        db_session.query(SearchSettings).filter(SearchSettings.id == ss_id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        db_session.rollback()
        cleanup_cc_pair(db_session, pair)


def _run_check_for_port_for_user(
    user_id: UUID, future_id: int
) -> tuple[int | None, MagicMock]:
    """Run check_for_port scoped to this test's FUTURE + a single user, and no
    connectors (so only the user loop acts)."""
    celery_app = MagicMock()
    with (
        patch.object(
            port_task,
            "get_secondary_search_settings",
            lambda db, *_, **__: db.get(SearchSettings, future_id),
        ),
        patch.object(
            port_task,
            "fetch_indexable_standard_connector_credential_pair_ids",
            lambda *_, **__: [],
        ),
        patch.object(
            port_task, "fetch_port_scope_user_ids", lambda *_, **__: [user_id]
        ),
    ):
        result = run_check_for_port(get_current_tenant_id(), celery_app)
    return result, celery_app


# --- run_port_attempt: the scope branch (proves no cc_pair self-cancel) ------


def test_run_port_attempt_user_scope_happy_path(
    db_session: Session, future_ss_id: int, port_user: User
) -> None:
    """A user attempt ports its COMPLETED files and reaches SUCCESS — proving it takes
    the user branch, not the cc_pair path (which would self-cancel on a NULL cc_pair)."""
    file_ids = sorted(
        str(_make_user_file(db_session, port_user.id).id) for _ in range(3)
    )
    attempt_id = create_port_attempt(
        db_session, None, future_ss_id, port_user_id=port_user.id
    ).id

    mock_copier = MagicMock()
    mock_copier.copy_doc_batch.side_effect = lambda ids, **_: (len(ids), False)
    with patch.object(port_task, "PortCopier", return_value=mock_copier):
        run_port_attempt(attempt_id)

    mock_copier.copy_doc_batch.assert_called_once()
    assert mock_copier.copy_doc_batch.call_args.args[0] == file_ids

    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.status == PortAttemptStatus.SUCCESS
    assert row.last_processed_doc_id == file_ids[-1]
    assert row.docs_ported == len(file_ids)


def test_run_port_attempt_user_scope_survival_filter(
    db_session: Session, future_ss_id: int, port_user: User
) -> None:
    """The survival filter passed to the copier drops a file no longer COMPLETED, so a
    delete mid-port isn't resurrected."""
    completed = _make_user_file(db_session, port_user.id, UserFileStatus.COMPLETED)
    deleting = _make_user_file(db_session, port_user.id, UserFileStatus.DELETING)
    attempt_id = create_port_attempt(
        db_session, None, future_ss_id, port_user_id=port_user.id
    ).id

    captured: dict[str, set[str]] = {}
    mock_copier = MagicMock()

    def _copy(ids: list[str], *, surviving_doc_ids=None, **_):  # type: ignore[no-untyped-def]
        captured["surviving"] = surviving_doc_ids() if surviving_doc_ids else set()
        return len(ids), False

    mock_copier.copy_doc_batch.side_effect = _copy
    with patch.object(port_task, "PortCopier", return_value=mock_copier):
        run_port_attempt(attempt_id)

    # only the COMPLETED file survives; the DELETING one is filtered out
    assert captured["surviving"] == {str(completed.id)}
    assert str(deleting.id) not in captured["surviving"]


# --- scheduler: user loop + dedicated-queue routing --------------------------


def test_check_for_port_creates_user_attempt_on_user_file_port_queue(
    db_session: Session, future_ss_id: int, port_user: User
) -> None:
    """A use_port_flow FUTURE + a user with COMPLETED files -> one user PortAttempt,
    enqueued as RUN_USER_FILE_PORT_ATTEMPT on the user_file_port queue."""
    _make_user_file(db_session, port_user.id)

    result, celery_app = _run_check_for_port_for_user(port_user.id, future_ss_id)

    assert result == 1
    db_session.expire_all()
    attempts = (
        db_session.query(PortAttempt)
        .filter(
            PortAttempt.port_user_id == port_user.id,
            PortAttempt.search_settings_id == future_ss_id,
        )
        .all()
    )
    assert len(attempts) == 1
    assert attempts[0].status == PortAttemptStatus.NOT_STARTED
    assert attempts[0].cc_pair_id is None

    call = celery_app.send_task.call_args
    assert call.args[0] == OnyxCeleryTask.RUN_USER_FILE_PORT_ATTEMPT
    assert call.kwargs["queue"] == OnyxCeleryQueues.USER_FILE_PORT
    assert call.kwargs["kwargs"] == {
        "port_attempt_id": attempts[0].id,
        "tenant_id": get_current_tenant_id(),
    }
    assert call.kwargs["expires"] == BEAT_EXPIRES_DEFAULT


# --- swap gate: user scope gates, incl. zero-connector -----------------------


def test_swap_gate_blocks_on_unsettled_user_then_releases(
    db_session: Session, future_ss_id: int, port_user: User
) -> None:
    """A zero-connector tenant still gates on user files: blocked while the user attempt
    is unsettled, ready once it SUCCEEDs (the old `not required_cc_pairs` short-circuit
    would have swapped immediately)."""
    future_ss = db_session.get(SearchSettings, future_ss_id)
    assert future_ss is not None
    _make_user_file(db_session, port_user.id)
    attempt = create_port_attempt(
        db_session, None, future_ss_id, port_user_id=port_user.id
    )

    # no connectors required; user attempt unsettled -> not ready
    assert _port_swap_ready(db_session, future_ss, [], [port_user.id]) is False
    assert all_user_scopes_ported(db_session, future_ss_id, [port_user.id]) is False

    mark_port_in_progress(db_session, attempt.id)
    mark_port_succeeded(db_session, attempt.id)

    assert all_user_scopes_ported(db_session, future_ss_id, [port_user.id]) is True
    assert _port_swap_ready(db_session, future_ss, [], [port_user.id]) is True


# --- INSTANT reclaim: the source stays pinned until user files drain ---------


def test_user_file_port_pending_until_attempt_succeeds(
    db_session: Session, future_ss_id: int, port_user: User
) -> None:
    """The user-scope term that pins an INSTANT source (via port_backfill_has_pending_work)
    stays True while a portable user lacks a settled attempt, and clears once it SUCCEEDs.
    Tested on the user-scope helper directly so the deployment's connectors don't confound
    the signal."""
    _make_user_file(db_session, port_user.id)
    assert _user_file_port_has_pending_work(db_session, future_ss_id) is True

    attempt = create_port_attempt(
        db_session, None, future_ss_id, port_user_id=port_user.id
    )
    mark_port_in_progress(db_session, attempt.id)
    mark_port_succeeded(db_session, attempt.id)
    assert _user_file_port_has_pending_work(db_session, future_ss_id) is False


# --- orphan record + sweep for user scope ------------------------------------


def test_record_and_read_user_orphan_candidate(
    db_session: Session, future_ss_id: int, port_user: User
) -> None:
    """A user-file delete during an active port records a user-scope candidate that the
    sweep reads (and clears) under the user scope."""
    future_ss = db_session.get(SearchSettings, future_ss_id)
    assert future_ss is not None
    primary = get_current_search_settings(db_session)
    uf = _make_user_file(db_session, port_user.id)

    recorded = record_port_orphan_candidates_for_user_file(
        db_session,
        port_user_id=port_user.id,
        document_id=str(uf.id),
        primary=primary,
        secondary=future_ss,
    )
    db_session.commit()
    assert len(recorded) == 1

    doc_ids = get_port_orphan_candidate_doc_ids(
        db_session, future_ss_id, None, port_user_id=port_user.id
    )
    assert doc_ids == [str(uf.id)]

    clear_port_orphan_candidates(
        db_session, future_ss_id, None, doc_ids, port_user_id=port_user.id
    )
    db_session.commit()
    assert (
        get_port_orphan_candidate_doc_ids(
            db_session, future_ss_id, None, port_user_id=port_user.id
        )
        == []
    )
