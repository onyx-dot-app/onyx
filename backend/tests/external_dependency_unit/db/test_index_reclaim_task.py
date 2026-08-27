"""External dependency unit tests for the old-index-reclamation state machine.

The OpenSearch deletion primitive is covered against a real index in
tests/external_dependency_unit/opensearch/test_opensearch_client.py, so most tests here
replace it at the module boundary and drive the state machine against real Postgres.
One end-to-end test still runs the real primitive.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

import onyx.background.celery.tasks.index_reclaim.tasks as reclaim_tasks
from onyx.configs.constants import OnyxCeleryQueues, OnyxCeleryTask
from onyx.context.search.models import SavedSearchSettings
from onyx.db.enums import (
    ConnectorCredentialPairStatus,
    EmbeddingPrecision,
    IndexModelStatus,
    IndexReclaimStatus,
)
from onyx.db.models import ConnectorCredentialPair, SearchSettings
from onyx.db.search_settings import create_search_settings, get_search_settings_by_id
from onyx.document_index.opensearch.client import OpenSearchIndexClient
from onyx.document_index.opensearch.index_reclaim import ReclaimOutcome
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


def _saved_settings(index_name: str | None = None) -> SavedSearchSettings:
    return SavedSearchSettings(
        model_name="test-reclaim-task-model",
        model_dim=128,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        provider_type=None,
        multipass_indexing=False,
        embedding_precision=EmbeddingPrecision.FLOAT,
        index_name=index_name or f"test_reclaim_task_{uuid4().hex[:8]}",
        enable_contextual_rag=False,
    )


def _make_past_settings(
    db_session: Session,
    reclaim_status: IndexReclaimStatus,
    *,
    pending_cc_pair_deletions: list[int] | None = None,
    stopped_reading_at: datetime | None = None,
    index_name: str | None = None,
) -> SearchSettings:
    ss = create_search_settings(
        _saved_settings(index_name), db_session, status=IndexModelStatus.PAST
    )
    ss.reclaim_status = reclaim_status
    ss.pending_cc_pair_deletions = pending_cc_pair_deletions
    ss.reclaim_stopped_reading_at = stopped_reading_at
    db_session.commit()
    db_session.refresh(ss)
    return ss


def _make_present_settings(db_session: Session) -> SearchSettings:
    """Without a PRESENT row the driver records the resulting error as a reclaim
    attempt bump, so these tests own one instead of trusting whatever the shared DB
    holds. get_current_search_settings reads the highest id, so this row always wins."""
    return create_search_settings(
        _saved_settings(f"test_reclaim_present_{uuid4().hex[:8]}"),
        db_session,
        status=IndexModelStatus.PRESENT,
    )


def _delete_settings(db_session: Session, ss: SearchSettings) -> None:
    if get_search_settings_by_id(db_session, ss.id) is not None:
        db_session.delete(ss)
        db_session.commit()


def _cc_pair_with_status(
    db_session: Session, status: ConnectorCredentialPairStatus
) -> ConnectorCredentialPair:
    pair = make_cc_pair(db_session)
    pair.status = status
    db_session.commit()
    db_session.refresh(pair)
    return pair


def test_pending_waits_while_port_still_reads_old_index(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reclaim_tasks, "is_active_port_backfill_source", lambda *_a, **_k: True
    )
    ss = _make_past_settings(db_session, IndexReclaimStatus.PENDING)
    celery_app = MagicMock()
    try:
        reclaim_tasks.run_old_index_reclaim(db_session, celery_app, "tenant", ss)
        db_session.refresh(ss)
        assert ss.reclaim_status == IndexReclaimStatus.PENDING
        celery_app.send_task.assert_not_called()
    finally:
        _delete_settings(db_session, ss)


def test_pending_fires_deletions_and_advances_to_soaking(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reclaim_tasks, "is_active_port_backfill_source", lambda *_a, **_k: False
    )
    invalid = _cc_pair_with_status(db_session, ConnectorCredentialPairStatus.INVALID)
    ss = _make_past_settings(
        db_session,
        IndexReclaimStatus.PENDING,
        pending_cc_pair_deletions=[invalid.id],
    )
    celery_app = MagicMock()
    try:
        reclaim_tasks.run_old_index_reclaim(db_session, celery_app, "tenant", ss)
        db_session.refresh(ss)
        db_session.refresh(invalid)

        assert ss.reclaim_status == IndexReclaimStatus.SOAKING
        assert ss.reclaim_stopped_reading_at is not None
        assert invalid.status == ConnectorCredentialPairStatus.DELETING
        celery_app.send_task.assert_called_once()
    finally:
        _delete_settings(db_session, ss)
        cleanup_cc_pair(db_session, invalid)


def test_pending_revalidation_spares_reactivated_connector(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reclaim_tasks, "is_active_port_backfill_source", lambda *_a, **_k: False
    )
    reactivated = _cc_pair_with_status(db_session, ConnectorCredentialPairStatus.ACTIVE)
    still_invalid = _cc_pair_with_status(
        db_session, ConnectorCredentialPairStatus.INVALID
    )
    ss = _make_past_settings(
        db_session,
        IndexReclaimStatus.PENDING,
        pending_cc_pair_deletions=[reactivated.id, still_invalid.id],
    )
    celery_app = MagicMock()
    try:
        reclaim_tasks.run_old_index_reclaim(db_session, celery_app, "tenant", ss)
        db_session.refresh(reactivated)
        db_session.refresh(still_invalid)

        assert reactivated.status == ConnectorCredentialPairStatus.ACTIVE
        assert still_invalid.status == ConnectorCredentialPairStatus.DELETING
    finally:
        _delete_settings(db_session, ss)
        cleanup_cc_pair(db_session, reactivated)
        cleanup_cc_pair(db_session, still_invalid)


def test_soaking_waits_until_retention_elapses(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reclaim_tasks, "OLD_INDEX_RETENTION_HOURS", 24)
    ss = _make_past_settings(
        db_session,
        IndexReclaimStatus.SOAKING,
        stopped_reading_at=datetime.now(timezone.utc),
    )
    celery_app = MagicMock()
    try:
        reclaim_tasks.run_old_index_reclaim(db_session, celery_app, "tenant", ss)
        db_session.refresh(ss)
        assert ss.reclaim_status == IndexReclaimStatus.SOAKING
    finally:
        _delete_settings(db_session, ss)


def test_soaking_advances_to_deleting_when_elapsed_and_healthy(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reclaim_tasks, "OLD_INDEX_RETENTION_HOURS", 0)
    monkeypatch.setattr(reclaim_tasks, "_new_index_can_serve", lambda _name: True)
    present = _make_present_settings(db_session)
    ss = _make_past_settings(
        db_session,
        IndexReclaimStatus.SOAKING,
        stopped_reading_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    celery_app = MagicMock()
    try:
        reclaim_tasks.run_old_index_reclaim(db_session, celery_app, "tenant", ss)
        db_session.refresh(ss)
        assert ss.reclaim_status == IndexReclaimStatus.DELETING
    finally:
        _delete_settings(db_session, ss)
        _delete_settings(db_session, present)


def test_soaking_holds_when_new_index_cannot_serve(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Waiting on the new index is not a failure, so it must not bump the attempt
    counter — a benign wait counted as a failure would eventually BLOCK the row."""
    monkeypatch.setattr(reclaim_tasks, "OLD_INDEX_RETENTION_HOURS", 0)
    monkeypatch.setattr(reclaim_tasks, "_new_index_can_serve", lambda _name: False)
    present = _make_present_settings(db_session)
    ss = _make_past_settings(
        db_session,
        IndexReclaimStatus.SOAKING,
        stopped_reading_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    celery_app = MagicMock()
    try:
        reclaim_tasks.run_old_index_reclaim(db_session, celery_app, "tenant", ss)
        db_session.refresh(ss)
        assert ss.reclaim_status == IndexReclaimStatus.SOAKING
        assert ss.reclaim_attempts == 0
    finally:
        _delete_settings(db_session, ss)
        _delete_settings(db_session, present)


def test_deleting_complete_marks_reclaimed_and_keeps_row(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        reclaim_tasks, "reclaim_index_data", lambda *_a, **_k: ReclaimOutcome.COMPLETE
    )
    ss = _make_past_settings(db_session, IndexReclaimStatus.DELETING)
    ss_id = ss.id
    try:
        reclaim_tasks.run_old_index_reclaim(db_session, MagicMock(), "tenant", ss)
        db_session.refresh(ss)
        row = get_search_settings_by_id(db_session, ss_id)
        assert row is not None
        assert row.reclaim_status == IndexReclaimStatus.RECLAIMED
    finally:
        _delete_settings(db_session, ss)


def test_deleting_incomplete_stays_deleting(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reclaim_tasks, "_DELETE_TIME_BUDGET_S", 0)
    monkeypatch.setattr(
        reclaim_tasks, "reclaim_index_data", lambda *_a, **_k: ReclaimOutcome.INCOMPLETE
    )
    ss = _make_past_settings(db_session, IndexReclaimStatus.DELETING)
    try:
        reclaim_tasks.run_old_index_reclaim(db_session, MagicMock(), "tenant", ss)
        db_session.refresh(ss)
        assert ss.reclaim_status == IndexReclaimStatus.DELETING
    finally:
        _delete_settings(db_session, ss)


def test_deleting_single_tenant_end_to_end_drops_real_index(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reclaim_tasks, "MULTI_TENANT", False)
    index_name = f"test_reclaim_e2e_{uuid4().hex[:8]}"
    client = OpenSearchIndexClient(index_name=index_name)
    # Single-tenant reclaim drops the whole index, so it needs no mappings or documents.
    client._client.indices.create(index=index_name)
    ss = _make_past_settings(
        db_session, IndexReclaimStatus.DELETING, index_name=index_name
    )
    ss_id = ss.id
    try:
        reclaim_tasks.run_old_index_reclaim(db_session, MagicMock(), "tenant", ss)
        db_session.refresh(ss)
        row = get_search_settings_by_id(db_session, ss_id)
        assert row is not None
        assert row.reclaim_status == IndexReclaimStatus.RECLAIMED
        assert client.index_exists() is False
    finally:
        try:
            client.delete_index()
        except Exception:
            pass
        client.close()
        _delete_settings(db_session, ss)


def test_step_failure_bumps_attempts_then_blocks_at_cap(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reclaim_tasks, "OLD_INDEX_RECLAIM_MAX_ATTEMPTS", 2)

    def _boom(*_a: object, **_k: object) -> ReclaimOutcome:
        raise RuntimeError("opensearch down")

    monkeypatch.setattr(reclaim_tasks, "reclaim_index_data", _boom)
    ss = _make_past_settings(db_session, IndexReclaimStatus.DELETING)
    try:
        reclaim_tasks.run_old_index_reclaim(db_session, MagicMock(), "tenant", ss)
        db_session.refresh(ss)
        assert ss.reclaim_attempts == 1
        assert ss.reclaim_status == IndexReclaimStatus.DELETING
        assert ss.reclaim_last_error is not None

        reclaim_tasks.run_old_index_reclaim(db_session, MagicMock(), "tenant", ss)
        db_session.refresh(ss)
        assert ss.reclaim_attempts == 2
        assert ss.reclaim_status == IndexReclaimStatus.BLOCKED
    finally:
        _delete_settings(db_session, ss)


def _enqueued_settings_ids(celery_app: MagicMock) -> list[int]:
    ids = []
    for call in celery_app.send_task.call_args_list:
        assert call.args[0] == OnyxCeleryTask.RUN_OLD_INDEX_RECLAIM
        assert call.kwargs["queue"] == OnyxCeleryQueues.INDEX_RECLAIM
        ids.append(call.kwargs["kwargs"]["search_settings_id"])
    return ids


def test_kill_switch_disabled_enqueues_nothing(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reclaim_tasks, "OLD_INDEX_RECLAIM_ENABLED", False)
    ss = _make_past_settings(db_session, IndexReclaimStatus.PENDING)
    celery_app = MagicMock()
    try:
        assert (
            reclaim_tasks.run_check_for_old_index_reclaim("tenant", celery_app) is None
        )
        celery_app.send_task.assert_not_called()
    finally:
        _delete_settings(db_session, ss)


def test_enabled_fans_out_one_task_per_reclaimable_row(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The beat must only enqueue and never drive a row inline, so the heavy deletion
    runs on the light worker instead of the primary beat."""
    monkeypatch.setattr(reclaim_tasks, "OLD_INDEX_RECLAIM_ENABLED", True)
    ss = _make_past_settings(db_session, IndexReclaimStatus.PENDING)
    ss_id = ss.id
    celery_app = MagicMock()
    try:
        enqueued = reclaim_tasks.run_check_for_old_index_reclaim("tenant", celery_app)
        assert enqueued is not None and enqueued >= 1
        assert ss_id in _enqueued_settings_ids(celery_app)

        db_session.expire_all()
        still = get_search_settings_by_id(db_session, ss_id)
        assert still is not None
        assert still.reclaim_status == IndexReclaimStatus.PENDING
    finally:
        _delete_settings(db_session, ss)


def test_execute_task_body_drives_one_step_under_lock(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reclaim_tasks, "OLD_INDEX_RECLAIM_ENABLED", True)
    monkeypatch.setattr(
        reclaim_tasks, "is_active_port_backfill_source", lambda *_a, **_k: False
    )
    ss = _make_past_settings(db_session, IndexReclaimStatus.PENDING)
    ss_id = ss.id
    try:
        reclaim_tasks.execute_old_index_reclaim(MagicMock(), "tenant", ss_id)
        # The task body commits on its own session, so this one must re-read the row.
        db_session.expire_all()
        driven = get_search_settings_by_id(db_session, ss_id)
        assert driven is not None
        assert driven.reclaim_status == IndexReclaimStatus.SOAKING
    finally:
        _delete_settings(db_session, ss)


def test_execute_task_body_honors_kill_switch(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task already queued when the flag was turned off must not drive its row, so
    disabling the feature stops work without waiting for the queue to drain."""
    monkeypatch.setattr(reclaim_tasks, "OLD_INDEX_RECLAIM_ENABLED", False)
    monkeypatch.setattr(
        reclaim_tasks, "is_active_port_backfill_source", lambda *_a, **_k: False
    )
    ss = _make_past_settings(db_session, IndexReclaimStatus.PENDING)
    ss_id = ss.id
    try:
        reclaim_tasks.execute_old_index_reclaim(MagicMock(), "tenant", ss_id)
        db_session.expire_all()
        row = get_search_settings_by_id(db_session, ss_id)
        assert row is not None
        assert row.reclaim_status == IndexReclaimStatus.PENDING
    finally:
        _delete_settings(db_session, ss)
