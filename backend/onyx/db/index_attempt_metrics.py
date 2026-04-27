"""Stage-level metric primitives for an `IndexAttempt`.

This module owns the canonical taxonomy of pipeline stages we measure during
docfetching + docprocessing, the per-stage scope that the API/UI use to
decide how to display each stage, and the write helpers used by the
indexing pipeline to record stage timings.

The ordering of `IndexAttemptStage` members is intentional and represents
the natural pipeline order — the API surfaces this order to the frontend so
it can render the "Pipeline order" sort mode without duplicating the
sequence client-side.

Recording must NEVER fail an indexing attempt. The consumer-facing helpers
(``time_stage`` and ``StageEventBuffer.flush``) wrap the underlying upsert
in a try/except that logs and swallows. The lower-level
``record_stage_aggregate`` and ``record_single_event`` raise on failure so
they remain testable in isolation.
"""

import datetime
import time
from collections.abc import Generator
from contextlib import contextmanager
from enum import Enum as PyEnum

from sqlalchemy import case
from sqlalchemy import cast
from sqlalchemy import Float
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.utils.logger import setup_logger

logger = setup_logger()


# Defensive lower bound on a recorded duration (ms). Negative values are not
# meaningful and would corrupt aggregates; protect against monotonic clock
# weirdness that could in theory yield a negative delta.
_MIN_DURATION_MS = 0


class IndexAttemptStage(str, PyEnum):
    """Canonical pipeline stages for an `IndexAttempt`.

    Member declaration order matches the natural temporal order of the
    pipeline (docfetching first, then docprocessing). Both backend
    serialization and frontend "Pipeline order" display rely on this.
    """

    # --- Docfetching (one process per attempt) ---
    CONNECTOR_VALIDATION = "CONNECTOR_VALIDATION"
    PERMISSION_VALIDATION = "PERMISSION_VALIDATION"
    CHECKPOINT_LOAD = "CHECKPOINT_LOAD"
    CONNECTOR_FETCH = "CONNECTOR_FETCH"
    HIERARCHY_UPSERT = "HIERARCHY_UPSERT"
    DOC_BATCH_STORE = "DOC_BATCH_STORE"
    DOC_BATCH_ENQUEUE = "DOC_BATCH_ENQUEUE"

    # --- Docprocessing (one task per batch, many tasks per attempt) ---
    QUEUE_WAIT = "QUEUE_WAIT"
    DOCPROCESSING_SETUP = "DOCPROCESSING_SETUP"
    BATCH_LOAD = "BATCH_LOAD"
    DOC_DB_PREPARE = "DOC_DB_PREPARE"
    IMAGE_PROCESSING = "IMAGE_PROCESSING"
    CHUNKING = "CHUNKING"
    CONTEXTUAL_RAG = "CONTEXTUAL_RAG"
    EMBEDDING = "EMBEDDING"
    VECTOR_DB_WRITE = "VECTOR_DB_WRITE"
    POST_INDEX_DB_UPDATE = "POST_INDEX_DB_UPDATE"
    COORDINATION_UPDATE = "COORDINATION_UPDATE"

    # --- Aggregate ---
    BATCH_TOTAL = "BATCH_TOTAL"


class StageScope(str, PyEnum):
    """How often a stage fires per attempt.

    Used by the admin UI to decide where to render each stage:

    - `ATTEMPT_LEVEL` stages have at most one event per attempt and are
      shown as a small "Attempt overhead" disclosure.
    - `BATCH_LEVEL` stages have many events per attempt and contribute to
      the per-batch stacked bar / detail table.
    """

    ATTEMPT_LEVEL = "ATTEMPT_LEVEL"
    BATCH_LEVEL = "BATCH_LEVEL"


# Single source of truth for stage scope. The API serializes this onto each
# row so the frontend never has to duplicate the mapping.
STAGE_SCOPE: dict[IndexAttemptStage, StageScope] = {
    IndexAttemptStage.CONNECTOR_VALIDATION: StageScope.ATTEMPT_LEVEL,
    IndexAttemptStage.PERMISSION_VALIDATION: StageScope.ATTEMPT_LEVEL,
    IndexAttemptStage.CHECKPOINT_LOAD: StageScope.ATTEMPT_LEVEL,
    IndexAttemptStage.CONNECTOR_FETCH: StageScope.BATCH_LEVEL,
    IndexAttemptStage.HIERARCHY_UPSERT: StageScope.BATCH_LEVEL,
    IndexAttemptStage.DOC_BATCH_STORE: StageScope.BATCH_LEVEL,
    IndexAttemptStage.DOC_BATCH_ENQUEUE: StageScope.BATCH_LEVEL,
    IndexAttemptStage.QUEUE_WAIT: StageScope.BATCH_LEVEL,
    IndexAttemptStage.DOCPROCESSING_SETUP: StageScope.BATCH_LEVEL,
    IndexAttemptStage.BATCH_LOAD: StageScope.BATCH_LEVEL,
    IndexAttemptStage.DOC_DB_PREPARE: StageScope.BATCH_LEVEL,
    IndexAttemptStage.IMAGE_PROCESSING: StageScope.BATCH_LEVEL,
    IndexAttemptStage.CHUNKING: StageScope.BATCH_LEVEL,
    IndexAttemptStage.CONTEXTUAL_RAG: StageScope.BATCH_LEVEL,
    IndexAttemptStage.EMBEDDING: StageScope.BATCH_LEVEL,
    IndexAttemptStage.VECTOR_DB_WRITE: StageScope.BATCH_LEVEL,
    IndexAttemptStage.POST_INDEX_DB_UPDATE: StageScope.BATCH_LEVEL,
    IndexAttemptStage.COORDINATION_UPDATE: StageScope.BATCH_LEVEL,
    IndexAttemptStage.BATCH_TOTAL: StageScope.BATCH_LEVEL,
}


# Defensive sanity check: every enum member must have a scope. This runs at
# import time so a future contributor adding a stage but forgetting the
# scope mapping fails fast rather than at API serialization.
_missing_scopes = set(IndexAttemptStage) - set(STAGE_SCOPE)
if _missing_scopes:
    raise RuntimeError(
        f"IndexAttemptStage members missing from STAGE_SCOPE: {_missing_scopes}"
    )


def record_stage_aggregate(
    db_session: Session,
    *,
    index_attempt_id: int,
    stage: IndexAttemptStage,
    event_count: int,
    total_duration_ms: int,
    m2_duration_ms: float,
    min_duration_ms: int,
    max_duration_ms: int,
    now: datetime.datetime | None = None,
) -> None:
    """Upsert a stage aggregate row for an attempt.

    Combines the incoming aggregate ``(event_count, total_duration_ms,
    m2_duration_ms, min, max)`` with the existing row using Chan's parallel
    combination formula (numerically stable variance accumulation without
    needing per-sample storage). Implemented as a single
    ``INSERT ... ON CONFLICT DO UPDATE`` so we don't need a SELECT-then-write
    transaction or row lock — the DB handles concurrent writers correctly.

    Raises on DB errors. Callers that must not fail (i.e. all instrumentation
    call sites) should use ``time_stage`` or ``StageEventBuffer`` instead,
    which wrap this in a try/except.
    """
    if event_count <= 0:
        return

    # Imported here to avoid a circular dependency: ``onyx.db.models`` imports
    # ``IndexAttemptStage`` from this module.
    from onyx.db.models import IndexAttemptStageMetric

    if now is None:
        now = datetime.datetime.now(datetime.timezone.utc)

    insert_stmt = pg_insert(IndexAttemptStageMetric).values(
        index_attempt_id=index_attempt_id,
        stage=stage,
        event_count=event_count,
        total_duration_ms=total_duration_ms,
        m2_duration_ms=m2_duration_ms,
        min_duration_ms=min_duration_ms,
        max_duration_ms=max_duration_ms,
        time_first_event=now,
        time_last_event=now,
    )

    excluded = insert_stmt.excluded
    metric = IndexAttemptStageMetric

    # Chan's parallel combination of M2 (sum of squared deviations from the
    # mean) for two aggregates A (existing row) and B (incoming):
    #
    #   M2_new = M2_a + M2_b + (mean_b - mean_a)^2 * (n_a * n_b / (n_a + n_b))
    #
    # In Postgres, all SET expressions in an UPDATE are evaluated against the
    # row's pre-update values regardless of their order in the SET list, so
    # we can reference ``metric.event_count`` / ``metric.total_duration_ms``
    # freely even though they're also being updated below.
    new_count = metric.event_count + excluded.event_count
    delta_means = cast(excluded.total_duration_ms, Float) / cast(
        excluded.event_count, Float
    ) - cast(metric.total_duration_ms, Float) / case(
        (metric.event_count == 0, 1),
        else_=metric.event_count,
    )
    cross_term = (
        func.power(delta_means, 2)
        * cast(metric.event_count, Float)
        * cast(excluded.event_count, Float)
        / cast(new_count, Float)
    )
    new_m2 = (
        metric.m2_duration_ms
        + excluded.m2_duration_ms
        + case(
            (metric.event_count == 0, 0.0),
            else_=cross_term,
        )
    )

    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["index_attempt_id", "stage"],
        set_=dict(
            m2_duration_ms=new_m2,
            event_count=new_count,
            total_duration_ms=metric.total_duration_ms + excluded.total_duration_ms,
            min_duration_ms=func.least(
                metric.min_duration_ms, excluded.min_duration_ms
            ),
            max_duration_ms=func.greatest(
                metric.max_duration_ms, excluded.max_duration_ms
            ),
            time_last_event=excluded.time_last_event,
        ),
    )

    db_session.execute(upsert_stmt)
    db_session.commit()


def record_single_event(
    db_session: Session,
    *,
    index_attempt_id: int,
    stage: IndexAttemptStage,
    duration_ms: int,
    now: datetime.datetime | None = None,
) -> None:
    """Convenience wrapper for the single-sample case.

    Equivalent to ``record_stage_aggregate(..., event_count=1,
    m2_duration_ms=0.0, min=duration_ms, max=duration_ms)``. The Chan
    formula collapses correctly for an incoming aggregate of size 1 (a
    standard Welford update).
    """
    duration_ms = max(_MIN_DURATION_MS, duration_ms)
    record_stage_aggregate(
        db_session,
        index_attempt_id=index_attempt_id,
        stage=stage,
        event_count=1,
        total_duration_ms=duration_ms,
        m2_duration_ms=0.0,
        min_duration_ms=duration_ms,
        max_duration_ms=duration_ms,
        now=now,
    )


@contextmanager
def time_stage(
    stage: IndexAttemptStage,
    index_attempt_id: int,
) -> Generator[None, None, None]:
    """Time the wrapped block and record a single stage event on exit.

    Records the duration even if the wrapped block raises — a stage that
    runs for 30 seconds and then crashes still has meaningful timing. The
    caller's exception is re-raised after the recording attempt.

    Recording errors are swallowed and logged; they must never fail an
    indexing attempt.
    """
    start = time.monotonic()
    try:
        yield
    finally:
        duration_ms = max(_MIN_DURATION_MS, int((time.monotonic() - start) * 1000))
        try:
            with get_session_with_current_tenant() as db_session:
                record_single_event(
                    db_session,
                    index_attempt_id=index_attempt_id,
                    stage=stage,
                    duration_ms=duration_ms,
                )
        except Exception:
            logger.exception(
                f"Failed to record stage event {stage.value} "
                f"for attempt {index_attempt_id}"
            )


class StageEventBuffer:
    """In-memory accumulator for many small stage events.

    Use this when a stage fires hundreds or thousands of times per pipeline
    batch (e.g. per ``EmbeddingModel.encode`` call) and we want to flush a
    single aggregate upsert at the end of the batch instead of paying the
    DB round-trip per event.

    Maintains a Welford-style running ``(count, mean, M2)`` plus exact
    integer ``total``, ``min``, and ``max``. ``flush()`` performs a single
    ``record_stage_aggregate`` call and resets the buffer. Recording
    errors during flush are swallowed and logged.
    """

    def __init__(
        self,
        stage: IndexAttemptStage,
        index_attempt_id: int,
    ) -> None:
        self.stage = stage
        self.index_attempt_id = index_attempt_id
        self._count = 0
        self._total = 0
        # `_mean` is a float used only by Welford's variance update; the
        # canonical mean for downstream consumers is `_total / _count`,
        # which is exact.
        self._mean = 0.0
        self._m2 = 0.0
        self._min: int | None = None
        self._max: int | None = None

    @property
    def count(self) -> int:
        return self._count

    def record(self, duration_ms: int) -> None:
        """Add one sample to the buffer using Welford's online update."""
        duration_ms = max(_MIN_DURATION_MS, duration_ms)
        self._count += 1
        self._total += duration_ms
        delta = duration_ms - self._mean
        self._mean += delta / self._count
        delta2 = duration_ms - self._mean
        self._m2 += delta * delta2
        self._min = duration_ms if self._min is None else min(self._min, duration_ms)
        self._max = duration_ms if self._max is None else max(self._max, duration_ms)

    @contextmanager
    def time(self) -> Generator[None, None, None]:
        """Context manager that times a block and records the duration."""
        start = time.monotonic()
        try:
            yield
        finally:
            self.record(int((time.monotonic() - start) * 1000))

    def flush(self) -> None:
        """Flush the buffer to a single DB upsert, then reset.

        Swallows and logs DB errors. Resets the buffer regardless so a
        repeated flush after a transient DB failure doesn't double-count.
        """
        if self._count == 0:
            return

        # Snapshot before reset so a re-entrant ``record()`` during the DB
        # call (unlikely but defensive) doesn't corrupt the in-flight values.
        count = self._count
        total = self._total
        m2 = self._m2
        min_d = self._min if self._min is not None else 0
        max_d = self._max if self._max is not None else 0
        self._reset()

        try:
            with get_session_with_current_tenant() as db_session:
                record_stage_aggregate(
                    db_session,
                    index_attempt_id=self.index_attempt_id,
                    stage=self.stage,
                    event_count=count,
                    total_duration_ms=total,
                    m2_duration_ms=m2,
                    min_duration_ms=min_d,
                    max_duration_ms=max_d,
                )
        except Exception:
            logger.exception(
                f"Failed to flush StageEventBuffer for "
                f"{self.stage.value} / attempt {self.index_attempt_id}"
            )

    def _reset(self) -> None:
        self._count = 0
        self._total = 0
        self._mean = 0.0
        self._m2 = 0.0
        self._min = None
        self._max = None
