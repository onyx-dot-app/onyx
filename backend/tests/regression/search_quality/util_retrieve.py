from sqlalchemy.orm import Session

from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import RerankingDetails
from onyx.context.search.postprocessing.postprocessing import semantic_reranking
from onyx.context.search.preprocessing.preprocessing import query_analysis
from onyx.context.search.retrieval.search_runner import get_query_embedding
from onyx.context.search.utils import remove_stop_words_and_punctuation
from onyx.document_index.interfaces import DocumentIndex
from onyx.utils.logger import setup_logger
from tests.regression.search_quality.util_config import SearchEvalConfig

logger = setup_logger(__name__)


def search_one_query(
    question_search: str,
    multilingual_expansion: list[str],
    document_index: DocumentIndex,
    db_session: Session,
    config: SearchEvalConfig,
) -> list[InferenceChunk]:
    """Uses the search pipeline to retrieve relevant chunks for the given query."""
    # the retrieval preprocessing is fairly stripped down so the query doesn't unexpectedly change
    query_embedding = get_query_embedding(question_search, db_session)

    all_query_terms = question_search.split()
    processed_keywords = (
        remove_stop_words_and_punctuation(all_query_terms)
        if not multilingual_expansion
        else all_query_terms
    )

    is_keyword = query_analysis(question_search)[0]
    hybrid_alpha = config.hybrid_alpha_keyword if is_keyword else config.hybrid_alpha

    access_control_list = ["PUBLIC"]
    if config.user_email:
        access_control_list.append(f"user_email:{config.user_email}")
    filters = IndexFilters(
        tags=[],
        user_file_ids=[],
        user_folder_ids=[],
        access_control_list=access_control_list,
        tenant_id=None,
    )

    results = document_index.hybrid_retrieval(
        query=question_search,
        query_embedding=query_embedding,
        final_keywords=processed_keywords,
        filters=filters,
        hybrid_alpha=hybrid_alpha,
        time_decay_multiplier=config.doc_time_decay,
        num_to_retrieve=config.num_returned_hits,
        ranking_profile_type=config.rank_profile,
        offset=config.offset,
        title_content_ratio=config.title_content_ratio,
    )

    return [result.to_inference_chunk() for result in results]


def rerank_one_query(
    question: str,
    retrieved_chunks: list[InferenceChunk],
    rerank_settings: RerankingDetails,
) -> list[InferenceChunk]:
    """Uses the reranker to rerank the retrieved chunks for the given query."""
    rerank_settings.num_rerank = len(retrieved_chunks)
    return semantic_reranking(
        query_str=question,
        rerank_settings=rerank_settings,
        chunks=retrieved_chunks,
        rerank_metrics_callback=None,
    )[0]


def group_by_documents(chunks: list[InferenceChunk]) -> list[str]:
    """Groups a sorted list of chunks into a sorted list of document ids."""
    seen_docids: set[str] = set()
    retrieved_docids: list[str] = []
    for chunk in chunks:
        if chunk.document_id not in seen_docids:
            seen_docids.add(chunk.document_id)
            retrieved_docids.append(chunk.document_id)
    return retrieved_docids
