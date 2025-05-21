from typing import Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.context.search.models import InferenceChunk
from onyx.db.models import Document
from onyx.utils.logger import setup_logger
from tests.regression.search_quality.util_retrieve import group_by_documents

logger = setup_logger(__name__)


class Metrics(BaseModel):
    # computed if ground truth is provided
    ground_truth_ratio_topk: Optional[float] = None
    ground_truth_avg_rank_delta: Optional[float] = None

    # computed if reranked results are provided
    soft_truth_ratio_topk: Optional[float] = None
    soft_truth_avg_rank_delta: Optional[float] = None


metric_names = list(Metrics.model_fields.keys())


def get_corresponding_document(
    doc_link: str, db_session: Session
) -> Optional[Document]:
    """Get the corresponding document from the database."""
    doc_filter = db_session.query(Document).filter(Document.link == doc_link)
    count = doc_filter.count()
    if count == 0:
        logger.warning(f"Could not find document with link {doc_link}, ignoring")
        return None
    if count > 1:
        logger.warning(f"Found multiple documents with link {doc_link}, using first")
    return doc_filter.first()


def evaluate_one_query(
    search_chunks: list[InferenceChunk],
    rerank_chunks: list[InferenceChunk],
    true_documents: list[Document],
    topk: int,
) -> Metrics:
    """Computes metrics for the search results, relative to the ground truth and reranked results."""
    metrics_dict: dict[str, float] = {}

    search_documents = group_by_documents(search_chunks)
    search_ranks = {docid: rank for rank, docid in enumerate(search_documents)}
    search_ranks_topk = {
        docid: rank for rank, docid in enumerate(search_documents[:topk])
    }
    true_ranks = {doc.id: rank for rank, doc in enumerate(true_documents)}

    if true_documents:
        metrics_dict["ground_truth_ratio_topk"] = _compute_ratio(
            search_ranks_topk, true_ranks
        )
        metrics_dict["ground_truth_avg_rank_delta"] = _compute_avg_rank_delta(
            search_ranks, true_ranks
        )

    if rerank_chunks:
        # build soft truth out of ground truth + reranked results, up to topk
        soft_ranks = true_ranks
        for docid in group_by_documents(rerank_chunks):
            if len(soft_ranks) >= topk:
                break
            if docid not in soft_ranks:
                soft_ranks[docid] = len(soft_ranks)

        metrics_dict["soft_truth_ratio_topk"] = _compute_ratio(
            search_ranks_topk, soft_ranks
        )
        metrics_dict["soft_truth_avg_rank_delta"] = _compute_avg_rank_delta(
            search_ranks, soft_ranks
        )

    return Metrics(**metrics_dict)


def _compute_ratio(search_ranks: dict[str, int], true_ranks: dict[str, int]) -> float:
    return len(set(search_ranks) & set(true_ranks)) / len(true_ranks)


def _compute_avg_rank_delta(
    search_ranks: dict[str, int], true_ranks: dict[str, int]
) -> float:
    out = len(search_ranks)
    return sum(
        abs(search_ranks.get(docid, out) - rank) for docid, rank in true_ranks.items()
    ) / len(true_ranks)
