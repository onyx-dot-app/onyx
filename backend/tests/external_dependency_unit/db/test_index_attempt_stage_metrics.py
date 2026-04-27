"""External dependency unit tests for stage-metric write helpers.

Validates the upsert + Chan-combination logic against real Postgres:

- ``record_single_event`` produces the right aggregate for a fresh row and
  for repeated events on the same ``(attempt, stage)`` key.
- The upsert correctly preserves ``time_first_event`` across updates while
  refreshing ``time_last_event``.
- ``record_stage_aggregate`` with pre-aggregated buffers (Chan parallel
  combination) produces a numerically identical M2 to streaming the same
  samples one at a time. This is the test that protects the SQL formula
  from regressions.
- Concurrent ``record_single_event`` writers do not lose updates and do
  not raise — Postgres ``INSERT ... ON CONFLICT DO UPDATE`` handles row
  contention correctly.
- ``StageEventBuffer.flush`` produces a single DB write with the correct
  aggregated values.
- Records with ``event_count <= 0`` are no-ops.
"""

import math
import statistics
from collections.abc import Generator
from concurrent.futures import as_completed
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import IndexingStatus
from onyx.db.index_attempt_metrics import record_single_event
from onyx.db.index_attempt_metrics import record_stage_aggregate
from onyx.db.index_attempt_metrics import StageEventBuffer
from onyx.db.index_attempt_metrics_models import IndexAttemptStage
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptStageMetric
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
        # IndexAttempt has no ON DELETE CASCADE from cc_pair, but
        # IndexAttemptStageMetric does cascade from IndexAttempt — so
        # deleting the attempt cleans up its metric rows automatically.
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


@pytest.fixture
def index_attempt(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
) -> IndexAttempt:
    attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=None,
        from_beginning=False,
        status=IndexingStatus.NOT_STARTED,
    )
    db_session.add(attempt)
    db_session.commit()
    db_session.refresh(attempt)
    return attempt


def _get_metric(
    db_session: Session,
    attempt_id: int,
    stage: IndexAttemptStage,
) -> IndexAttemptStageMetric | None:
    db_session.expire_all()
    return db_session.execute(
        select(IndexAttemptStageMetric)
        .where(IndexAttemptStageMetric.index_attempt_id == attempt_id)
        .where(IndexAttemptStageMetric.stage == stage)
    ).scalar_one_or_none()


class TestRecordSingleEvent:
    def test_first_event_creates_row(
        self,
        db_session: Session,
        index_attempt: IndexAttempt,
    ) -> None:
        record_single_event(
            db_session,
            index_attempt_id=index_attempt.id,
            stage=IndexAttemptStage.CHUNKING,
            duration_ms=42,
        )

        row = _get_metric(db_session, index_attempt.id, IndexAttemptStage.CHUNKING)
        assert row is not None
        assert row.event_count == 1
        assert row.total_duration_ms == 42
        assert row.m2_duration_ms == pytest.approx(0.0)
        assert row.min_duration_ms == 42
        assert row.max_duration_ms == 42
        assert row.time_first_event is not None
        assert row.time_last_event is not None
        assert row.time_first_event == row.time_last_event

    def test_streamed_samples_match_welford(
        self,
        db_session: Session,
        index_attempt: IndexAttempt,
    ) -> None:
        """Feeding samples one at a time should yield the same M2 as
        ``statistics.variance(samples) * (n - 1)``."""
        samples = [10, 20, 30, 40, 50]
        for s in samples:
            record_single_event(
                db_session,
                index_attempt_id=index_attempt.id,
                stage=IndexAttemptStage.EMBEDDING,
                duration_ms=s,
            )

        row = _get_metric(db_session, index_attempt.id, IndexAttemptStage.EMBEDDING)
        assert row is not None
        assert row.event_count == len(samples)
        assert row.total_duration_ms == sum(samples)
        assert row.min_duration_ms == min(samples)
        assert row.max_duration_ms == max(samples)

        expected_m2 = statistics.variance(samples) * (len(samples) - 1)
        assert math.isclose(row.m2_duration_ms, expected_m2, rel_tol=1e-9)

    def test_time_first_event_preserved_across_updates(
        self,
        db_session: Session,
        index_attempt: IndexAttempt,
    ) -> None:
        """``time_first_event`` is set on insert and never moves; only
        ``time_last_event`` advances on subsequent upserts."""
        record_single_event(
            db_session,
            index_attempt_id=index_attempt.id,
            stage=IndexAttemptStage.VECTOR_DB_WRITE,
            duration_ms=10,
        )
        first_row = _get_metric(
            db_session, index_attempt.id, IndexAttemptStage.VECTOR_DB_WRITE
        )
        assert first_row is not None
        first_seen = first_row.time_first_event
        first_last = first_row.time_last_event
        assert first_seen is not None
        assert first_last is not None

        # A small wallclock delay between events keeps the timestamps
        # distinct without slowing the test meaningfully.
        import time as _time

        _time.sleep(0.01)

        record_single_event(
            db_session,
            index_attempt_id=index_attempt.id,
            stage=IndexAttemptStage.VECTOR_DB_WRITE,
            duration_ms=20,
        )
        second_row = _get_metric(
            db_session, index_attempt.id, IndexAttemptStage.VECTOR_DB_WRITE
        )
        assert second_row is not None
        assert second_row.time_first_event == first_seen
        assert second_row.time_last_event is not None
        assert second_row.time_last_event > first_last


class TestChanCombination:
    """The Chan parallel-combination formula encoded in the upsert SQL must
    yield the same M2 whether samples are fed one at a time or as multiple
    pre-aggregated buffers."""

    def test_chunked_aggregates_match_streamed(
        self,
        db_session: Session,
        index_attempt: IndexAttempt,
    ) -> None:
        samples = [10, 20, 30, 40, 50]
        chunk_a = samples[:2]  # [10, 20]
        chunk_b = samples[2:]  # [30, 40, 50]

        # Pre-aggregate each chunk, then submit the two aggregates to the
        # same ``(attempt, stage)`` key.
        for chunk in (chunk_a, chunk_b):
            record_stage_aggregate(
                db_session,
                index_attempt_id=index_attempt.id,
                stage=IndexAttemptStage.CONTEXTUAL_RAG,
                event_count=len(chunk),
                total_duration_ms=sum(chunk),
                m2_duration_ms=(
                    statistics.variance(chunk) * (len(chunk) - 1)
                    if len(chunk) > 1
                    else 0.0
                ),
                min_duration_ms=min(chunk),
                max_duration_ms=max(chunk),
            )

        row = _get_metric(
            db_session, index_attempt.id, IndexAttemptStage.CONTEXTUAL_RAG
        )
        assert row is not None
        assert row.event_count == len(samples)
        assert row.total_duration_ms == sum(samples)
        assert row.min_duration_ms == min(samples)
        assert row.max_duration_ms == max(samples)

        expected_m2 = statistics.variance(samples) * (len(samples) - 1)
        assert math.isclose(row.m2_duration_ms, expected_m2, rel_tol=1e-9)


class TestNoOpInputs:
    def test_zero_event_count_is_noop(
        self,
        db_session: Session,
        index_attempt: IndexAttempt,
    ) -> None:
        record_stage_aggregate(
            db_session,
            index_attempt_id=index_attempt.id,
            stage=IndexAttemptStage.IMAGE_PROCESSING,
            event_count=0,
            total_duration_ms=0,
            m2_duration_ms=0.0,
            min_duration_ms=0,
            max_duration_ms=0,
        )
        row = _get_metric(
            db_session, index_attempt.id, IndexAttemptStage.IMAGE_PROCESSING
        )
        assert row is None

    def test_negative_event_count_is_noop(
        self,
        db_session: Session,
        index_attempt: IndexAttempt,
    ) -> None:
        record_stage_aggregate(
            db_session,
            index_attempt_id=index_attempt.id,
            stage=IndexAttemptStage.IMAGE_PROCESSING,
            event_count=-1,
            total_duration_ms=10,
            m2_duration_ms=0.0,
            min_duration_ms=10,
            max_duration_ms=10,
        )
        row = _get_metric(
            db_session, index_attempt.id, IndexAttemptStage.IMAGE_PROCESSING
        )
        assert row is None


class TestStageEventBuffer:
    def test_flush_writes_single_aggregate(
        self,
        db_session: Session,
        index_attempt: IndexAttempt,
        tenant_context: None,  # noqa: ARG002 — buffer.flush() needs the tenant context
    ) -> None:
        samples = [5, 15, 25, 35, 45]
        buf = StageEventBuffer(
            stage=IndexAttemptStage.EMBEDDING,
            index_attempt_id=index_attempt.id,
        )
        for s in samples:
            buf.record(s)
        assert buf.count == len(samples)

        buf.flush()
        # Buffer is reset post-flush.
        assert buf.count == 0

        row = _get_metric(db_session, index_attempt.id, IndexAttemptStage.EMBEDDING)
        assert row is not None
        assert row.event_count == len(samples)
        assert row.total_duration_ms == sum(samples)
        assert row.min_duration_ms == min(samples)
        assert row.max_duration_ms == max(samples)

        expected_m2 = statistics.variance(samples) * (len(samples) - 1)
        assert math.isclose(row.m2_duration_ms, expected_m2, rel_tol=1e-9)

    def test_empty_flush_is_noop(
        self,
        db_session: Session,
        index_attempt: IndexAttempt,
        tenant_context: None,  # noqa: ARG002
    ) -> None:
        buf = StageEventBuffer(
            stage=IndexAttemptStage.CHUNKING,
            index_attempt_id=index_attempt.id,
        )
        buf.flush()  # nothing recorded; should not write a row
        assert (
            _get_metric(db_session, index_attempt.id, IndexAttemptStage.CHUNKING)
            is None
        )


class TestConcurrentUpserts:
    def test_concurrent_record_single_event_no_lost_updates(
        self,
        db_session: Session,
        index_attempt: IndexAttempt,
        tenant_context: None,  # noqa: ARG002 — child threads need the tenant context
    ) -> None:
        """N threads each record one event for the same (attempt, stage).
        The final row must have event_count == N and total == N * duration.
        """
        n_workers = 16
        per_event_ms = 7

        def worker() -> None:
            with get_session_with_current_tenant() as session:
                record_single_event(
                    session,
                    index_attempt_id=index_attempt.id,
                    stage=IndexAttemptStage.CHUNKING,
                    duration_ms=per_event_ms,
                )

        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            futures = [ex.submit(worker) for _ in range(n_workers)]
            for f in as_completed(futures):
                # Re-raise any worker exception so a failed upsert surfaces.
                f.result()

        row = _get_metric(db_session, index_attempt.id, IndexAttemptStage.CHUNKING)
        assert row is not None
        assert row.event_count == n_workers
        assert row.total_duration_ms == n_workers * per_event_ms
        assert row.min_duration_ms == per_event_ms
        assert row.max_duration_ms == per_event_ms
        # All samples are equal, so variance and therefore M2 must be 0.
        assert math.isclose(row.m2_duration_ms, 0.0, abs_tol=1e-9)
