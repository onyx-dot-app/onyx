"""Test that the start-of-run staging sweep skips files whose owning
attempt is still non-terminal.

The sweep at the start of a docfetching attempt deletes orphan staged
files left behind by previous attempts on the same cc_pair. Without
the terminal-status filter, a concurrent in-progress attempt (such as
a targeted reindex) would have its in-flight binaries wiped out from
under it. This test creates that exact race scenario and verifies the
fix.
"""

from collections.abc import Generator
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import IndexingStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.file_store.staging import reap_prior_attempt_staged_files
from onyx.file_store.staging import stage_raw_file
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def _make_attempt(
    db_session: Session,
    cc_pair_id: int,
    search_settings_id: int,
    status: IndexingStatus,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair_id,
        search_settings_id=search_settings_id,
        from_beginning=False,
        status=status,
    )
    db_session.add(attempt)
    db_session.commit()
    db_session.refresh(attempt)
    return attempt


def _stage_file(
    cc_pair_id: int, attempt_id: int, tenant_id: str, payload: bytes
) -> str:
    return stage_raw_file(
        content=BytesIO(payload),
        content_type="application/octet-stream",
        metadata={
            "index_attempt_id": attempt_id,
            "cc_pair_id": cc_pair_id,
            "tenant_id": tenant_id,
            "test_marker": uuid4().hex,
        },
    )


def test_sweep_skips_files_owned_by_non_terminal_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    initialize_file_store: None,  # noqa: ARG001
) -> None:
    """A concurrent in-progress attempt's staged files must survive the
    start-of-run sweep, even though they belong to a different attempt
    on the same cc_pair."""
    from onyx.db.search_settings import get_current_search_settings

    settings = get_current_search_settings(db_session)

    terminal_old = _make_attempt(
        db_session, cc_pair.id, settings.id, IndexingStatus.FAILED
    )
    in_progress_concurrent = _make_attempt(
        db_session, cc_pair.id, settings.id, IndexingStatus.IN_PROGRESS
    )
    current = _make_attempt(
        db_session, cc_pair.id, settings.id, IndexingStatus.IN_PROGRESS
    )

    file_for_terminal = _stage_file(
        cc_pair.id, terminal_old.id, TEST_TENANT_ID, b"terminal payload"
    )
    file_for_in_progress = _stage_file(
        cc_pair.id, in_progress_concurrent.id, TEST_TENANT_ID, b"concurrent payload"
    )
    file_for_current = _stage_file(
        cc_pair.id, current.id, TEST_TENANT_ID, b"current payload"
    )
    db_session.commit()

    # Run the sweep as if `current` is starting up.
    deleted_count = reap_prior_attempt_staged_files(
        current_attempt_id=current.id,
        cc_pair_id=cc_pair.id,
        tenant_id=TEST_TENANT_ID,
        db_session=db_session,
    )

    # Only the terminal attempt's file should have been reaped.
    assert deleted_count == 1

    from onyx.db.file_record import get_filerecord_by_file_id_optional

    db_session.expire_all()

    assert (
        get_filerecord_by_file_id_optional(file_for_terminal, db_session) is None
    ), "terminal attempt's staged file should be reaped"
    assert (
        get_filerecord_by_file_id_optional(file_for_in_progress, db_session) is not None
    ), "concurrent in-progress attempt's staged file must NOT be reaped"
    assert (
        get_filerecord_by_file_id_optional(file_for_current, db_session) is not None
    ), "current attempt's own file must NOT be reaped (excluded by current_attempt_id)"

    # Cleanup: remove the survivors so other tests don't see them.
    from onyx.file_store.file_store import get_default_file_store

    fs = get_default_file_store()
    for fid in (file_for_in_progress, file_for_current):
        try:
            fs.delete_file(fid)
        except Exception:
            pass


def test_sweep_skips_files_owned_by_not_started_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    initialize_file_store: None,  # noqa: ARG001
) -> None:
    """A `NOT_STARTED` attempt is also non-terminal — its staged files
    must survive the sweep. This covers the case where a worker wrote
    files but crashed before the attempt status moved out of NOT_STARTED."""
    from onyx.db.search_settings import get_current_search_settings

    settings = get_current_search_settings(db_session)

    not_started = _make_attempt(
        db_session, cc_pair.id, settings.id, IndexingStatus.NOT_STARTED
    )
    current = _make_attempt(
        db_session, cc_pair.id, settings.id, IndexingStatus.IN_PROGRESS
    )

    file_for_not_started = _stage_file(
        cc_pair.id, not_started.id, TEST_TENANT_ID, b"not started payload"
    )
    db_session.commit()

    deleted_count = reap_prior_attempt_staged_files(
        current_attempt_id=current.id,
        cc_pair_id=cc_pair.id,
        tenant_id=TEST_TENANT_ID,
        db_session=db_session,
    )

    assert deleted_count == 0

    from onyx.db.file_record import get_filerecord_by_file_id_optional

    db_session.expire_all()

    assert (
        get_filerecord_by_file_id_optional(file_for_not_started, db_session) is not None
    ), "NOT_STARTED attempt's staged file must NOT be reaped"

    # Cleanup
    from onyx.file_store.file_store import get_default_file_store

    fs = get_default_file_store()
    try:
        fs.delete_file(file_for_not_started)
    except Exception:
        pass


def test_sweep_reaps_orphan_with_no_owning_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    initialize_file_store: None,  # noqa: ARG001
) -> None:
    """Files tagged with an `index_attempt_id` that doesn't match any
    real `IndexAttempt` row (deleted by retention, never recorded) are
    still reapable — nothing is going to consume them."""
    from onyx.db.search_settings import get_current_search_settings

    settings = get_current_search_settings(db_session)
    current = _make_attempt(
        db_session, cc_pair.id, settings.id, IndexingStatus.IN_PROGRESS
    )

    # Use an attempt id that doesn't correspond to any IndexAttempt row.
    orphan_attempt_id = 999_999_999
    file_for_orphan = _stage_file(
        cc_pair.id, orphan_attempt_id, TEST_TENANT_ID, b"orphan payload"
    )
    db_session.commit()

    deleted_count = reap_prior_attempt_staged_files(
        current_attempt_id=current.id,
        cc_pair_id=cc_pair.id,
        tenant_id=TEST_TENANT_ID,
        db_session=db_session,
    )

    assert deleted_count == 1

    from onyx.db.file_record import get_filerecord_by_file_id_optional

    db_session.expire_all()
    assert (
        get_filerecord_by_file_id_optional(file_for_orphan, db_session) is None
    ), "orphaned staged file (no owning attempt) should be reaped"
    db_session.commit()
