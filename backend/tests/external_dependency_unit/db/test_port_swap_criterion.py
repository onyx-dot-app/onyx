"""External dependency unit tests for the port-aware swap criterion (T7/D8).

The port-flow branch of `check_and_perform_index_swap` swaps on four conditions
rather than the legacy successful-index count: every required cc_pair's port is
SUCCESS, a real (non-seed) FUTURE index attempt landed after the port, nothing is
in progress, and the deferred metadata-sync backlog has drained. The push-based
Ingestion pair is gated on its port only (it never runs a connector index attempt).
Mode C (INSTANT) swaps immediately; the legacy (flag-off) path is untouched.

`_port_swap_ready` is tested directly with an explicit required list (isolated
from other cc_pairs); the `check_and_perform_index_swap` cases patch
`_perform_index_swap` so no destructive real swap runs.

The two-phase-cancel tests at the bottom cover the port_attempt DB contract that
keeps connector deletion the last writer: `request_port_cancel` leaves an IN_PROGRESS
port active until the task acks CANCELED after its last write, cancels a NOT_STARTED
port outright, `mark_port_in_progress` starts only NOT_STARTED (no double writer), and
`cancel_active_port_attempts` (the swap path) uses the same two-phase rule.
"""

from collections.abc import Generator
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db import swap_index
from onyx.db.document import mark_document_synced_secondary_pending
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import PortAttemptStatus
from onyx.db.enums import SwitchoverType
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import PortAttempt
from onyx.db.models import SearchSettings
from onyx.db.port_attempt import cancel_active_port_attempts
from onyx.db.port_attempt import create_port_attempt
from onyx.db.port_attempt import get_active_port_attempt
from onyx.db.port_attempt import mark_port_canceled
from onyx.db.port_attempt import mark_port_in_progress
from onyx.db.port_attempt import mark_port_succeeded
from onyx.db.port_attempt import request_port_cancel
from onyx.db.swap_index import _port_swap_ready
from onyx.db.swap_index import _required_cc_pairs_for_switchover
from onyx.db.swap_index import check_and_perform_index_swap
from onyx.kg.models import KGStage
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair_and_future
from tests.external_dependency_unit.indexing_helpers import make_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_future_search_settings

_PENDING_DOC_PREFIX = "swapdoc-"


@pytest.fixture
def cc_pair_and_future(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[ConnectorCredentialPair, int], None, None]:
    pair = make_cc_pair(db_session)
    future_id = make_future_search_settings(db_session).id
    try:
        yield pair, future_id
    finally:
        cleanup_cc_pair_and_future(
            db_session, pair, future_id, doc_prefix=_PENDING_DOC_PREFIX
        )


def _make_success_port(db_session: Session, cc_pair_id: int, ss_id: int) -> datetime:
    """A SUCCESS port attempt; returns its (non-None) completion time so callers can
    order index attempts relative to it."""
    attempt = create_port_attempt(db_session, cc_pair_id, ss_id)
    mark_port_in_progress(db_session, attempt.id)
    mark_port_succeeded(db_session, attempt.id)
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt.id)
    assert row is not None and row.time_completed is not None
    return row.time_completed


def test_port_swap_ready_when_port_succeeded(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A successful port (no active attempt) with a drained sync backlog is ready —
    no post-port connector index attempt is required."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    _make_success_port(db_session, cc_pair.id, future_id)
    assert _port_swap_ready(db_session, future_ss, [cc_pair]) is True


def test_port_swap_blocks_when_no_port(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    assert _port_swap_ready(db_session, future_ss, [cc_pair]) is False


def test_port_swap_blocks_on_active_port(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    attempt = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, attempt.id)  # active, not terminal
    assert _port_swap_ready(db_session, future_ss, [cc_pair]) is False


def test_port_swap_blocks_on_pending_sync_backlog(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    _make_success_port(db_session, cc_pair.id, future_id)
    # A deferred-sync doc owned by the ported cc_pair remains -> the scoped backlog
    # gate fails. The count JOINs through DocumentByConnectorCredentialPair, so the
    # doc must be linked to the cc_pair or it's invisible to the query.
    doc_id = f"{_PENDING_DOC_PREFIX}pending"
    db_session.add(
        DbDocument(id=doc_id, semantic_id=doc_id, kg_stage=KGStage.NOT_STARTED)
    )
    db_session.flush()
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=doc_id,
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
            has_been_indexed=True,
        )
    )
    db_session.commit()
    mark_document_synced_secondary_pending(doc_id, db_session)
    assert _port_swap_ready(db_session, future_ss, [cc_pair]) is False


def test_port_swap_blocks_on_unfinished_ingestion_port(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """check_for_port ports the push-based Ingestion pair too, and the port is its
    only path into FUTURE — so an unfinished Ingestion port must hold the swap, even
    though it never yields a FUTURE index attempt."""
    _standard, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    ingestion = make_cc_pair(db_session, source=DocumentSource.INGESTION_API)
    try:
        attempt = create_port_attempt(db_session, ingestion.id, future_id)
        mark_port_in_progress(db_session, attempt.id)  # active -> not done
        assert _port_swap_ready(db_session, future_ss, [ingestion]) is False
    finally:
        db_session.query(PortAttempt).filter(
            PortAttempt.cc_pair_id == ingestion.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, ingestion)


def test_port_swap_ready_ingestion_skips_index_attempt(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """Once its port succeeds, the Ingestion pair is ready with NO FUTURE index
    attempt — the post-port index condition standard connectors face is skipped."""
    _standard, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    ingestion = make_cc_pair(db_session, source=DocumentSource.INGESTION_API)
    try:
        _make_success_port(db_session, ingestion.id, future_id)
        assert _port_swap_ready(db_session, future_ss, [ingestion]) is True
    finally:
        db_session.query(PortAttempt).filter(
            PortAttempt.cc_pair_id == ingestion.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, ingestion)


def test_required_cc_pairs_for_switchover_scopes_by_mode(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    active = make_cc_pair(db_session)
    paused = make_cc_pair(db_session)
    deleting = make_cc_pair(db_session)
    paused.status = ConnectorCredentialPairStatus.PAUSED
    deleting.status = ConnectorCredentialPairStatus.DELETING
    db_session.commit()
    all_ccp = [active, paused, deleting]
    try:
        # REINDEX uses indexable_statuses (incl PAUSED, excl DELETING)
        reindex = _required_cc_pairs_for_switchover(
            db_session, all_ccp, SwitchoverType.REINDEX
        )
        assert {c.id for c in reindex} == {active.id, paused.id}

        # ACTIVE_ONLY uses active_statuses (excl PAUSED + DELETING)
        active_only = _required_cc_pairs_for_switchover(
            db_session, all_ccp, SwitchoverType.ACTIVE_ONLY
        )
        assert {c.id for c in active_only} == {active.id}
    finally:
        for cc_pair in (active, paused, deleting):
            cleanup_cc_pair(db_session, cc_pair)


def test_swap_holds_when_port_not_ready(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    future_ss.switchover_type = SwitchoverType.REINDEX  # not INSTANT -> gated
    db_session.commit()

    with patch.object(swap_index, "_perform_index_swap") as mock_swap:
        result = check_and_perform_index_swap(db_session)

    assert result is None
    mock_swap.assert_not_called()


def test_mode_c_swaps_immediately(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    _, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    future_ss.switchover_type = SwitchoverType.INSTANT
    db_session.commit()

    sentinel = object()
    with patch.object(
        swap_index, "_perform_index_swap", return_value=sentinel
    ) as mock_swap:
        result = check_and_perform_index_swap(db_session)

    assert result is sentinel
    mock_swap.assert_called_once()
    # port-flow INSTANT swaps live WITHOUT the wipe: the port backfills the new
    # index, so cleanup_documents would destroy live data — the swap omits it.
    assert mock_swap.call_args.kwargs.get("cleanup_documents") is not True


def test_legacy_path_does_not_consult_port_helpers(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    _, future_id = cc_pair_and_future  # use_port_flow stays False (default)
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.switchover_type = SwitchoverType.REINDEX  # non-INSTANT legacy path
    db_session.commit()

    # Asserts one thing: the legacy path never consults the port helper. The swap
    # decision itself is covered in test_index_swap_workflow.py; _perform_index_swap
    # is patched only to keep a swap off the real DB/index.
    with (
        patch.object(
            swap_index,
            "_port_swap_ready",
            side_effect=AssertionError("legacy must not use the port path"),
        ) as mock_ready,
        patch.object(swap_index, "_perform_index_swap"),
    ):
        check_and_perform_index_swap(db_session)

    mock_ready.assert_not_called()


# --- two-phase cancel: the port_attempt contract that keeps deletion the last writer


def _port_row(db_session: Session, attempt_id: int) -> PortAttempt:
    db_session.expire_all()
    row = db_session.get(PortAttempt, attempt_id)
    assert row is not None
    return row


def test_request_cancel_not_started_terminalizes(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """NOT_STARTED: cancel outright so a waiting deletion can proceed — a mere flag
    would wedge it (NOT_STARTED is invisible to the stall watchdog)."""
    cc_pair, future_id = cc_pair_and_future
    attempt = create_port_attempt(db_session, cc_pair.id, future_id)

    request_port_cancel(db_session, attempt.id)

    assert _port_row(db_session, attempt.id).status == PortAttemptStatus.CANCELED
    assert get_active_port_attempt(db_session, cc_pair.id, future_id) is None


def test_request_cancel_in_progress_flags_but_stays_active(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """IN_PROGRESS: flag only, row stays active — a waiter must keep blocking until
    the task itself acks after its last write."""
    cc_pair, future_id = cc_pair_and_future
    attempt = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, attempt.id)

    request_port_cancel(db_session, attempt.id)

    row = _port_row(db_session, attempt.id)
    assert row.status == PortAttemptStatus.IN_PROGRESS
    assert row.cancel_requested is True
    still_active = get_active_port_attempt(db_session, cc_pair.id, future_id)
    assert still_active is not None and still_active.id == attempt.id


def test_in_progress_ack_unblocks_waiter(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """The task's ack (mark_port_canceled) is what flips the row terminal and lets
    the waiter proceed — get_active_port_attempt returns None only after it."""
    cc_pair, future_id = cc_pair_and_future
    attempt = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, attempt.id)
    request_port_cancel(db_session, attempt.id)
    assert get_active_port_attempt(db_session, cc_pair.id, future_id) is not None

    mark_port_canceled(db_session, attempt.id)

    assert _port_row(db_session, attempt.id).status == PortAttemptStatus.CANCELED
    assert get_active_port_attempt(db_session, cc_pair.id, future_id) is None


def test_request_cancel_terminal_is_noop(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    attempt = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, attempt.id)
    mark_port_succeeded(db_session, attempt.id)

    request_port_cancel(db_session, attempt.id)

    row = _port_row(db_session, attempt.id)
    assert row.status == PortAttemptStatus.SUCCESS
    assert row.cancel_requested is False


def test_mark_in_progress_rejects_duplicate_and_terminal(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """Only a NOT_STARTED row may start. A re-dispatched duplicate (already
    IN_PROGRESS) and a terminal row are both rejected, so one attempt never runs two
    concurrent writers."""
    cc_pair, future_id = cc_pair_and_future
    attempt = create_port_attempt(db_session, cc_pair.id, future_id)

    assert mark_port_in_progress(db_session, attempt.id) is True
    assert mark_port_in_progress(db_session, attempt.id) is False  # duplicate

    mark_port_canceled(db_session, attempt.id)
    assert mark_port_in_progress(db_session, attempt.id) is False  # terminal


def test_cancel_active_port_attempts_is_two_phase(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """The swap-path bulk cancel uses the same two-phase rule: NOT_STARTED ->
    CANCELED, IN_PROGRESS -> flagged-but-active (so a concurrent deletion waiting on
    that port isn't unblocked mid-write)."""
    future_id = make_future_search_settings(db_session).id
    # active-unique is per (cc_pair, ss), so use two cc_pairs on one FUTURE
    not_started_pair = make_cc_pair(db_session)
    in_progress_pair = make_cc_pair(db_session)
    try:
        ns = create_port_attempt(db_session, not_started_pair.id, future_id)
        ip = create_port_attempt(db_session, in_progress_pair.id, future_id)
        mark_port_in_progress(db_session, ip.id)

        affected = cancel_active_port_attempts(db_session, future_id)

        assert affected == 2
        assert _port_row(db_session, ns.id).status == PortAttemptStatus.CANCELED
        ip_row = _port_row(db_session, ip.id)
        assert ip_row.status == PortAttemptStatus.IN_PROGRESS
        assert ip_row.cancel_requested is True
        assert (
            get_active_port_attempt(db_session, in_progress_pair.id, future_id)
            is not None
        )
    finally:
        for pair in (not_started_pair, in_progress_pair):
            cleanup_cc_pair(db_session, pair)
        db_session.query(PortAttempt).filter(
            PortAttempt.search_settings_id == future_id
        ).delete(synchronize_session="fetch")
        db_session.commit()
