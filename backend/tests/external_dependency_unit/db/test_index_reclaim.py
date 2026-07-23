"""External dependency unit tests for the old-index-reclamation DB helpers
(reclaim helpers in db/search_settings.py; the won't-port picker in
db/connector_credential_pair.py).

Covers the pure/isolated helpers introduced in PR1:
- compute_wont_port_cc_pair_ids: INVALID always; PAUSED only under ACTIVE_ONLY;
  ACTIVE/DELETING never
- the transition helpers (advance_to_soaking stamps the anchor; advance_to_deleting;
  record_failure bumps attempts then BLOCKS at the cap; clear_reclaim_intent resets)
- fetch_reclaimable_past_settings: actionable PAST rows only, excludes BLOCKED, honors limit

set_reclaim_intent_on_current targets the singleton PRESENT row and is covered by the
endpoint test in a later PR.
"""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.context.search.models import SavedSearchSettings
from onyx.db.connector_credential_pair import compute_wont_port_cc_pair_ids
from onyx.db.enums import (
    ConnectorCredentialPairStatus,
    EmbeddingPrecision,
    IndexModelStatus,
    IndexReclaimStatus,
    SwitchoverType,
)
from onyx.db.models import ConnectorCredentialPair, SearchSettings
from onyx.db.search_settings import (
    advance_to_deleting__no_commit,
    advance_to_soaking__no_commit,
    clear_reclaim_intent__no_commit,
    create_search_settings,
    fetch_reclaimable_past_settings,
    record_failure__no_commit,
)
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


def _make_past_settings(db_session: Session) -> SearchSettings:
    saved = SavedSearchSettings(
        model_name="test-reclaim-model",
        model_dim=128,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        provider_type=None,
        multipass_indexing=False,
        embedding_precision=EmbeddingPrecision.FLOAT,
        index_name=f"test_reclaim_{uuid4().hex[:8]}",
        enable_contextual_rag=False,
    )
    return create_search_settings(saved, db_session, status=IndexModelStatus.PAST)


def _make_cc_pair_with_status(
    db_session: Session, status: ConnectorCredentialPairStatus
) -> ConnectorCredentialPair:
    pair = make_cc_pair(db_session)
    pair.status = status
    db_session.commit()
    db_session.refresh(pair)
    return pair


# --- compute_wont_port_cc_pair_ids ---------------------------------------------


def test_invalid_cc_pair_wont_port_under_every_switchover(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    pair = _make_cc_pair_with_status(db_session, ConnectorCredentialPairStatus.INVALID)
    try:
        for switchover in SwitchoverType:
            ids = compute_wont_port_cc_pair_ids(db_session, switchover)
            assert pair.id in ids, f"INVALID must be in won't-port set for {switchover}"
    finally:
        cleanup_cc_pair(db_session, pair)


def test_paused_cc_pair_wont_port_only_under_active_only(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    pair = _make_cc_pair_with_status(db_session, ConnectorCredentialPairStatus.PAUSED)
    try:
        assert pair.id in compute_wont_port_cc_pair_ids(
            db_session, SwitchoverType.ACTIVE_ONLY
        )
        assert pair.id not in compute_wont_port_cc_pair_ids(
            db_session, SwitchoverType.REINDEX
        )
        assert pair.id not in compute_wont_port_cc_pair_ids(
            db_session, SwitchoverType.INSTANT
        )
    finally:
        cleanup_cc_pair(db_session, pair)


def test_active_and_deleting_cc_pairs_never_wont_port(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    active = _make_cc_pair_with_status(db_session, ConnectorCredentialPairStatus.ACTIVE)
    deleting = _make_cc_pair_with_status(
        db_session, ConnectorCredentialPairStatus.DELETING
    )
    try:
        for switchover in SwitchoverType:
            ids = compute_wont_port_cc_pair_ids(db_session, switchover)
            assert active.id not in ids
            assert deleting.id not in ids
    finally:
        cleanup_cc_pair(db_session, active)
        cleanup_cc_pair(db_session, deleting)


# --- transitions ----------------------------------------------------------------


def test_advance_to_soaking_stamps_anchor(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    ss = _make_past_settings(db_session)
    try:
        ss.reclaim_status = IndexReclaimStatus.PENDING
        db_session.commit()

        assert advance_to_soaking__no_commit(ss) is True
        db_session.commit()
        db_session.refresh(ss)

        assert ss.reclaim_status == IndexReclaimStatus.SOAKING
        assert ss.reclaim_stopped_reading_at is not None
        assert ss.reclaim_attempts == 0
    finally:
        db_session.delete(ss)
        db_session.commit()


def test_advance_to_soaking_is_noop_off_source_state(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A repeat call on an already-SOAKING row must not re-stamp the anchor (which
    would extend the soak) — it returns False and leaves the row untouched."""
    ss = _make_past_settings(db_session)
    try:
        ss.reclaim_status = IndexReclaimStatus.PENDING
        assert advance_to_soaking__no_commit(ss) is True  # PENDING -> SOAKING, stamps
        db_session.commit()
        db_session.refresh(ss)
        first_anchor = ss.reclaim_stopped_reading_at

        assert advance_to_soaking__no_commit(ss) is False  # already SOAKING
        db_session.commit()
        db_session.refresh(ss)
        assert ss.reclaim_stopped_reading_at == first_anchor
    finally:
        db_session.delete(ss)
        db_session.commit()


def test_advance_to_deleting(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    ss = _make_past_settings(db_session)
    try:
        ss.reclaim_status = IndexReclaimStatus.SOAKING
        db_session.commit()

        assert advance_to_deleting__no_commit(ss) is True
        db_session.commit()
        db_session.refresh(ss)

        assert ss.reclaim_status == IndexReclaimStatus.DELETING
        # Off-source no-op: cannot skip the soak from PENDING.
        assert advance_to_deleting__no_commit(ss) is False
    finally:
        db_session.delete(ss)
        db_session.commit()


def test_record_failure_bumps_then_blocks_at_cap(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    ss = _make_past_settings(db_session)
    try:
        ss.reclaim_status = IndexReclaimStatus.DELETING
        db_session.commit()

        # under the cap: not blocked
        blocked = record_failure__no_commit(ss, "boom", max_attempts=2)
        db_session.commit()
        db_session.refresh(ss)
        assert blocked is False
        assert ss.reclaim_attempts == 1
        assert ss.reclaim_last_error == "boom"
        assert ss.reclaim_status == IndexReclaimStatus.DELETING

        # reaches the cap: BLOCKED
        blocked = record_failure__no_commit(ss, "boom again", max_attempts=2)
        db_session.commit()
        db_session.refresh(ss)
        assert blocked is True
        assert ss.reclaim_attempts == 2
        assert ss.reclaim_status == IndexReclaimStatus.BLOCKED
    finally:
        db_session.delete(ss)
        db_session.commit()


def test_clear_reclaim_intent_resets_fields(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    ss = _make_past_settings(db_session)
    try:
        ss.reclaim_status = IndexReclaimStatus.PENDING
        ss.pending_cc_pair_deletions = [1, 2, 3]
        ss.reclaim_attempts = 4
        ss.reclaim_last_error = "prior"
        db_session.commit()

        clear_reclaim_intent__no_commit(db_session, ss.id)
        db_session.commit()
        db_session.refresh(ss)

        assert ss.reclaim_status is None
        assert ss.pending_cc_pair_deletions is None
        assert ss.reclaim_attempts == 0
        assert ss.reclaim_last_error is None
        assert ss.reclaim_stopped_reading_at is None
    finally:
        db_session.delete(ss)
        db_session.commit()


# --- fetch_reclaimable_past_settings --------------------------------------------


def test_fetch_reclaimable_includes_actionable_excludes_blocked(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    pending = _make_past_settings(db_session)
    deleting = _make_past_settings(db_session)
    blocked = _make_past_settings(db_session)
    pending.reclaim_status = IndexReclaimStatus.PENDING
    deleting.reclaim_status = IndexReclaimStatus.DELETING
    blocked.reclaim_status = IndexReclaimStatus.BLOCKED
    db_session.commit()
    try:
        found = {s.id for s in fetch_reclaimable_past_settings(db_session, limit=100)}
        assert pending.id in found
        assert deleting.id in found
        assert blocked.id not in found  # parked, excluded
    finally:
        for row in (pending, deleting, blocked):
            db_session.delete(row)
        db_session.commit()


def test_fetch_reclaimable_respects_limit(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    rows = [_make_past_settings(db_session) for _ in range(3)]
    for row in rows:
        row.reclaim_status = IndexReclaimStatus.PENDING
    db_session.commit()
    try:
        assert len(fetch_reclaimable_past_settings(db_session, limit=1)) == 1
    finally:
        for row in rows:
            db_session.delete(row)
        db_session.commit()
