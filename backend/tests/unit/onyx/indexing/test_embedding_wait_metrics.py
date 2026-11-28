"""embed_and_stream records the rate limit waits of a batch as stage metrics."""

from typing import Any
from unittest.mock import MagicMock, patch

from onyx.db.index_attempt_metrics_models import IndexAttemptStage
from onyx.indexing.indexing_pipeline import ChunkEmbeddingResult, embed_and_stream
from onyx.natural_language_processing.embedding_rate_limit import EmbeddingWaitTotals

_PIPELINE = "onyx.indexing.indexing_pipeline"


def _run_batch(wait_totals: EmbeddingWaitTotals, waits: tuple[float, float]) -> dict:
    embedder = MagicMock()
    embedder.embedding_model.wait_totals = wait_totals

    def embed(**_: Any) -> ChunkEmbeddingResult:
        wait_totals.add_rate_limit_wait(waits[0])
        wait_totals.add_provider_throttle_wait(waits[1])
        return ChunkEmbeddingResult(successful_chunk_ids=[], connector_failures=[])

    recorded: dict[IndexAttemptStage, int] = {}
    with (
        patch(f"{_PIPELINE}._embed_chunks_to_store", side_effect=embed),
        patch(f"{_PIPELINE}.emit_stage_counter"),
        patch(
            f"{_PIPELINE}.safe_record_single_event_if_set",
            side_effect=lambda stage, _attempt_id, ms: recorded.__setitem__(stage, ms),
        ),
    ):
        with embed_and_stream([], embedder, "public", None, attempt_id=7):
            pass
    return recorded


def test_batch_waits_are_recorded_as_stages() -> None:
    wait_totals = EmbeddingWaitTotals()
    # Earlier batches of the same model must not count toward this batch.
    wait_totals.add_rate_limit_wait(100)

    recorded = _run_batch(wait_totals, (2.5, 1.0))

    assert recorded[IndexAttemptStage.EMBEDDING_RATE_LIMIT_WAIT] == 2500
    assert recorded[IndexAttemptStage.EMBEDDING_PROVIDER_THROTTLE_WAIT] == 1000
    assert IndexAttemptStage.EMBEDDING in recorded


def test_batches_without_waits_record_no_wait_stages() -> None:
    recorded = _run_batch(EmbeddingWaitTotals(), (0, 0))

    assert IndexAttemptStage.EMBEDDING_RATE_LIMIT_WAIT not in recorded
    assert IndexAttemptStage.EMBEDDING_PROVIDER_THROTTLE_WAIT not in recorded
