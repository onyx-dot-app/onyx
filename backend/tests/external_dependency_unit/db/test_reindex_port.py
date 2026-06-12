"""External dependency unit tests for the reindexing-port DB layer.

Scoped to behavior/invariants worth guarding (the column existence + defaults are
covered by applying the migration, which this repo does not test programmatically):
- the partial-unique "one active attempt per (cc_pair, FUTURE)" index — and that
  its predicate matches the stored (uppercase) enum name, not the value
- mark_document_synced_secondary_pending sets the flag (and clears needs-sync),
  and a later mark_document_as_synced clears it again
"""

from collections.abc import Generator

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.document import mark_document_as_modified
from onyx.db.document import mark_document_as_synced
from onyx.db.document import mark_document_synced_secondary_pending
from onyx.db.enums import PortAttemptStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.models import PortAttempt
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
