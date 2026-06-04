"""External dependency unit tests for the reindexing-port DB layer.

Scoped to behavior/invariants worth guarding (the column existence + defaults are
covered by applying the migration, which this repo does not test programmatically):
- the partial-unique "one active attempt per (cc_pair, FUTURE)" index — and that
  its predicate matches the stored (uppercase) enum name, not the value
- the PortAttempt lifecycle helpers (create -> in_progress -> cursor -> terminal)
  and first-terminal-write-wins
- mark_document_synced_secondary_pending sets the flag (and clears needs-sync),
  and a later mark_document_as_synced clears it again
- the synthetic seed: writer row shape, seed-blind filtering (a seed must not count
  toward the swap or masquerade as the poll cursor), and the gated should_index
  FUTURE branch (legacy once-only vs port-flow continuous)
"""

from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.docprocessing.utils import should_index
from onyx.context.search.models import SavedSearchSettings
from onyx.db.connector_credential_pair import get_last_successful_attempt_poll_range_end
from onyx.db.document import mark_document_as_modified
from onyx.db.document import mark_document_as_synced
from onyx.db.document import mark_document_synced_secondary_pending
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.enums import PortAttemptStatus
from onyx.db.index_attempt import (
    count_unique_active_cc_pairs_with_successful_index_attempts,
)
from onyx.db.index_attempt import count_unique_cc_pairs_with_successful_index_attempts
from onyx.db.index_attempt import create_synthetic_seed_attempt
from onyx.db.index_attempt import get_latest_successful_index_attempt_for_cc_pair_id
from onyx.db.index_attempt import mock_successful_index_attempt
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.models import IndexAttempt
from onyx.db.models import PortAttempt
from onyx.db.models import SearchSettings
from onyx.db.port_attempt import commit_port_cursor
from onyx.db.port_attempt import create_port_attempt
from onyx.db.port_attempt import get_active_port_attempt
from onyx.db.port_attempt import mark_port_failed
from onyx.db.port_attempt import mark_port_in_progress
from onyx.db.port_attempt import mark_port_succeeded
from onyx.db.search_settings import create_search_settings
from onyx.db.search_settings import get_current_search_settings
from onyx.kg.models import KGStage
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
        db_session.rollback()
        db_session.query(PortAttempt).filter(PortAttempt.cc_pair_id == pair.id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def test_port_attempt_active_unique_constraint(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """At most one active (NOT_STARTED/IN_PROGRESS) attempt per (cc_pair, FUTURE);
    terminal rows may coexist. Also guards the index predicate against the stored
    enum casing (uppercase name) — a lowercase predicate would silently no-op."""
    ss = get_current_search_settings(db_session)

    db_session.add(
        PortAttempt(
            cc_pair_id=cc_pair.id,
            search_settings_id=ss.id,
            status=PortAttemptStatus.IN_PROGRESS,
        )
    )
    db_session.commit()

    db_session.add(
        PortAttempt(
            cc_pair_id=cc_pair.id,
            search_settings_id=ss.id,
            status=PortAttemptStatus.NOT_STARTED,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    # a terminal attempt for the same pair is allowed (outside the predicate)
    db_session.add(
        PortAttempt(
            cc_pair_id=cc_pair.id,
            search_settings_id=ss.id,
            status=PortAttemptStatus.SUCCESS,
        )
    )
    db_session.commit()

    active = (
        db_session.query(PortAttempt)
        .filter(
            PortAttempt.cc_pair_id == cc_pair.id,
            PortAttempt.status.in_(
                [PortAttemptStatus.NOT_STARTED, PortAttemptStatus.IN_PROGRESS]
            ),
        )
        .count()
    )
    assert active == 1


def test_mark_secondary_pending_then_synced_clears_it(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    doc_id = "test-secondary-pending-doc"
    db_session.add(
        DbDocument(id=doc_id, semantic_id=doc_id, kg_stage=KGStage.NOT_STARTED)
    )
    db_session.commit()
    try:
        mark_document_as_modified(doc_id, db_session)  # needs-sync

        # PRESENT synced but FUTURE missing -> defer
        mark_document_synced_secondary_pending(doc_id, db_session)
        db_session.expire_all()
        row = db_session.query(DbDocument).filter(DbDocument.id == doc_id).one()
        assert row.last_synced is not None and row.last_modified is not None
        assert row.last_synced >= row.last_modified  # needs-sync cleared
        assert row.secondary_only_sync_pending is True

        # a later full sync reaches FUTURE -> flag flips back to False
        mark_document_as_synced(doc_id, db_session)
        db_session.expire_all()
        row = db_session.query(DbDocument).filter(DbDocument.id == doc_id).one()
        assert row.secondary_only_sync_pending is False
    finally:
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()


def test_mark_secondary_pending_raises_on_missing_document(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    with pytest.raises(ValueError):
        mark_document_synced_secondary_pending("does-not-exist", db_session)


def test_port_attempt_lifecycle_helpers(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """create -> in_progress -> cursor commit -> success; get_active tracks the
    active attempt and stops returning it once the attempt is terminal."""
    ss = get_current_search_settings(db_session)

    attempt = create_port_attempt(db_session, cc_pair.id, ss.id, celery_task_id="t-1")
    attempt_id = attempt.id
    assert attempt.status == PortAttemptStatus.NOT_STARTED
    assert get_active_port_attempt(db_session, cc_pair.id, ss.id) is not None

    mark_port_in_progress(db_session, attempt_id, celery_task_id="t-1")
    commit_port_cursor(
        db_session, attempt_id, last_processed_doc_id="doc-50", docs_ported=50
    )
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.status == PortAttemptStatus.IN_PROGRESS
    assert row.last_processed_doc_id == "doc-50"
    assert row.docs_ported == 50
    assert row.time_started is not None and row.last_progress_time is not None

    # a second cursor commit advances the (absolute) cumulative counter
    commit_port_cursor(
        db_session, attempt_id, last_processed_doc_id="doc-80", docs_ported=80
    )
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.last_processed_doc_id == "doc-80" and row.docs_ported == 80

    mark_port_succeeded(db_session, attempt_id)
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    assert row.status == PortAttemptStatus.SUCCESS
    assert row.time_completed is not None
    # terminal attempts are no longer "active"
    assert get_active_port_attempt(db_session, cc_pair.id, ss.id) is None


def test_port_attempt_terminal_is_first_write_wins(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """A terminal attempt ignores later transitions, so a late task SUCCESS can't
    clobber a watchdog FAILED (the row lock makes this deterministic)."""
    ss = get_current_search_settings(db_session)
    attempt = create_port_attempt(db_session, cc_pair.id, ss.id)
    mark_port_in_progress(db_session, attempt.id)

    mark_port_failed(db_session, attempt.id, error_msg="stalled")
    mark_port_succeeded(db_session, attempt.id)  # no-op: already terminal

    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt.id)
    assert row is not None
    assert row.status == PortAttemptStatus.FAILED
    assert row.error_msg == "stalled"


@pytest.fixture
def cc_pair_and_future(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[ConnectorCredentialPair, int], None, None]:
    """A cc_pair plus an isolated FUTURE SearchSettings (unique index_name) so the
    global count/cursor helpers see only this test's attempts."""
    pair = make_cc_pair(db_session)
    present = get_current_search_settings(db_session)
    saved = SavedSearchSettings.from_db_model(present).model_copy(
        update={"index_name": f"test_future_{uuid4().hex[:8]}"}
    )
    future = create_search_settings(saved, db_session, status=IndexModelStatus.FUTURE)
    future_id = future.id
    try:
        yield pair, future_id
    finally:
        db_session.rollback()
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.query(SearchSettings).filter(SearchSettings.id == future_id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def test_create_synthetic_seed_attempt(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    epoch = 1_700_000_000.0

    seed_id = create_synthetic_seed_attempt(
        cc_pair.id, future_id, poll_range_end=epoch, db_session=db_session
    )
    db_session.expire_all()
    seed = db_session.get(IndexAttempt, seed_id)
    assert seed is not None
    assert seed.status == IndexingStatus.SUCCESS
    assert seed.is_synthetic_seed is True
    # time_started == time_created so the swap criterion's "real attempt after the
    # port" comparison is well-defined for the run that supersedes the seed
    assert seed.time_started is not None and seed.time_created is not None
    assert seed.time_started == seed.time_created
    assert seed.poll_range_end is not None
    assert seed.poll_range_end.timestamp() == epoch


def test_seed_excluded_from_latest_and_counts(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None

    # only a synthetic seed exists
    create_synthetic_seed_attempt(
        cc_pair.id, future_id, poll_range_end=1000.0, db_session=db_session
    )
    db_session.expire_all()
    assert (
        count_unique_cc_pairs_with_successful_index_attempts(future_id, db_session) == 0
    )
    assert (
        count_unique_active_cc_pairs_with_successful_index_attempts(
            future_id, db_session
        )
        == 0
    )
    assert (
        get_latest_successful_index_attempt_for_cc_pair_id(
            db_session, cc_pair.id, secondary_index=True
        )
        is None
    )
    # the seed's cursor is invisible to the seed-blind helper -> earliest fallback
    assert (
        get_last_successful_attempt_poll_range_end(
            cc_pair.id, 42.0, future_ss, db_session
        )
        == 42.0
    )

    # a real SUCCESS attempt IS counted and returned
    real_id = mock_successful_index_attempt(
        cc_pair.id, future_id, docs_indexed=5, db_session=db_session
    )
    db_session.expire_all()
    assert (
        count_unique_cc_pairs_with_successful_index_attempts(future_id, db_session) == 1
    )
    latest = get_latest_successful_index_attempt_for_cc_pair_id(
        db_session, cc_pair.id, secondary_index=True
    )
    assert latest is not None and latest.id == real_id


def test_should_index_future_gated_on_port_flow(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    # make the connector pollable on the continuous path
    cc_pair.connector.refresh_freq = 60
    # a real SUCCESS attempt, old enough to be re-pollable
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.add(
        IndexAttempt(
            connector_credential_pair_id=cc_pair.id,
            search_settings_id=future_id,
            from_beginning=True,
            status=IndexingStatus.SUCCESS,
            time_started=old,
            time_updated=old,
        )
    )
    db_session.commit()
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None

    # legacy (flag off): one success is enough -> don't index again
    future_ss.use_port_flow = False
    db_session.commit()
    assert (
        should_index(
            cc_pair, future_ss, secondary_index_building=True, db_session=db_session
        )
        is False
    )

    # port flow (flag on): polls continuously -> index again
    future_ss.use_port_flow = True
    db_session.commit()
    assert (
        should_index(
            cc_pair, future_ss, secondary_index_building=True, db_session=db_session
        )
        is True
    )
