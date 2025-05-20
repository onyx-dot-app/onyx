from bisect import bisect_left
from typing import cast
from typing import Optional

from pydantic import BaseModel

from onyx.context.search.models import InferenceChunk
from onyx.utils.logger import setup_logger
from tests.regression.search_quality.util_data import GroundTruth

logger = setup_logger(__name__)


class Metrics(BaseModel):
    ground_truth_jaccard_similarity: Optional[float]
    ground_truth_missing_chunks_ratio: Optional[float]
    ground_truth_average_rank_change: Optional[float]

    topk_jaccard_similarity: float
    topk_missing_chunks_ratio: float
    topk_average_rank_change: float


metric_names = list(Metrics.model_fields.keys())


def evaluate_one_query(
    search_chunks: list[InferenceChunk],
    rerank_chunks: list[InferenceChunk],
    true_chunks: list[GroundTruth],
    topk: int,
) -> Metrics:
    """Computes metrics for the search results, relative to the ground truth and reranked results."""
    # TODO:
    search_topk = search_chunks[:topk]
    true_topk = true_chunks[:topk]

    # get the score adjusted topk (topk where the score is at least 50% of the top score)
    # could be more than topk if top scores are similar, may or may not be a good thing
    # can change by swapping rerank_results with rerank_topk in bisect
    adj_topk = bisect_left(
        true_chunks,
        -0.5 * cast(float, true_chunks[0].score),
        key=lambda x: -cast(float, x.score),
    )
    search_adj_topk = search_chunks[:adj_topk]
    true_adj_topk = true_chunks[:adj_topk]

    # compute metrics
    search_ranks = {chunk.unique_id: rank for rank, chunk in enumerate(search_chunks)}
    return Metrics(
        # TODO:
        *_compute_jaccard_and_missing_chunks_ratio(search_adj_topk, true_adj_topk),
        _compute_average_rank_change(search_ranks, true_adj_topk),
        *_compute_jaccard_and_missing_chunks_ratio(search_topk, true_topk),
        _compute_average_rank_change(search_ranks, true_topk),
    )


def _compute_jaccard_and_missing_chunks_ratio(
    search_topk: list[InferenceChunk], rerank_topk: list[InferenceChunk]
) -> tuple[float, float]:
    search_chunkids = {chunk.unique_id for chunk in search_topk}
    rerank_chunkids = {chunk.unique_id for chunk in rerank_topk}
    jaccard_similarity = len(search_chunkids & rerank_chunkids) / len(
        search_chunkids | rerank_chunkids
    )
    missing_chunks_ratio = len(rerank_chunkids - search_chunkids) / len(rerank_chunkids)
    return jaccard_similarity, missing_chunks_ratio


def _compute_average_rank_change(
    search_ranks: dict[str, int], rerank_topk: list[InferenceChunk]
) -> float:
    rank_changes = [
        abs(search_ranks[chunk.unique_id] - rerank_rank)
        for rerank_rank, chunk in enumerate(rerank_topk)
    ]
    return sum(rank_changes) / len(rank_changes)
