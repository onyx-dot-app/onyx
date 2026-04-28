"""Stage-level metric primitives for an `IndexAttempt`.

This module owns the canonical taxonomy of pipeline stages we measure during
docfetching + docprocessing, plus the per-stage scope that the API/UI use to
decide how to display each stage. Storage and write helpers live alongside
the SQLAlchemy model in `onyx.db.models` and (in a follow-up phase) in this
module.

The ordering of `IndexAttemptStage` members is intentional and represents
the natural pipeline order — the API surfaces this order to the frontend so
it can render the "Pipeline order" sort mode without duplicating the
sequence client-side.
"""

from enum import Enum as PyEnum


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
