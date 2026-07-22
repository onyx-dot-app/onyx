"""External dependency unit tests for the user-file port scope (PR1 — schema + helpers).

Covers the scope-polymorphic PortAttempt (exactly-one CHECK, the NULL-distinct
user-branch active-unique index), the user-file enumeration/survival helpers the port
scheduler will consume, and the secondary_reconcile_pending flag lifecycle. All dark
until PR2 wires the port itself — these assert only the storage/read/write primitives.
"""

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.enums import UserFileStatus
from onyx.db.models import ConnectorCredentialPair, SearchSettings, User, UserFile
from onyx.db.port_attempt import (
    count_active_port_attempts,
    create_port_attempt,
    get_active_port_attempt,
    get_latest_port_attempt,
    mark_port_in_progress,
    mark_port_succeeded,
)
from onyx.db.user_file import (
    clear_user_file_reconcile_pending,
    count_user_files_reconcile_pending,
    fetch_port_scope_user_ids,
    filter_existing_user_file_ids,
    get_max_user_file_id_for_user,
    get_user_file_ids_for_user_batch,
    mark_user_file_reconcile_pending,
    user_file_port_scope_active,
)
from tests.external_dependency_unit.conftest import create_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    make_future_search_settings,
)


def _make_user_file(
    db_session: Session,
    user_id: UUID,
    status: UserFileStatus = UserFileStatus.COMPLETED,
) -> UserFile:
    uf = UserFile(
        id=uuid4(),
        user_id=user_id,
        file_id=f"portscope_{uuid4().hex[:8]}",
        name=f"{uuid4().hex[:8]}.txt",
        file_type="text/plain",
        status=status,
    )
    db_session.add(uf)
    db_session.commit()
    db_session.refresh(uf)
    return uf


def _delete_user_and_files(db_session: Session, user_id: UUID) -> None:
    """Teardown: user_file.user_id has no ON DELETE cascade, so drop the files first,
    then the user (via the ORM object to avoid a column-equality delete)."""
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
    user = create_test_user(db_session, "portscope")
    try:
        yield user
    finally:
        _delete_user_and_files(db_session, user.id)


@pytest.fixture
def future_ss_id(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[int, None, None]:
    ss_id = make_future_search_settings(db_session, use_port_flow=True).id
    try:
        yield ss_id
    finally:
        db_session.rollback()
        # Deleting the settings cascades its PortAttempts (FK ondelete=CASCADE).
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


def test_create_port_attempt_rejects_neither_scope(
    db_session: Session, future_ss_id: int
) -> None:
    with pytest.raises(ValueError):
        create_port_attempt(db_session, None, future_ss_id)


def test_create_port_attempt_rejects_both_scopes(
    db_session: Session,
    future_ss_id: int,
    port_user: User,
    cc_pair: ConnectorCredentialPair,
) -> None:
    with pytest.raises(ValueError):
        create_port_attempt(
            db_session, cc_pair.id, future_ss_id, port_user_id=port_user.id
        )


def test_user_active_unique_rejects_second_active(
    db_session: Session, future_ss_id: int, port_user: User
) -> None:
    """At most one active (NOT_STARTED/IN_PROGRESS) attempt per (user, FUTURE)."""
    create_port_attempt(db_session, None, future_ss_id, port_user_id=port_user.id)
    with pytest.raises(IntegrityError):
        create_port_attempt(db_session, None, future_ss_id, port_user_id=port_user.id)
    db_session.rollback()


def test_user_active_unique_allows_distinct_users(
    db_session: Session, future_ss_id: int, port_user: User
) -> None:
    """Two NULL-cc_pair user attempts for different users must not collide — proves
    the connector active-unique index is scoped to `cc_pair_id IS NOT NULL`."""
    other = create_test_user(db_session, "portscope_other")
    try:
        a = create_port_attempt(
            db_session, None, future_ss_id, port_user_id=port_user.id
        )
        b = create_port_attempt(db_session, None, future_ss_id, port_user_id=other.id)
        assert a.id != b.id
    finally:
        _delete_user_and_files(db_session, other.id)


def test_user_active_unique_allows_new_after_terminal(
    db_session: Session, future_ss_id: int, port_user: User
) -> None:
    """A settled attempt frees the active slot for a resume."""
    first = create_port_attempt(
        db_session, None, future_ss_id, port_user_id=port_user.id
    )
    mark_port_in_progress(db_session, first.id)
    mark_port_succeeded(db_session, first.id)
    second = create_port_attempt(
        db_session, None, future_ss_id, port_user_id=port_user.id
    )
    assert second.id != first.id


def test_get_active_and_latest_by_user_scope(
    db_session: Session, future_ss_id: int, port_user: User
) -> None:
    assert (
        get_active_port_attempt(
            db_session, None, future_ss_id, port_user_id=port_user.id
        )
        is None
    )
    attempt = create_port_attempt(
        db_session, None, future_ss_id, port_user_id=port_user.id
    )
    active = get_active_port_attempt(
        db_session, None, future_ss_id, port_user_id=port_user.id
    )
    assert active is not None and active.id == attempt.id
    latest = get_latest_port_attempt(
        db_session, None, future_ss_id, port_user_id=port_user.id
    )
    assert latest is not None and latest.id == attempt.id


def test_count_active_port_attempts_scope_isolation(
    db_session: Session,
    future_ss_id: int,
    port_user: User,
    cc_pair: ConnectorCredentialPair,
) -> None:
    """A user attempt is not counted against the connector cap, and vice versa."""
    create_port_attempt(db_session, cc_pair.id, future_ss_id)
    create_port_attempt(db_session, None, future_ss_id, port_user_id=port_user.id)
    assert count_active_port_attempts(db_session, future_ss_id, scope="connector") == 1
    assert count_active_port_attempts(db_session, future_ss_id, scope="user_file") == 1


def test_fetch_port_scope_user_ids_membership(
    db_session: Session, port_user: User
) -> None:
    """A user with a COMPLETED file is enumerated; a PROCESSING-only user is not."""
    _make_user_file(db_session, port_user.id, UserFileStatus.COMPLETED)
    processing_user = create_test_user(db_session, "portscope_proc")
    try:
        _make_user_file(db_session, processing_user.id, UserFileStatus.PROCESSING)
        enumerated = set(fetch_port_scope_user_ids(db_session))
        assert port_user.id in enumerated
        assert processing_user.id not in enumerated
    finally:
        _delete_user_and_files(db_session, processing_user.id)


def test_user_file_batch_cursor_and_bounds(
    db_session: Session, port_user: User
) -> None:
    ids = sorted(str(_make_user_file(db_session, port_user.id).id) for _ in range(5))
    up_to = ids[3]  # exclude the last id from the snapshot

    page = get_user_file_ids_for_user_batch(
        db_session, port_user.id, after_id=None, limit=2, up_to_id=up_to
    )
    assert page == ids[:2]

    rest = get_user_file_ids_for_user_batch(
        db_session, port_user.id, after_id=ids[1], limit=10, up_to_id=up_to
    )
    assert rest == ids[2:4]  # id>ids[1] AND id<=ids[3]

    assert get_max_user_file_id_for_user(db_session, port_user.id) == ids[-1]


def test_filter_existing_user_file_ids_drops_non_completed(
    db_session: Session, port_user: User
) -> None:
    completed = _make_user_file(db_session, port_user.id, UserFileStatus.COMPLETED)
    deleting = _make_user_file(db_session, port_user.id, UserFileStatus.DELETING)
    survivors = filter_existing_user_file_ids(
        db_session, port_user.id, [str(completed.id), str(deleting.id)]
    )
    assert survivors == {str(completed.id)}


def test_user_file_port_scope_active(db_session: Session, port_user: User) -> None:
    assert user_file_port_scope_active(db_session, port_user.id) is True
    assert user_file_port_scope_active(db_session, uuid4()) is False


def test_secondary_pending_flag_round_trip(
    db_session: Session, port_user: User
) -> None:
    uf = _make_user_file(db_session, port_user.id)
    baseline = count_user_files_reconcile_pending(db_session)

    mark_user_file_reconcile_pending(db_session, uf.id)
    db_session.expire_all()
    marked = db_session.get(UserFile, uf.id)
    assert marked is not None and marked.secondary_reconcile_pending is True
    assert count_user_files_reconcile_pending(db_session) == baseline + 1

    clear_user_file_reconcile_pending(db_session, uf.id)
    db_session.expire_all()
    cleared = db_session.get(UserFile, uf.id)
    assert cleared is not None and cleared.secondary_reconcile_pending is False
    assert count_user_files_reconcile_pending(db_session) == baseline
