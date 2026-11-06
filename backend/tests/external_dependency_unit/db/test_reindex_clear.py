"""Tests for the reindex swap clear (onyx.db.reindex_clear and the document
helpers it drives): what loses its content hash or becomes needs-sync at the swap."""

from collections.abc import Generator
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.document import (
    clear_content_hash_for_cc_pair_since__no_commit,
    clear_content_hash_for_failed_documents__no_commit,
    mark_secondary_pending_documents_needs_sync__no_commit,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt import create_synthetic_seed_attempt
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    IndexAttempt,
    IndexAttemptError,
    SearchSettings,
)
from onyx.db.port_attempt import create_port_attempt
from onyx.db.reindex_clear import (
    _CLEAR_MARGIN,
    PairClearBounds,
    get_pair_clear_bounds,
)
from onyx.db.search_settings import get_current_search_settings
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    cleanup_cc_pair_and_future,
    make_cc_pair,
    make_future_search_settings,
    seed_cc_pair_documents,
)

_DOC_PREFIX = "cleardoc-"


@pytest.fixture
def pair_and_future(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[ConnectorCredentialPair, SearchSettings], None, None]:
    pair = make_cc_pair(db_session)
    future = make_future_search_settings(db_session, use_port_flow=True)
    try:
        yield pair, future
    finally:
        cleanup_cc_pair_and_future(db_session, pair, future.id, doc_prefix=_DOC_PREFIX)


def _seed(
    db_session: Session, pair: ConnectorCredentialPair, future_id: int
) -> datetime:
    """Seeds the pair like set_new_search_settings does; returns the seed's creation
    time, which is when the reindex began for the pair."""
    seed_id = create_synthetic_seed_attempt(pair.id, future_id, db_session, 0.0)
    db_session.commit()
    seed = db_session.get(IndexAttempt, seed_id)
    assert seed is not None
    return seed.time_created


def _attempt(
    db_session: Session,
    pair: ConnectorCredentialPair,
    search_settings_id: int,
    status: IndexingStatus,
    poll_range_end: datetime | None = None,
    *,
    is_backfill: bool = False,
) -> IndexAttempt:
    now = datetime.now(tz=timezone.utc)
    row = IndexAttempt(
        connector_credential_pair_id=pair.id,
        search_settings_id=search_settings_id,
        status=status,
        from_beginning=False,
        is_backfill=is_backfill,
        poll_range_end=poll_range_end,
        time_started=now,
        time_finished=now if status.is_terminal() else None,
    )
    db_session.add(row)
    db_session.commit()
    return row


def _docs(db_session: Session, pair: ConnectorCredentialPair, count: int) -> list[str]:
    return seed_cc_pair_documents(
        db_session, pair, count, prefix=_DOC_PREFIX, unique=True
    )


def _set(db_session: Session, doc_id: str, **fields: object) -> None:
    doc = db_session.get(Document, doc_id)
    assert doc is not None
    for name, value in fields.items():
        setattr(doc, name, value)
    db_session.commit()


def _hashes(db_session: Session, doc_ids: list[str]) -> dict[str, str | None]:
    db_session.expire_all()
    rows = db_session.execute(
        select(Document.id, Document.content_hash).where(Document.id.in_(doc_ids))
    )
    return {row.id: row.content_hash for row in rows}


def _bounds(
    db_session: Session, pair: ConnectorCredentialPair, future: SearchSettings
) -> dict[int, PairClearBounds]:
    db_session.expire_all()
    return get_pair_clear_bounds(db_session, future, [pair.id])


def test_clear_from_follows_futures_last_successful_poll(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, future = pair_and_future
    since = _seed(db_session, pair, future.id)
    success, errors = IndexingStatus.SUCCESS, IndexingStatus.COMPLETED_WITH_ERRORS

    # A window end within the margin of the reindex start clears from the start.
    _attempt(db_session, pair, future.id, success, since + timedelta(minutes=10))
    bounds = _bounds(db_session, pair, future)[pair.id]
    assert bounds.future_covered_through == since + timedelta(minutes=10)
    assert bounds.clear_from == since

    later = since + timedelta(hours=3)
    latest = since + timedelta(hours=4)
    # Not resume points: a failure, a backfill (own window, cursor untouched).
    _attempt(db_session, pair, future.id, IndexingStatus.FAILED, latest)
    _attempt(db_session, pair, future.id, success, latest, is_backfill=True)
    # Completed with errors moves the cursor like a success does.
    _attempt(db_session, pair, future.id, errors, later)
    bounds = _bounds(db_session, pair, future)[pair.id]
    assert bounds.since == since
    assert bounds.future_covered_through == later
    assert bounds.clear_from == later - _CLEAR_MARGIN
    assert bounds.push_based is False

    # Completed with an unresolved folder-level error: not a resume point, since
    # that folder's documents may never have reached FUTURE. Resolved: it is.
    entity_failed = _attempt(db_session, pair, future.id, errors, latest)
    error = IndexAttemptError(
        index_attempt_id=entity_failed.id,
        connector_credential_pair_id=pair.id,
        entity_id="folder-1",
        failure_message="folder unreachable",
    )
    db_session.add(error)
    db_session.commit()
    try:
        assert (
            _bounds(db_session, pair, future)[pair.id].future_covered_through == later
        )
        error.is_resolved = True
        db_session.commit()
        assert (
            _bounds(db_session, pair, future)[pair.id].future_covered_through == latest
        )
    finally:
        db_session.delete(error)
        db_session.commit()


def test_clear_from_falls_back_to_the_reindex_start(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    """No successful FUTURE poll: clear from the reindex start (seed, else port)."""
    pair, future = pair_and_future
    assert get_pair_clear_bounds(db_session, future, []) == {}
    # Neither seed nor port: clear everything rather than nothing.
    assert _bounds(db_session, pair, future)[
        pair.id
    ].clear_from == datetime.fromtimestamp(0, tz=timezone.utc)

    port = create_port_attempt(db_session, pair.id, future.id)
    db_session.commit()
    bounds = _bounds(db_session, pair, future)[pair.id]
    assert bounds.future_covered_through is None
    assert bounds.since == port.time_created
    assert bounds.clear_from == port.time_created

    seed_created = _seed(db_session, pair, future.id)
    bounds = _bounds(db_session, pair, future)[pair.id]
    assert bounds.since == seed_created
    assert bounds.clear_from == seed_created

    ingestion = make_cc_pair(db_session, source=DocumentSource.INGESTION_API)
    try:
        by_pair = get_pair_clear_bounds(db_session, future, [pair.id, ingestion.id, -1])
        assert set(by_pair) == {pair.id, ingestion.id}
        assert by_pair[ingestion.id].push_based is True
    finally:
        cleanup_cc_pair(db_session, ingestion)


def test_since_clear_touches_only_this_pairs_docs_at_or_after_the_bound(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, _ = pair_and_future
    other = make_cc_pair(db_session)
    try:
        bound = datetime.now(tz=timezone.utc)
        before, after = _docs(db_session, pair, 2)
        (other_doc,) = _docs(db_session, other, 1)
        for doc_id, modified in (
            (before, bound - timedelta(minutes=1)),
            (after, bound),
            (other_doc, bound + timedelta(minutes=1)),
        ):
            _set(db_session, doc_id, content_hash="h", last_modified=modified)

        cleared = clear_content_hash_for_cc_pair_since__no_commit(
            db_session, pair.connector_id, pair.credential_id, bound
        )
        db_session.commit()
        assert cleared == 1
        assert _hashes(db_session, [before, after, other_doc]) == {
            before: "h",
            after: None,
            other_doc: "h",
        }
    finally:
        cleanup_cc_pair(db_session, other)


def test_skip_locked_leaves_rows_another_transaction_holds(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    """The swap's delta pass never waits on a row an indexing batch holds."""
    pair, _ = pair_and_future
    bound = datetime.now(tz=timezone.utc)
    held, free = _docs(db_session, pair, 2)
    for doc_id in (held, free):
        _set(db_session, doc_id, content_hash="h", last_modified=bound)

    with get_session_with_current_tenant() as other_session:
        other_session.execute(
            select(Document).where(Document.id == held).with_for_update()
        )
        cleared = clear_content_hash_for_cc_pair_since__no_commit(
            db_session, pair.connector_id, pair.credential_id, bound, skip_locked=True
        )
        db_session.commit()
        other_session.rollback()
    assert cleared == 1
    assert _hashes(db_session, [held, free]) == {held: "h", free: None}

    # Lock gone: a plain pass clears the rest.
    cleared = clear_content_hash_for_cc_pair_since__no_commit(
        db_session, pair.connector_id, pair.credential_id, bound
    )
    db_session.commit()
    assert cleared == 1 and _hashes(db_session, [held]) == {held: None}


def test_failed_documents_clear_hits_error_rows_of_these_settings_only(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, future = pair_and_future
    now = datetime.now(tz=timezone.utc)
    errors = IndexingStatus.COMPLETED_WITH_ERRORS
    future_attempt = _attempt(db_session, pair, future.id, errors, now)
    present_id = get_current_search_settings(db_session).id
    present_attempt = _attempt(db_session, pair, present_id, errors, now)
    resolved, unresolved, present_only, untouched = _docs(db_session, pair, 4)
    for doc_id in (resolved, unresolved, present_only, untouched):
        _set(db_session, doc_id, content_hash="h", last_modified=now)

    def _error(
        attempt: IndexAttempt, document_id: str | None, *, is_resolved: bool = False
    ) -> IndexAttemptError:
        return IndexAttemptError(
            index_attempt_id=attempt.id,
            connector_credential_pair_id=pair.id,
            document_id=document_id,
            entity_id=None if document_id else "folder-1",
            failure_message="embedding failed",
            is_resolved=is_resolved,
        )

    errors = [
        _error(future_attempt, resolved, is_resolved=True),
        _error(future_attempt, unresolved),
        _error(future_attempt, None),
        _error(present_attempt, present_only),
    ]
    db_session.add_all(errors)
    db_session.commit()
    try:
        cleared = clear_content_hash_for_failed_documents__no_commit(
            db_session, future.id
        )
        db_session.commit()
        assert cleared == 2
        assert _hashes(db_session, [resolved, unresolved, present_only, untouched]) == {
            resolved: None,
            unresolved: None,
            present_only: "h",
            untouched: "h",
        }
    finally:
        for error in errors:
            db_session.delete(error)
        db_session.commit()


def test_needs_sync_flip_turns_the_flag_into_a_plain_needs_sync(
    db_session: Session, pair_and_future: tuple[ConnectorCredentialPair, SearchSettings]
) -> None:
    pair, _ = pair_and_future
    synced_at = datetime.now(tz=timezone.utc)
    flagged, plain = _docs(db_session, pair, 2)
    _set(db_session, flagged, secondary_only_sync_pending=True, last_synced=synced_at)
    _set(db_session, plain, secondary_only_sync_pending=False, last_synced=synced_at)

    flipped = mark_secondary_pending_documents_needs_sync__no_commit(
        db_session, pair.connector_id, pair.credential_id
    )
    db_session.commit()
    assert flipped == 1

    db_session.expire_all()
    rows = {
        row.id: (row.secondary_only_sync_pending, row.last_synced)
        for row in db_session.scalars(
            select(Document).where(Document.id.in_([flagged, plain]))
        )
    }
    assert rows[flagged] == (False, None)
    assert rows[plain][0] is False and rows[plain][1] is not None
