from collections.abc import Callable

from langgraph.types import StreamWriter

from onyx.agents.agent_search.shared_graph_utils.models import AgentChunkRetrievalStats
from onyx.agents.agent_search.shared_graph_utils.models import InitialAgentResultStats
from onyx.agents.agent_search.shared_graph_utils.models import QueryRetrievalResult
from onyx.agents.agent_search.shared_graph_utils.models import (
    SubQuestionAnswerResults,
)
from onyx.agents.agent_search.shared_graph_utils.utils import write_custom_event
from onyx.chat.models import StreamStopInfo
from onyx.chat.models import StreamStopReason
from onyx.chat.models import StreamType
from onyx.chat.models import SubQuestionPiece
from onyx.tools.models import SearchQueryInfo
from onyx.utils.logger import setup_logger

logger = setup_logger()


def dispatch_subquestion(
    level: int, writer: StreamWriter
) -> Callable[[str, int], None]:
    def _helper(sub_question_part: str, sep_num: int) -> None:
        write_custom_event(
            "decomp_qs",
            SubQuestionPiece(
                sub_question=sub_question_part,
                level=level,
                level_question_num=sep_num,
            ),
            writer,
        )

    return _helper


def dispatch_subquestion_sep(level: int, writer: StreamWriter) -> Callable[[int], None]:
    def _helper(sep_num: int) -> None:
        write_custom_event(
            "stream_finished",
            StreamStopInfo(
                stop_reason=StreamStopReason.FINISHED,
                stream_type=StreamType.SUB_QUESTIONS,
                level=level,
                level_question_num=sep_num,
            ),
            writer,
        )

    return _helper


def calculate_initial_agent_stats(
    decomp_answer_results: list[SubQuestionAnswerResults],
    original_question_stats: AgentChunkRetrievalStats,
) -> InitialAgentResultStats:
    initial_agent_result_stats: InitialAgentResultStats = InitialAgentResultStats(
        sub_questions={},
        original_question={},
        agent_effectiveness={},
    )

    orig_verified = original_question_stats.verified_count
    orig_support_score = original_question_stats.verified_avg_scores

    verified_document_chunk_ids = []
    support_scores = 0.0

    for decomp_answer_result in decomp_answer_results:
        verified_document_chunk_ids += (
            decomp_answer_result.sub_question_retrieval_stats.verified_doc_chunk_ids
        )
        if (
            decomp_answer_result.sub_question_retrieval_stats.verified_avg_scores
            is not None
        ):
            support_scores += (
                decomp_answer_result.sub_question_retrieval_stats.verified_avg_scores
            )

    verified_document_chunk_ids = list(set(verified_document_chunk_ids))

    # Calculate sub-question stats
    if (
        verified_document_chunk_ids
        and len(verified_document_chunk_ids) > 0
        and support_scores is not None
    ):
        sub_question_stats: dict[str, float | int | None] = {
            "num_verified_documents": len(verified_document_chunk_ids),
            "verified_avg_score": float(support_scores / len(decomp_answer_results)),
        }
    else:
        sub_question_stats = {"num_verified_documents": 0, "verified_avg_score": None}

    initial_agent_result_stats.sub_questions.update(sub_question_stats)

    # Get original question stats
    initial_agent_result_stats.original_question.update(
        {
            "num_verified_documents": original_question_stats.verified_count,
            "verified_avg_score": original_question_stats.verified_avg_scores,
        }
    )

    # Calculate chunk utilization ratio
    sub_verified = initial_agent_result_stats.sub_questions["num_verified_documents"]

    chunk_ratio: float | None = None
    if sub_verified is not None and orig_verified is not None and orig_verified > 0:
        chunk_ratio = (float(sub_verified) / orig_verified) if sub_verified > 0 else 0.0
    elif sub_verified is not None and sub_verified > 0:
        chunk_ratio = 10.0

    initial_agent_result_stats.agent_effectiveness["utilized_chunk_ratio"] = chunk_ratio

    if (
        orig_support_score is None
        or orig_support_score == 0.0
        and initial_agent_result_stats.sub_questions["verified_avg_score"] is None
    ):
        initial_agent_result_stats.agent_effectiveness["support_ratio"] = None
    elif orig_support_score is None or orig_support_score == 0.0:
        initial_agent_result_stats.agent_effectiveness["support_ratio"] = 10
    elif initial_agent_result_stats.sub_questions["verified_avg_score"] is None:
        initial_agent_result_stats.agent_effectiveness["support_ratio"] = 0
    else:
        initial_agent_result_stats.agent_effectiveness["support_ratio"] = (
            initial_agent_result_stats.sub_questions["verified_avg_score"]
            / orig_support_score
        )

    return initial_agent_result_stats


def get_query_info(results: list[QueryRetrievalResult]) -> SearchQueryInfo:
    # Use the query info from the base document retrieval
    # this is used for some fields that are the same across the searches done
    query_info = None
    for result in results:
        if result.query_info is not None:
            query_info = result.query_info
            break

    assert query_info is not None, "must have query info"
    return query_info
