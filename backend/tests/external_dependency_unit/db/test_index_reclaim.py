"""External dependency unit tests for the old-index-reclamation DB helpers +
set_new_search_settings consent/guard logic (reclaim helpers in db/search_settings.py;
the won't-port picker in db/connector_credential_pair.py; the name-reuse guard + consent
enforcement in server/manage/search_settings.py).

Covers the pure/isolated helpers (the happy-path transitions are exercised end-to-end
in test_index_reclaim_task.py; here we cover the guards + query logic):
- compute_wont_port_cc_pair_ids: INVALID always; PAUSED only under ACTIVE_ONLY;
  ACTIVE/DELETING never
- mark_cc_pairs_deleting_if_still_wont_port: atomic re-validation — spares a reactivated
  connector, returns only the ids transitioned
- transition guard: advance_to_soaking no-ops off its source state (won't re-stamp the
  soak anchor); clear_reclaim_intent resets the row
- fetch_reclaimable_past_settings: actionable PAST rows only, excludes BLOCKED, honors limit
- name-reuse guard: refuses a reindex whose new index_name still belongs to a not-yet-
  reclaimed PAST; find_unreclaimed_past_by_index_name decides which rows count
- consent: set_reclaim_intent stamps the PRESENT; drift enforcement rejects deleting a
  cc_pair the admin never acknowledged
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

import onyx.server.manage.search_settings as search_settings_api
from onyx.context.search.models import SavedSearchSettings
from onyx.db.connector_credential_pair import (
    compute_wont_port_cc_pair_ids,
    mark_cc_pairs_deleting_if_still_wont_port__no_commit,
)
from onyx.db.enums import (
    ConnectorCredentialPairStatus,
    EmbeddingPrecision,
    IndexModelStatus,
    IndexReclaimStatus,
    SwitchoverType,
)
from onyx.db.models import ConnectorCredentialPair, SearchSettings
from onyx.db.search_settings import (
    advance_to_soaking__no_commit,
    clear_reclaim_intent__no_commit,
    create_search_settings,
    fetch_reclaimable_past_settings,
    find_unreclaimed_past_by_index_name,
    get_current_search_settings,
    set_reclaim_intent_on_current__no_commit,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


def _make_settings(
    db_session: Session,
    reclaim_status: IndexReclaimStatus | None = None,
    *,
    index_name: str | None = None,
    status: IndexModelStatus = IndexModelStatus.PAST,
) -> SearchSettings:
    saved = SavedSearchSettings(
        model_name="test-reclaim-model",
        model_dim=128,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        provider_type=None,
        multipass_indexing=False,
        embedding_precision=EmbeddingPrecision.FLOAT,
        index_name=index_name or f"test_reclaim_{uuid4().hex[:8]}",
        enable_contextual_rag=False,
    )
    ss = create_search_settings(saved, db_session, status=status)
    if reclaim_status is not None:
        ss.reclaim_status = reclaim_status
        db_session.commit()
        db_session.refresh(ss)
    return ss


@pytest.fixture
def present_search_settings(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[SearchSettings, None, None]:
    """A PRESENT row for the tests that stamp reclaim intent. The db_session fixture
    creates none and get_current_search_settings raises without one, so these tests would
    otherwise depend on whatever the shared database holds. Reuses an existing row rather
    than adding a second, which would be a state no deployment reaches."""
    try:
        existing: SearchSettings | None = get_current_search_settings(db_session)
    except RuntimeError:
        existing = None
    if existing is not None:
        yield existing
        return

    created = _make_settings(db_session, None, status=IndexModelStatus.PRESENT)
    yield created
    db_session.rollback()
    db_session.delete(created)
    db_session.commit()


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


def test_mark_deleting_transitions_only_still_wont_port(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """The atomic fire-time transition moves only still-INVALID/PAUSED consented pairs to
    DELETING and returns exactly those; a reactivated (ACTIVE) one is spared. Fusing the
    re-check and the write into one conditional UPDATE closes the reactivation race."""
    invalid = _make_cc_pair_with_status(
        db_session, ConnectorCredentialPairStatus.INVALID
    )
    paused = _make_cc_pair_with_status(db_session, ConnectorCredentialPairStatus.PAUSED)
    reactivated = _make_cc_pair_with_status(
        db_session, ConnectorCredentialPairStatus.ACTIVE
    )
    try:
        transitioned = mark_cc_pairs_deleting_if_still_wont_port__no_commit(
            db_session, [invalid.id, paused.id, reactivated.id]
        )
        db_session.commit()
        for pair in (invalid, paused, reactivated):
            db_session.refresh(pair)

        assert set(transitioned) == {invalid.id, paused.id}
        assert invalid.status == ConnectorCredentialPairStatus.DELETING
        assert paused.status == ConnectorCredentialPairStatus.DELETING
        assert reactivated.status == ConnectorCredentialPairStatus.ACTIVE  # spared
    finally:
        for pair in (invalid, paused, reactivated):
            cleanup_cc_pair(db_session, pair)


# --- transitions ----------------------------------------------------------------


def test_advance_to_soaking_is_noop_off_source_state(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A repeat call on an already-SOAKING row must not re-stamp the anchor (which
    would extend the soak) — it returns False and leaves the row untouched."""
    ss = _make_settings(db_session)
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


def test_clear_reclaim_intent_resets_fields(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    ss = _make_settings(db_session)
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
    pending = _make_settings(db_session)
    deleting = _make_settings(db_session)
    blocked = _make_settings(db_session)
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
    rows = [_make_settings(db_session) for _ in range(3)]
    for row in rows:
        row.reclaim_status = IndexReclaimStatus.PENDING
    db_session.commit()
    try:
        assert len(fetch_reclaimable_past_settings(db_session, limit=1)) == 1
    finally:
        for row in rows:
            db_session.delete(row)
        db_session.commit()


# --- name-reuse guard (server/manage/search_settings.py) ------------------------


def test_guard_no_collision_is_noop(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A fresh index_name (no PAST row) passes the guard untouched."""
    search_settings_api._guard_index_name_reuse(
        db_session, f"test_no_collide_{uuid4().hex[:8]}"
    )


def test_guard_reclaimed_past_same_name_is_noop(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A same-named PAST already RECLAIMED (its index is gone) is safe to reuse."""
    name = f"test_reclaimed_reuse_{uuid4().hex[:8]}"
    ss = _make_settings(db_session, IndexReclaimStatus.RECLAIMED, index_name=name)
    try:
        search_settings_api._guard_index_name_reuse(db_session, name)
    finally:
        db_session.delete(ss)
        db_session.commit()


@pytest.mark.parametrize(
    "reclaim_status",
    [
        None,  # legacy pre-feature PAST row — its orphaned index still exists
        IndexReclaimStatus.PENDING,
        IndexReclaimStatus.SOAKING,
        IndexReclaimStatus.DELETING,
        IndexReclaimStatus.BLOCKED,
    ],
)
def test_guard_conflicts_while_index_unreclaimed(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    reclaim_status: IndexReclaimStatus | None,
) -> None:
    """Any collision whose index data is still present is refused — reclaim-tracked rows
    AND legacy NULL rows. The guard doesn't touch the row (no synchronous reclaim)."""
    name = f"test_collide_{uuid4().hex[:8]}"
    ss = _make_settings(db_session, reclaim_status, index_name=name)
    try:
        with pytest.raises(OnyxError) as exc:
            search_settings_api._guard_index_name_reuse(db_session, name)
        assert exc.value.error_code == OnyxErrorCode.CONFLICT
        assert "earlier reindex" in exc.value.detail
        db_session.refresh(ss)
        assert ss.reclaim_status == reclaim_status  # untouched
    finally:
        db_session.delete(ss)
        db_session.commit()


def test_find_unreclaimed_includes_blocked_and_legacy_excludes_reclaimed(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """The collision query treats anything but RECLAIMED as still-present: BLOCKED (its
    delete never finished) and a legacy NULL row (pre-feature orphan) both count; only
    RECLAIMED is gone."""
    name = f"test_find_unreclaimed_{uuid4().hex[:8]}"
    blocked = _make_settings(db_session, IndexReclaimStatus.BLOCKED, index_name=name)
    legacy = _make_settings(db_session, None, index_name=name)
    reclaimed = _make_settings(
        db_session, IndexReclaimStatus.RECLAIMED, index_name=name
    )
    try:
        found = {s.id for s in find_unreclaimed_past_by_index_name(db_session, name)}
        assert blocked.id in found
        assert legacy.id in found
        assert reclaimed.id not in found
    finally:
        for row in (blocked, legacy, reclaimed):
            db_session.delete(row)
        db_session.commit()


# --- consent resolution + capture -----------------------------------------------


def test_resolve_consent_nothing_wont_port_reclaims_only() -> None:
    """A plain reindex (nothing won't-port) reclaims the old index with no deletions —
    empty set, never None."""
    assert search_settings_api._resolve_consented_deletions(None, []) == []
    assert search_settings_api._resolve_consented_deletions([1], []) == []


def test_resolve_consent_no_acknowledgment_is_rejected() -> None:
    """Proceeding without consent would reclaim the old index anyway, so those connectors
    would lose their data unannounced."""
    with pytest.raises(OnyxError) as exc:
        search_settings_api._resolve_consented_deletions(None, [1, 2])
    assert exc.value.error_code == OnyxErrorCode.CONFLICT


def test_reindex_replaces_consent_set_left_by_a_superseded_reindex(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    present_search_settings: SearchSettings,  # noqa: ARG001
) -> None:
    """Both reindexes stamp the same PRESENT row, so the superseding one has to replace the
    earlier consent set. Inheriting it would let this swap delete connectors the admin only
    agreed to lose on the reindex that never happened."""
    invalid = _make_cc_pair_with_status(
        db_session, ConnectorCredentialPairStatus.INVALID
    )
    present = get_current_search_settings(db_session)
    try:
        set_reclaim_intent_on_current__no_commit(db_session, [101, 202])
        assert present.pending_cc_pair_deletions == [101, 202]

        consented = search_settings_api._resolve_reclaim_intent(
            db_session,
            SwitchoverType.REINDEX,
            acknowledged_wont_port_cc_pair_ids=[invalid.id],
        )
        assert consented == [invalid.id]
        set_reclaim_intent_on_current__no_commit(db_session, consented)

        assert present.pending_cc_pair_deletions == [invalid.id]
    finally:
        db_session.rollback()
        cleanup_cc_pair(db_session, invalid)


def test_resolve_consent_acknowledged_covers_returns_set() -> None:
    """Acknowledged covers the server set (incl. the safe drift where a consented connector
    re-activated) -> stamp the server set."""
    assert search_settings_api._resolve_consented_deletions([1, 2, 3], [1, 2]) == [1, 2]


def test_resolve_consent_rejects_unacknowledged_deletion() -> None:
    """A connector that became paused/invalid after the page loaded is in the server set
    but not acknowledged — deleting it would violate consent, so reject."""
    with pytest.raises(OnyxError) as exc:
        search_settings_api._resolve_consented_deletions([1], [1, 2])
    assert exc.value.error_code == OnyxErrorCode.CONFLICT


def test_set_reclaim_intent_marks_present_pending(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    present_search_settings: SearchSettings,  # noqa: ARG001
) -> None:
    """Consent capture stamps PENDING + the consented cc_pair ids on the current PRESENT
    (the future PAST). Asserted in-session then rolled back — never committed — so the
    shared singleton PRESENT row is left untouched."""
    present = get_current_search_settings(db_session)
    try:
        set_reclaim_intent_on_current__no_commit(db_session, [101, 202])
        assert present.reclaim_status == IndexReclaimStatus.PENDING
        assert present.pending_cc_pair_deletions == [101, 202]
    finally:
        db_session.rollback()
