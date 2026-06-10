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
from onyx.db.enums import SwitchoverType
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document as DbDocument
from onyx.db.models import PortAttempt
from onyx.db.models import SearchSettings
from onyx.db.port_attempt import create_port_attempt
from onyx.db.port_attempt import mark_port_in_progress
from onyx.db.port_attempt import mark_port_succeeded
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
    # a deferred-sync doc remains -> the backlog gate fails (tenant-global count)
    doc_id = f"{_PENDING_DOC_PREFIX}pending"
    db_session.add(
        DbDocument(id=doc_id, semantic_id=doc_id, kg_stage=KGStage.NOT_STARTED)
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
    cc_pair, future_id = cc_pair_and_future
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
    assert mock_swap.call_args.kwargs["cleanup_documents"] is True


def test_legacy_path_does_not_consult_port_helpers(
    db_session: Session, cc_pair_and_future: tuple[ConnectorCredentialPair, int]
) -> None:
    cc_pair, future_id = cc_pair_and_future  # use_port_flow stays False (default)
    future_ss = db_session.get(SearchSettings, future_id)
    assert future_ss is not None
    future_ss.switchover_type = SwitchoverType.REINDEX  # non-INSTANT legacy path
    db_session.commit()

    with (
        patch.object(
            swap_index,
            "_port_swap_ready",
            side_effect=AssertionError("legacy must not use the port path"),
        ) as mock_ready,
        patch.object(swap_index, "_perform_index_swap") as mock_swap,
    ):
        result = check_and_perform_index_swap(db_session)

    mock_ready.assert_not_called()
    # legacy REINDEX holds (cc_pairs without successful FUTURE indexings) -> no swap
    assert result is None
    mock_swap.assert_not_called()
