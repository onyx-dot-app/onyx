from collections import defaultdict
from collections.abc import Callable

import numpy as np
from langgraph.types import StreamWriter

from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkRetrievalStats
from onyx.agents.agent_search.shared_graph_utils.models import QueryRetrievalResult
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import SubQueryPiece
from onyx.context.search.models import InferenceSection
from onyx.utils.logger import setup_logger

logger = setup_logger()


def dispatch_subquery(
    level: int, question_num: int, writer: StreamWriter
) -> Callable[[str, int], None]:
    def helper(token: str, num: int) -> None:
        write_custom_event(
            "subqueries",
            SubQueryPiece(
                sub_query=token,
                level=level,
                level_question_num=question_num,
                query_id=num,
            ),
            writer,
        )

    return helper


def calculate_sub_question_retrieval_stats(
    verified_documents: list[InferenceSection],
    expanded_retrieval_results: list[QueryRetrievalResult],
) -> AgentChunkRetrievalStats:
    chunk_scores: dict[str, dict[str, list[int | float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for expanded_retrieval_result in expanded_retrieval_results:
        for doc in expanded_retrieval_result.retrieved_documents:
            doc_chunk_id = f"{doc.center_chunk.document_id}_{doc.center_chunk.chunk_id}"
            if doc.center_chunk.score is not None:
                chunk_scores[doc_chunk_id]["score"].append(doc.center_chunk.score)

    verified_doc_chunk_ids = [
        f"{verified_document.center_chunk.document_id}_{verified_document.center_chunk.chunk_id}"
        for verified_document in verified_documents
    ]
    dismissed_doc_chunk_ids = []

    raw_chunk_stats_counts: dict[str, int] = defaultdict(int)
    raw_chunk_stats_scores: dict[str, float] = defaultdict(float)
    for doc_chunk_id, chunk_data in chunk_scores.items():
        valid_chunk_scores = [
            score for score in chunk_data["score"] if score is not None
        ]
        key = "verified" if doc_chunk_id in verified_doc_chunk_ids else "rejected"
        raw_chunk_stats_counts[f"{key}_count"] += 1

        raw_chunk_stats_scores[f"{key}_scores"] += float(np.mean(valid_chunk_scores))

        if key == "rejected":
            dismissed_doc_chunk_ids.append(doc_chunk_id)

    if raw_chunk_stats_counts["verified_count"] == 0:
        verified_avg_scores = 0.0
    else:
        verified_avg_scores = raw_chunk_stats_scores["verified_scores"] / float(
            raw_chunk_stats_counts["verified_count"]
        )

    rejected_scores = raw_chunk_stats_scores.get("rejected_scores")
    if rejected_scores is not None:
        rejected_avg_scores = rejected_scores / float(
            raw_chunk_stats_counts["rejected_count"]
        )
    else:
        rejected_avg_scores = None

    chunk_stats = AgentChunkRetrievalStats(
        verified_count=raw_chunk_stats_counts["verified_count"],
        verified_avg_scores=verified_avg_scores,
        rejected_count=raw_chunk_stats_counts["rejected_count"],
        rejected_avg_scores=rejected_avg_scores,
        verified_doc_chunk_ids=verified_doc_chunk_ids,
        dismissed_doc_chunk_ids=dismissed_doc_chunk_ids,
    )

    return chunk_stats
