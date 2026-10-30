"""External dependency unit tests for the port-aware swap criterion (T7/D8).

The port-flow branch of `check_and_perform_index_swap` swaps on four conditions
rather than the legacy successful-index count: every required cc_pair's port is
SUCCESS, a real (non-seed) FUTURE index attempt landed after the port, nothing is
in progress, and the deferred metadata-sync backlog has drained. The push-based
Ingestion pair is gated on its port only (it never runs a connector index attempt).
Mode C (INSTANT) swaps immediately; the legacy (flag-off) path is untouched.

`_perform_index_swap` must flip PRESENT -> PAST and FUTURE -> PRESENT in one
commit, so no other session ever reads a state with no PRESENT row.

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
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db import swap_index
from onyx.db.document import (
    PortedScope,
    PresentSearchSettingsRef,
    _present_index_content_hash_sql,
    get_port_source_content_hashes,
    mark_document_synced_secondary_pending,
    present_index_content_hash,
    record_present_index_write__no_commit,
    record_reindex_write__no_commit,
    sample_ported_document_ids,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    ConnectorCredentialPairStatus,
    IndexModelStatus,
    PortAttemptStatus,
    SwitchoverType,
    UserFileStatus,
)
from onyx.db.index_attempt import (
    create_index_attempt,
    mark_attempt_in_progress,
    mark_attempt_succeeded,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    Credential,
    DocumentByConnectorCredentialPair,
    IndexAttempt,
    PortAttempt,
    SearchSettings,
    UserFile,
)
from onyx.db.models import Document as DbDocument
from onyx.db.port_attempt import (
    cancel_active_port_attempts,
    create_port_attempt,
    get_active_port_attempt,
    mark_port_in_progress,
    mark_port_terminal,
    pause_port_attempt,
    request_port_cancel,
)
from onyx.db.search_settings import (
    get_current_search_settings,
    update_search_settings_status__no_commit,
)
from onyx.db.swap_index import (
    _perform_index_swap,
    _port_swap_ready,
    _required_cc_pairs_for_switchover,
    _verification_backoff_key,
    check_and_perform_index_swap,
)
from onyx.db.user_file import PortedUserScope, sample_ported_user_file_ids
from onyx.kg.models import KGStage
from onyx.redis.redis_pool import get_redis_client
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    cleanup_cc_pair_and_future,
    make_cc_pair,
    make_future_search_settings,
    seed_cc_pair_documents,
)

_PENDING_DOC_PREFIX = "swapdoc-"
_VERIFY_DOC_PREFIX = "swapdoc-verify-"
# Snapshot bounds that sort after every seeded id, so a test scope covers them all.
_ALL_DOCS_BOUND = "swapdoc-verify-zzzzzzzz"
_ALL_FILES_BOUND = "ffffffff-ffff-ffff-ffff-ffffffffffff"


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


def _make_success_port(
    db_session: Session,
    cc_pair_id: int,
    ss_id: int,
    up_to_doc_id: str | None = _ALL_DOCS_BOUND,
) -> datetime:
    """Creates a SUCCESS port attempt and returns its completion time, so callers can
    order index attempts relative to it. The snapshot bound defaults to one that
    covers every seeded document, so the pre-swap sample can see them."""
    attempt = create_port_attempt(
        db_session, cc_pair_id, ss_id, up_to_doc_id=up_to_doc_id
    )
    mark_port_in_progress(db_session, attempt.id)
    mark_port_terminal(db_session, attempt.id, PortAttemptStatus.SUCCESS)
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
    assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is True


def test_port_swap_blocks_when_no_port(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is False


def test_port_swap_blocks_on_active_port(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    attempt = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, attempt.id)  # active, not terminal
    assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is False


def _pause_unit(db_session: Session, cc_pair_id: int, ss_id: int) -> None:
    """Park a connector unit at PAUSED (FAILED -> PAUSED) for the swap-gate tests."""
    attempt = create_port_attempt(db_session, cc_pair_id, ss_id)
    mark_port_in_progress(db_session, attempt.id)
    mark_port_terminal(
        db_session, attempt.id, PortAttemptStatus.FAILED, error_msg="durable"
    )
    assert pause_port_attempt(db_session, attempt.id) is True


def test_port_swap_paused_connector_blocks_until_success(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A PAUSED connector port blocks the swap (only SUCCESS clears the gate); once the
    operator Resumes and the fresh attempt SUCCEEDs, the swap unblocks. Guards that PAUSED
    is not mistaken for a settled/successful state."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None

    _pause_unit(db_session, cc_pair.id, future_id)
    assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is False

    # a Resume mints a fresh attempt that eventually SUCCEEDs -> latest is SUCCESS -> ready
    _make_success_port(db_session, cc_pair.id, future_id)
    db_session.expire_all()
    assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is True


def test_port_swap_paused_user_blocks(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A PAUSED user port blocks the swap via all_user_scopes_ported (PAUSED isn't settled).
    Pure regression guard for the user branch."""
    _cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    user = create_test_user(db_session, "port_paused_user")
    try:
        attempt = create_port_attempt(db_session, None, future_id, port_user_id=user.id)
        mark_port_in_progress(db_session, attempt.id)
        mark_port_terminal(
            db_session, attempt.id, PortAttemptStatus.FAILED, error_msg="durable"
        )
        assert pause_port_attempt(db_session, attempt.id) is True

        # no required connectors; the single required user is PAUSED -> blocked
        assert _port_swap_ready(db_session, future_ss, [], [user.id]) is False
    finally:
        db_session.rollback()
        db_session.query(PortAttempt).filter(
            PortAttempt.port_user_id == user.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        delete_test_user(db_session, user)
        db_session.commit()


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
    assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is False


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
        assert _port_swap_ready(db_session, future_ss, [ingestion], []) is False
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
        assert _port_swap_ready(db_session, future_ss, [ingestion], []) is True
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


def test_instant_swap_never_commits_a_state_without_present(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """After each commit of the swap, a separate session must read exactly one
    PRESENT row. With two commits, a port task that starts between them fails on
    get_current_search_settings."""
    _, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.use_port_flow = True
    future_ss.switchover_type = SwitchoverType.INSTANT
    db_session.commit()
    old_present_id = get_current_search_settings(db_session).id

    # (PRESENT row count, PRESENT id, its backfill source) seen after each commit
    observed: list[tuple[int, int | None, int | None]] = []

    def _read_committed_state(_session: Session) -> None:
        with get_session_with_current_tenant() as reader:
            present_rows = (
                reader.execute(
                    select(SearchSettings).where(
                        SearchSettings.status == IndexModelStatus.PRESENT
                    )
                )
                .scalars()
                .all()
            )
            row = present_rows[0] if present_rows else None
            observed.append(
                (
                    len(present_rows),
                    row.id if row else None,
                    row.port_backfill_source_id if row else None,
                )
            )

    event.listen(db_session, "after_commit", _read_committed_state)
    try:
        with patch.object(swap_index, "get_default_document_index"):
            result = _perform_index_swap(db_session, future_ss, all_cc_pairs=[])
        assert result is not None and result.id == old_present_id
    finally:
        event.remove(db_session, "after_commit", _read_committed_state)
        # Put the original PRESENT back before the fixture deletes the test row.
        db_session.rollback()
        restored_future = db_session.get(SearchSettings, future_id)
        old_present = db_session.get(SearchSettings, old_present_id)
        assert restored_future is not None and old_present is not None
        if restored_future.status == IndexModelStatus.PRESENT:
            update_search_settings_status__no_commit(
                restored_future, IndexModelStatus.PAST, db_session
            )
        update_search_settings_status__no_commit(
            old_present, IndexModelStatus.PRESENT, db_session
        )
        db_session.commit()

    assert observed, "the swap made no commit"
    assert all(count == 1 for count, _, _ in observed), observed
    # The status flip and the backfill pin land in the same commit.
    first_promoted = next(o for o in observed if o[1] == future_id)
    assert first_promoted[2] == old_present_id


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
    """The task's ack (mark_port_terminal with CANCELED) is what flips the row terminal and lets
    the waiter proceed — get_active_port_attempt returns None only after it."""
    cc_pair, future_id = cc_pair_and_future
    attempt = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, attempt.id)
    request_port_cancel(db_session, attempt.id)
    assert get_active_port_attempt(db_session, cc_pair.id, future_id) is not None

    mark_port_terminal(db_session, attempt.id, PortAttemptStatus.CANCELED)

    assert _port_row(db_session, attempt.id).status == PortAttemptStatus.CANCELED
    assert get_active_port_attempt(db_session, cc_pair.id, future_id) is None


def test_request_cancel_terminal_is_noop(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    attempt = create_port_attempt(db_session, cc_pair.id, future_id)
    mark_port_in_progress(db_session, attempt.id)
    mark_port_terminal(db_session, attempt.id, PortAttemptStatus.SUCCESS)

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

    mark_port_terminal(db_session, attempt.id, PortAttemptStatus.CANCELED)
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


def _clear_verification_backoff(future_id: int) -> None:
    """Deletes the Redis backoff key a failed check leaves, so tests start clean."""
    get_redis_client().delete(_verification_backoff_key(future_id))


def test_sampler_returns_ported_documents_with_chunks(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, _ = cc_pair_and_future
    kept = seed_cc_pair_documents(
        db_session, cc_pair, 2, prefix=f"{_VERIFY_DOC_PREFIX}keep-", chunk_count=3
    )
    seed_cc_pair_documents(
        db_session, cc_pair, 1, prefix=f"{_VERIFY_DOC_PREFIX}nochunks-", chunk_count=0
    )

    scope = PortedScope(
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        up_to_doc_id=_ALL_DOCS_BOUND,
    )
    assert sorted(sample_ported_document_ids(db_session, [scope], 10)) == sorted(kept)
    # The sample must be deterministic; a fresh random draw would eventually miss the
    # gap and pass.
    assert sample_ported_document_ids(db_session, [scope], 1) == (
        sample_ported_document_ids(db_session, [scope], 1)
    )


def test_sampler_covers_documents_predating_the_chunk_count_column(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """Documents with a NULL chunk_count predate the column and must still be
    sampled, or an old deployment would verify nothing."""
    cc_pair, _ = cc_pair_and_future
    legacy = seed_cc_pair_documents(
        db_session, cc_pair, 2, prefix=f"{_VERIFY_DOC_PREFIX}legacy-", chunk_count=None
    )
    seed_cc_pair_documents(
        db_session, cc_pair, 1, prefix=f"{_VERIFY_DOC_PREFIX}empty-", chunk_count=0
    )
    scope = PortedScope(
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        up_to_doc_id=_ALL_DOCS_BOUND,
    )
    assert sorted(sample_ported_document_ids(db_session, [scope], 10)) == sorted(legacy)


def test_document_absent_from_both_indexes_does_not_hold_the_swap(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A document with no chunks in the source index can never appear in the new
    one, so it must not hold the swap."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    _make_success_port(db_session, cc_pair.id, future_id)
    seeded = seed_cc_pair_documents(
        db_session, cc_pair, 1, prefix=_VERIFY_DOC_PREFIX, chunk_count=None
    )
    _clear_verification_backoff(future_id)

    with (
        patch.object(
            swap_index, "find_documents_missing_from_index", return_value=seeded
        ),
        patch.object(swap_index, "find_documents_with_no_chunks", return_value=seeded),
    ):
        assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is True


def test_sampler_respects_the_port_snapshot_bound(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """Documents added after the port's snapshot bound belong to the FUTURE index
    attempt and must not be sampled."""
    cc_pair, _ = cc_pair_and_future
    seed_cc_pair_documents(
        db_session, cc_pair, 1, prefix=f"{_VERIFY_DOC_PREFIX}a-", chunk_count=2
    )
    seed_cc_pair_documents(
        db_session, cc_pair, 1, prefix=f"{_VERIFY_DOC_PREFIX}z-", chunk_count=2
    )

    scope = PortedScope(
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        up_to_doc_id=f"{_VERIFY_DOC_PREFIX}m",
    )
    sampled = sample_ported_document_ids(db_session, [scope], 10)
    assert all(doc_id.startswith(f"{_VERIFY_DOC_PREFIX}a-") for doc_id in sampled)
    assert sampled


def test_swap_holds_while_an_index_attempt_is_still_running(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    _make_success_port(db_session, cc_pair.id, future_id)
    seed_cc_pair_documents(
        db_session, cc_pair, 1, prefix=_VERIFY_DOC_PREFIX, chunk_count=3
    )
    _clear_verification_backoff(future_id)

    attempt_id = create_index_attempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=future_id,
        db_session=db_session,
    )
    # create_index_attempt leaves the attempt NOT_STARTED, which must not hold the swap.
    with patch.object(swap_index, "find_documents_missing_from_index", return_value=[]):
        assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is True

    _clear_verification_backoff(future_id)
    attempt = db_session.get(IndexAttempt, attempt_id)
    assert attempt is not None
    mark_attempt_in_progress(attempt, db_session)
    db_session.expire_all()
    with patch.object(
        swap_index, "find_documents_missing_from_index", return_value=[]
    ) as lookup:
        assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is False
    # The running attempt held the swap before the sample, so no lookup was made.
    lookup.assert_not_called()

    mark_attempt_succeeded(attempt_id, db_session)
    db_session.expire_all()
    _clear_verification_backoff(future_id)
    with patch.object(swap_index, "find_documents_missing_from_index", return_value=[]):
        assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is True


def test_writer_starting_during_the_sample_holds_the_swap(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    _make_success_port(db_session, cc_pair.id, future_id)
    seed_cc_pair_documents(
        db_session, cc_pair, 1, prefix=_VERIFY_DOC_PREFIX, chunk_count=3
    )
    _clear_verification_backoff(future_id)

    attempt_id = create_index_attempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=future_id,
        db_session=db_session,
    )

    def _start_writing_mid_sample(*_args: object, **_kwargs: object) -> list[str]:
        attempt = db_session.get(IndexAttempt, attempt_id)
        assert attempt is not None
        mark_attempt_in_progress(attempt, db_session)
        db_session.expire_all()
        return []

    with patch.object(
        swap_index,
        "find_documents_missing_from_index",
        side_effect=_start_writing_mid_sample,
    ):
        assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is False


def test_sampler_skips_a_scope_with_no_snapshot_bound(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """A port with no snapshot bound copied nothing, so documents and files completed
    later must not be sampled: their FUTURE copy is the dual-write's or the next index
    attempt's job."""
    cc_pair, _ = cc_pair_and_future
    seed_cc_pair_documents(
        db_session, cc_pair, 2, prefix=f"{_VERIFY_DOC_PREFIX}late-", chunk_count=3
    )
    unbounded = PortedScope(
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        up_to_doc_id=None,
    )
    assert sample_ported_document_ids(db_session, [unbounded], 10) == []

    user = create_test_user(db_session, "port_verify_unbounded")
    try:
        _add_user_file(db_session, user.id, 4, "completed-after-start.txt")
        assert (
            sample_ported_user_file_ids(
                db_session,
                [PortedUserScope(user_id=user.id, up_to_doc_id=None)],
                per_scope_limit=10,
            )
            == []
        )
    finally:
        db_session.rollback()
        db_session.query(UserFile).filter(UserFile.user_id == user.id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()
        delete_test_user(db_session, user)
        db_session.commit()


def _make_cc_pair_with_distinct_ids(
    db_session: Session,
) -> tuple[ConnectorCredentialPair, Credential | None]:
    """Makes a cc_pair whose connector_id and credential_id differ.

    make_cc_pair advances both id sequences together, so the two ids are often equal.
    Inserting one extra credential shifts the credential sequence by one.
    """
    cc_pair = make_cc_pair(db_session)
    if cc_pair.connector_id != cc_pair.credential_id:
        return cc_pair, None

    spare = Credential(source=DocumentSource.MOCK_CONNECTOR, credential_json={})
    db_session.add(spare)
    db_session.commit()
    cleanup_cc_pair(db_session, cc_pair)

    cc_pair = make_cc_pair(db_session)
    assert cc_pair.connector_id != cc_pair.credential_id
    return cc_pair, spare


def test_sampler_keeps_connector_and_credential_apart(db_session: Session) -> None:
    """Both ids are ints, so only a test catches the query swapping the two columns."""
    cc_pair, spare_credential = _make_cc_pair_with_distinct_ids(db_session)
    try:
        seeded = seed_cc_pair_documents(
            db_session, cc_pair, 1, prefix=f"{_VERIFY_DOC_PREFIX}pair-", chunk_count=2
        )
        correct = PortedScope(
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
            up_to_doc_id=_ALL_DOCS_BOUND,
        )
        swapped = PortedScope(
            connector_id=cc_pair.credential_id,
            credential_id=cc_pair.connector_id,
            up_to_doc_id=_ALL_DOCS_BOUND,
        )
        assert sample_ported_document_ids(db_session, [correct], 5) == seeded
        assert sample_ported_document_ids(db_session, [swapped], 5) == []
    finally:
        db_session.rollback()
        cleanup_cc_pair(db_session, cc_pair)
        if spare_credential is not None:
            db_session.delete(spare_credential)
        db_session.commit()


def test_pre_swap_check_gates_on_what_is_in_the_new_index(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    _make_success_port(db_session, cc_pair.id, future_id)
    seeded = seed_cc_pair_documents(
        db_session, cc_pair, 1, prefix=_VERIFY_DOC_PREFIX, chunk_count=3
    )
    _clear_verification_backoff(future_id)

    with (
        patch.object(
            swap_index, "find_documents_missing_from_index", return_value=seeded
        ),
        patch.object(swap_index, "find_documents_with_no_chunks", return_value=[]),
    ):
        assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is False

    _clear_verification_backoff(future_id)
    with patch.object(
        swap_index, "find_documents_missing_from_index", return_value=[]
    ) as lookup:
        assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is True
    # The lookup received the real sample, not an empty list.
    assert seeded[0] in lookup.call_args[0][1]


def test_failed_verification_backs_off_before_rechecking(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """After a failed check the next tick must hold the swap without re-running the
    sample and the lookup."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    _make_success_port(db_session, cc_pair.id, future_id)
    seeded = seed_cc_pair_documents(
        db_session, cc_pair, 1, prefix=_VERIFY_DOC_PREFIX, chunk_count=3
    )
    _clear_verification_backoff(future_id)

    with (
        patch.object(
            swap_index, "find_documents_missing_from_index", return_value=seeded
        ),
        patch.object(swap_index, "find_documents_with_no_chunks", return_value=[]),
    ):
        assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is False

    with patch.object(swap_index, "find_documents_missing_from_index") as lookup:
        assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is False
        lookup.assert_not_called()
    _clear_verification_backoff(future_id)


def test_zero_retry_delay_writes_no_backoff_key(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """With a retry delay of 0 the gate must not set a backoff key, because Redis
    rejects ex=0."""
    cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    _make_success_port(db_session, cc_pair.id, future_id)
    seeded = seed_cc_pair_documents(
        db_session, cc_pair, 1, prefix=_VERIFY_DOC_PREFIX, chunk_count=3
    )
    _clear_verification_backoff(future_id)

    with (
        patch.object(swap_index, "PORT_SWAP_VERIFY_RETRY_DELAY_S", 0),
        patch.object(
            swap_index,
            "find_documents_missing_from_index",
            return_value=seeded,
        ),
        patch.object(swap_index, "find_documents_with_no_chunks", return_value=[]),
    ):
        assert _port_swap_ready(db_session, future_ss, [cc_pair], []) is False
    # With no backoff key the next tick re-checks immediately.
    assert not get_redis_client().exists(_verification_backoff_key(future_id))


def _add_user_file(
    db_session: Session, user_id: UUID, chunk_count: int | None, name: str
) -> UUID:
    user_file = UserFile(
        id=uuid4(),
        user_id=user_id,
        file_id=f"file-{uuid4().hex[:8]}",
        name=name,
        file_type="text/plain",
        status=UserFileStatus.COMPLETED,
        chunk_count=chunk_count,
    )
    db_session.add(user_file)
    db_session.commit()
    return user_file.id


def test_user_file_sampler_covers_the_second_port_scope(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """User files have no cc_pair, so they need their own sampler."""
    _cc_pair, _future_id = cc_pair_and_future
    user = create_test_user(db_session, "port_verify_userfile")
    try:
        with_chunks = _add_user_file(db_session, user.id, 4, "ported.txt")
        _add_user_file(db_session, user.id, 0, "no-chunks.txt")
        unknown_chunks = _add_user_file(db_session, user.id, None, "legacy.txt")

        sampled = sample_ported_user_file_ids(
            db_session,
            [PortedUserScope(user_id=user.id, up_to_doc_id=_ALL_FILES_BOUND)],
            per_scope_limit=10,
        )
        assert sorted(sampled) == sorted([str(with_chunks), str(unknown_chunks)])
    finally:
        db_session.rollback()
        db_session.query(UserFile).filter(UserFile.user_id == user.id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()
        delete_test_user(db_session, user)
        db_session.commit()


def test_port_swap_blocks_when_a_ported_user_file_is_missing(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """The gate must hold when a user's ported files are missing from the new index."""
    _cc_pair, future_id = cc_pair_and_future
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    user = create_test_user(db_session, "port_verify_userfile_gate")
    try:
        user_file_id = _add_user_file(db_session, user.id, 4, "ported.txt")
        attempt = create_port_attempt(
            db_session,
            None,
            future_id,
            port_user_id=user.id,
            up_to_doc_id=_ALL_FILES_BOUND,
        )
        mark_port_in_progress(db_session, attempt.id)
        mark_port_terminal(db_session, attempt.id, PortAttemptStatus.SUCCESS)
        db_session.expire_all()
        _clear_verification_backoff(future_id)

        with (
            patch.object(
                swap_index,
                "find_documents_missing_from_index",
                return_value=[str(user_file_id)],
            ) as lookup,
            patch.object(swap_index, "find_documents_with_no_chunks", return_value=[]),
        ):
            assert _port_swap_ready(db_session, future_ss, [], [user.id]) is False
        assert str(user_file_id) in lookup.call_args[0][1]

        _clear_verification_backoff(future_id)
        with patch.object(
            swap_index, "find_documents_missing_from_index", return_value=[]
        ):
            assert _port_swap_ready(db_session, future_ss, [], [user.id]) is True
    finally:
        db_session.rollback()
        db_session.query(PortAttempt).filter(
            PortAttempt.port_user_id == user.id
        ).delete(synchronize_session="fetch")
        db_session.query(UserFile).filter(UserFile.user_id == user.id).delete(
            synchronize_session="fetch"
        )
        db_session.commit()
        delete_test_user(db_session, user)
        db_session.commit()
        _clear_verification_backoff(future_id)


def _seed_hashed_doc(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    name: str,
    content_hash: str | None,
    record: tuple[str | None, int] | None = None,
) -> str:
    """A doc of the cc_pair with PRESENT's content_hash and, when given, the record
    (secondary_content_hash, secondary_search_settings_id)."""
    doc_id = f"{_PENDING_DOC_PREFIX}{name}"
    db_session.add(
        DbDocument(
            id=doc_id,
            semantic_id=doc_id,
            kg_stage=KGStage.NOT_STARTED,
            content_hash=content_hash,
            secondary_content_hash=record[0] if record else None,
            secondary_search_settings_id=record[1] if record else None,
        )
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
    return doc_id


def _columns(
    db_session: Session, doc_id: str
) -> tuple[str | None, str | None, int | None]:
    """(content_hash, secondary_content_hash, secondary_search_settings_id) as stored."""
    db_session.expire_all()
    row = db_session.get(DbDocument, doc_id)
    assert row is not None
    return (
        row.content_hash,
        row.secondary_content_hash,
        row.secondary_search_settings_id,
    )


def _present_hash(
    db_session: Session, doc_id: str, present: PresentSearchSettingsRef
) -> str | None:
    db_session.expire_all()
    row = db_session.get(DbDocument, doc_id)
    assert row is not None
    return present_index_content_hash(row, present)


def test_present_index_content_hash_sql_matches_python(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """The SQL form (_present_index_content_hash_sql) and the Python form agree on
    every rule."""
    cc_pair, future_id = cc_pair_and_future
    present_id = get_current_search_settings(db_session).id
    older = present_id - 1
    plain = PresentSearchSettingsRef(id=present_id, port_backfill_source_id=None)
    pinned = PresentSearchSettingsRef(id=present_id, port_backfill_source_id=older)
    rows = {
        "none": _seed_hashed_doc(db_session, cc_pair, "r0", "c"),
        "present": _seed_hashed_doc(
            db_session, cc_pair, "r1", "stale", ("r", present_id)
        ),
        "pin": _seed_hashed_doc(db_session, cc_pair, "r2", "c", ("r", older)),
        "newer": _seed_hashed_doc(db_session, cc_pair, "r3", "c", ("r", future_id)),
        "older": _seed_hashed_doc(db_session, cc_pair, "r4", "c", ("r", older - 1)),
    }
    cases = [
        (
            plain,
            {"none": "c", "present": "r", "pin": None, "newer": "c", "older": None},
        ),
        (
            pinned,
            {"none": "c", "present": "r", "pin": "r", "newer": "c", "older": None},
        ),
    ]
    for present, expected in cases:
        by_id = {rows[name]: value for name, value in expected.items()}
        sql_rows = db_session.execute(
            select(
                DbDocument.id, _present_index_content_hash_sql(present).label("hash")
            ).where(DbDocument.id.in_(list(rows.values())))
        ).all()
        assert {row.id: row.hash for row in sql_rows} == by_id
        assert {
            doc_id: _present_hash(db_session, doc_id, present)
            for doc_id in rows.values()
        } == by_id


def test_present_index_write_records_unless_a_newer_index_has_the_doc(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future
    present_id = get_current_search_settings(db_session).id
    fresh = _seed_hashed_doc(db_session, cc_pair, "fresh", None)
    mine = _seed_hashed_doc(db_session, cc_pair, "mine", "v1", ("v1", present_id))
    taken = _seed_hashed_doc(db_session, cc_pair, "taken", "v1", ("v1", future_id))

    record_present_index_write__no_commit(
        db_session, {fresh: "v2", mine: "v2", taken: "v2"}, present_id, present_id
    )
    db_session.commit()
    assert _columns(db_session, fresh) == ("v2", "v2", present_id)
    assert _columns(db_session, mine) == ("v2", "v2", present_id)
    # FUTURE's record stays; content_hash alone describes PRESENT for this doc
    assert _columns(db_session, taken) == ("v2", "v1", future_id)

    # A batch that began before a swap wrote into the old index, which search no
    # longer uses. Nothing changes.
    record_present_index_write__no_commit(
        db_session, {mine: "v3"}, present_id - 1, present_id
    )
    db_session.commit()
    assert _columns(db_session, mine) == ("v2", "v2", present_id)


def test_reindex_write_copies_the_present_hash_into_content_hash(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """When the record stops describing PRESENT, content_hash must start to. Both the
    port and secondary indexing replace the record this way."""
    cc_pair, present_id = cc_pair_and_future  # the fixture's FUTURE plays PRESENT
    present = PresentSearchSettingsRef(id=present_id, port_backfill_source_id=None)
    next_id = present_id + 1
    # swapped to PRESENT with v1, never fetched since: content_hash is the old index's
    ported = _seed_hashed_doc(
        db_session, cc_pair, "take-port", "old", ("v1", present_id)
    )
    indexed = _seed_hashed_doc(
        db_session, cc_pair, "take-sec", "old", ("v1", present_id)
    )

    snapshot = get_port_source_content_hashes(db_session, [ported], present_id)
    assert snapshot == {ported: "v1"}
    record_reindex_write__no_commit(
        db_session, snapshot, next_id, present, skip_docs_recorded_for_target=True
    )
    record_reindex_write__no_commit(
        db_session,
        {indexed: "v9"},
        next_id,
        present,
        skip_docs_recorded_for_target=False,
    )
    db_session.commit()
    assert _columns(db_session, ported) == ("v1", "v1", next_id)
    assert _columns(db_session, indexed) == ("v1", "v9", next_id)
    assert _present_hash(db_session, ported, present) == "v1"
    assert _present_hash(db_session, indexed, present) == "v1"

    # the port never replaces a record already made for its target
    record_reindex_write__no_commit(
        db_session,
        {indexed: "v1"},
        next_id,
        present,
        skip_docs_recorded_for_target=True,
    )
    db_session.commit()
    assert _columns(db_session, indexed) == ("v1", "v9", next_id)


def test_lazy_resolution_through_two_reindexes(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    """Port, late PRESENT write, swap, fetch, next reindex. A swap is modelled by the
    PresentSearchSettingsRef the gate would build for the new PRESENT: the resolver
    reads only the row and that ref."""
    cc_pair, b = cc_pair_and_future
    a = get_current_search_settings(db_session).id
    c = b + 1
    present_a = PresentSearchSettingsRef(id=a, port_backfill_source_id=None)
    present_b = PresentSearchSettingsRef(id=b, port_backfill_source_id=None)
    present_c = PresentSearchSettingsRef(id=c, port_backfill_source_id=None)
    d = _seed_hashed_doc(db_session, cc_pair, "walk", "v1", ("v1", a))

    # 1. the port copies v1 into B
    record_reindex_write__no_commit(
        db_session,
        get_port_source_content_hashes(db_session, [d], a),
        b,
        present_a,
        skip_docs_recorded_for_target=True,
    )
    db_session.commit()
    assert _columns(db_session, d) == ("v1", "v1", b)
    # 2. indexing writes v2 into A: B's record is newer, so it is left alone
    record_present_index_write__no_commit(db_session, {d: "v2"}, a, a)
    db_session.commit()
    assert _columns(db_session, d) == ("v2", "v1", b)
    assert _present_hash(db_session, d, present_a) == "v2"
    # 3. swap: B is PRESENT and holds v1, so a fetch at v2 writes, then records for B
    assert _present_hash(db_session, d, present_b) == "v1"
    record_present_index_write__no_commit(db_session, {d: "v2"}, b, b)
    db_session.commit()
    assert _columns(db_session, d) == ("v2", "v2", b)
    assert _present_hash(db_session, d, present_b) == "v2"
    # 4. reindex C: the port replaces the record; content_hash keeps describing B
    record_reindex_write__no_commit(
        db_session,
        get_port_source_content_hashes(db_session, [d], b),
        c,
        present_b,
        skip_docs_recorded_for_target=True,
    )
    db_session.commit()
    assert _columns(db_session, d) == ("v2", "v2", c)
    assert _present_hash(db_session, d, present_b) == "v2"
    # 5. indexing writes v3 into B while C is being built
    record_present_index_write__no_commit(db_session, {d: "v3"}, b, b)
    db_session.commit()
    assert _columns(db_session, d) == ("v3", "v2", c)
    assert _present_hash(db_session, d, present_b) == "v3"
    # 6. swap to C: it holds v2, so a fetch at v3 writes
    assert _present_hash(db_session, d, present_c) == "v2"


def test_instant_backfill_trusts_the_pinned_source_until_it_records(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, new_present = cc_pair_and_future
    old = get_current_search_settings(db_session).id
    pinned = PresentSearchSettingsRef(id=new_present, port_backfill_source_id=old)
    unpinned = PresentSearchSettingsRef(id=new_present, port_backfill_source_id=None)
    # swapped INSTANT while content_hash still says "old" from the index before `old`
    d = _seed_hashed_doc(db_session, cc_pair, "inst", "old", ("v1", old))

    # while pinned the backfill will bring v1; a pin cleared without a backfill record
    # means the doc never reached the new PRESENT
    assert _present_hash(db_session, d, pinned) == "v1"
    assert _present_hash(db_session, d, unpinned) is None

    record_reindex_write__no_commit(
        db_session,
        get_port_source_content_hashes(db_session, [d], old),
        new_present,
        pinned,
        skip_docs_recorded_for_target=True,
    )
    db_session.commit()
    assert _columns(db_session, d) == ("v1", "v1", new_present)
    assert _present_hash(db_session, d, unpinned) == "v1"
