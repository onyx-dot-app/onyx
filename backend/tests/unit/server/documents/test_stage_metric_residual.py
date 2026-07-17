"""Unit tests for the BATCH_UNACCOUNTED residual synthesis.

``synthesize_unaccounted`` is a pure function over stage snapshots, so it is
tested without a DB. Covers the residual math, the in-span component set, the
clamp, and the absent-BATCH_TOTAL case.
"""

from onyx.db.index_attempt_metrics_models import IndexAttemptStage
from onyx.db.index_attempt_metrics_models import STAGE_SCOPE
from onyx.server.documents.models import _BATCH_TOTAL_COMPONENT_STAGES
from onyx.server.documents.models import IndexAttemptStageMetricSnapshot
from onyx.server.documents.models import synthesize_unaccounted


def _snap(
    stage: IndexAttemptStage, total_ms: int, event_count: int = 1
) -> IndexAttemptStageMetricSnapshot:
    return IndexAttemptStageMetricSnapshot(
        stage=stage,
        scope=STAGE_SCOPE[stage],
        event_count=event_count,
        total_duration_ms=total_ms,
        avg_duration_ms=(total_ms / event_count if event_count else None),
        std_dev_duration_ms=None,
        min_duration_ms=None,
        max_duration_ms=None,
        time_first_event=None,
        time_last_event=None,
    )


def test_residual_is_total_minus_in_span_components() -> None:
    snaps = [
        _snap(IndexAttemptStage.VECTOR_DB_WRITE, 200),
        _snap(IndexAttemptStage.EMBEDDING, 50),
        _snap(IndexAttemptStage.COORD_LOCK_ACQUIRE_WAIT, 700),
        _snap(IndexAttemptStage.BATCH_TOTAL, 1000),
    ]
    residual = synthesize_unaccounted(snaps)
    assert residual is not None
    assert residual.stage == IndexAttemptStage.BATCH_UNACCOUNTED
    assert residual.scope == STAGE_SCOPE[IndexAttemptStage.BATCH_UNACCOUNTED]
    assert residual.total_duration_ms == 1000 - (200 + 50 + 700)
    # avg uses BATCH_TOTAL's event_count (one batch here).
    assert residual.avg_duration_ms == 50.0


def test_residual_excludes_pre_batch_total_stages() -> None:
    # QUEUE_WAIT / DOCPROCESSING_SETUP / BATCH_LOAD precede batch_total_start
    # and must NOT be subtracted from BATCH_TOTAL.
    snaps = [
        _snap(IndexAttemptStage.QUEUE_WAIT, 9999),
        _snap(IndexAttemptStage.DOCPROCESSING_SETUP, 9999),
        _snap(IndexAttemptStage.BATCH_LOAD, 9999),
        _snap(IndexAttemptStage.VECTOR_DB_WRITE, 100),
        _snap(IndexAttemptStage.BATCH_TOTAL, 1000),
    ]
    residual = synthesize_unaccounted(snaps)
    assert residual is not None
    assert residual.total_duration_ms == 900


def test_residual_clamps_at_zero_when_components_exceed_total() -> None:
    snaps = [
        _snap(IndexAttemptStage.VECTOR_DB_WRITE, 5000),
        _snap(IndexAttemptStage.BATCH_TOTAL, 1000),
    ]
    residual = synthesize_unaccounted(snaps)
    assert residual is not None
    assert residual.total_duration_ms == 0


def test_residual_none_without_batch_total() -> None:
    snaps = [_snap(IndexAttemptStage.VECTOR_DB_WRITE, 100)]
    assert synthesize_unaccounted(snaps) is None


def test_component_set_excludes_non_in_span_stages() -> None:
    must_be_excluded = {
        IndexAttemptStage.QUEUE_WAIT,
        IndexAttemptStage.DOCPROCESSING_SETUP,
        IndexAttemptStage.BATCH_LOAD,
        IndexAttemptStage.BATCH_TOTAL,
        IndexAttemptStage.BATCH_UNACCOUNTED,
        # docfetching-process stages
        IndexAttemptStage.CONNECTOR_VALIDATION,
        IndexAttemptStage.CONNECTOR_FETCH,
        IndexAttemptStage.DOC_BATCH_ENQUEUE,
    }
    assert not (_BATCH_TOTAL_COMPONENT_STAGES & must_be_excluded)


def test_component_set_includes_new_wait_timers() -> None:
    for stage in (
        IndexAttemptStage.DOC_LOCK_ACQUIRE_WAIT,
        IndexAttemptStage.COORD_LOCK_ACQUIRE_WAIT,
        IndexAttemptStage.ENRICHMENT_PREP,
        IndexAttemptStage.FINALIZATION,
        IndexAttemptStage.GC_COLLECT,
    ):
        assert stage in _BATCH_TOTAL_COMPONENT_STAGES


def test_residual_uses_component_totals_not_averages() -> None:
    # EMBEDDING fires multiple times per batch (event_count > batch count).
    # The residual must subtract TOTALS, and its avg must use BATCH_TOTAL's
    # event_count (the batch count), not the component event counts.
    snaps = [
        _snap(IndexAttemptStage.EMBEDDING, 300, event_count=3),  # avg 100, total 300
        _snap(IndexAttemptStage.VECTOR_DB_WRITE, 200, event_count=1),
        _snap(IndexAttemptStage.BATCH_TOTAL, 1000, event_count=4),
    ]
    residual = synthesize_unaccounted(snaps)
    assert residual is not None
    assert residual.total_duration_ms == 1000 - (300 + 200)
    assert residual.event_count == 4
    assert residual.avg_duration_ms == 500 / 4


def test_warn_log_fires_when_components_exceed_total(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import onyx.server.documents.models as models_module

    calls: list[tuple] = []
    monkeypatch.setattr(
        models_module.logger, "warning", lambda *a, **k: calls.append((a, k))
    )
    snaps = [
        _snap(IndexAttemptStage.VECTOR_DB_WRITE, 5000),
        _snap(IndexAttemptStage.BATCH_TOTAL, 1000),
    ]
    residual = synthesize_unaccounted(snaps)
    assert residual is not None
    assert residual.total_duration_ms == 0
    assert len(calls) == 1
