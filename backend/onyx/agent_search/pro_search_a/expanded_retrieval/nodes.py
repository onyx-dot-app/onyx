from collections import defaultdict
from collections.abc import Callable
from typing import cast
from typing import Literal

import numpy as np
from langchain_core.callbacks.manager import dispatch_custom_event
from langchain_core.messages import HumanMessage
from langchain_core.messages import merge_message_runs
from langgraph.types import Command
from langgraph.types import Send

from onyx.agent_search.core_state import in_subgraph_extract_core_fields
from onyx.agent_search.pro_search_a.expanded_retrieval.models import (
    ExpandedRetrievalResult,
)
from onyx.agent_search.pro_search_a.expanded_retrieval.models import QueryResult
from onyx.agent_search.pro_search_a.expanded_retrieval.states import DocRerankingUpdate
from onyx.agent_search.pro_search_a.expanded_retrieval.states import DocRetrievalUpdate
from onyx.agent_search.pro_search_a.expanded_retrieval.states import (
    DocVerificationInput,
)
from onyx.agent_search.pro_search_a.expanded_retrieval.states import (
    DocVerificationUpdate,
)
from onyx.agent_search.pro_search_a.expanded_retrieval.states import (
    ExpandedRetrievalInput,
)
from onyx.agent_search.pro_search_a.expanded_retrieval.states import (
    ExpandedRetrievalState,
)
from onyx.agent_search.pro_search_a.expanded_retrieval.states import (
    ExpandedRetrievalUpdate,
)
from onyx.agent_search.pro_search_a.expanded_retrieval.states import InferenceSection
from onyx.agent_search.pro_search_a.expanded_retrieval.states import (
    QueryExpansionUpdate,
)
from onyx.agent_search.pro_search_a.expanded_retrieval.states import RetrievalInput
from onyx.agent_search.shared_graph_utils.calculations import get_fit_scores
from onyx.agent_search.shared_graph_utils.models import AgentChunkStats
from onyx.agent_search.shared_graph_utils.models import RetrievalFitStats
from onyx.agent_search.shared_graph_utils.prompts import REWRITE_PROMPT_MULTI_ORIGINAL
from onyx.agent_search.shared_graph_utils.prompts import VERIFIER_PROMPT
from onyx.agent_search.shared_graph_utils.utils import dispatch_separated
from onyx.agent_search.shared_graph_utils.utils import parse_question_id
from onyx.chat.models import ExtendedToolResponse
from onyx.chat.models import SubQueryPiece
from onyx.configs.dev_configs import AGENT_MAX_QUERY_RETRIEVAL_RESULTS
from onyx.configs.dev_configs import AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS
from onyx.configs.dev_configs import AGENT_RERANKING_STATS
from onyx.configs.dev_configs import AGENT_RETRIEVAL_STATS
from onyx.context.search.models import SearchRequest
from onyx.context.search.pipeline import retrieval_preprocessing
from onyx.context.search.postprocessing.postprocessing import rerank_sections
from onyx.db.engine import get_session_context_manager
from onyx.llm.interfaces import LLM
from onyx.tools.models import SearchQueryInfo
from onyx.tools.tool_implementations.search.search_tool import (
    SEARCH_RESPONSE_SUMMARY_ID,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary
from onyx.tools.tool_implementations.search.search_tool import yield_search_responses
from onyx.utils.logger import setup_logger

logger = setup_logger()


def dispatch_subquery(level: int, question_nr: int) -> Callable[[str, int], None]:
    def helper(token: str, num: int) -> None:
        dispatch_custom_event(
            "subqueries",
            SubQueryPiece(
                sub_query=token,
                level=level,
                level_question_nr=question_nr,
                query_id=num,
            ),
        )

    return helper


def expand_queries(state: ExpandedRetrievalInput) -> QueryExpansionUpdate:
    # Sometimes we want to expand the original question, sometimes we want to expand a sub-question.
    # When we are running this node on the original question, no question is explictly passed in.
    # Instead, we use the original question from the search request.
    question = state.get("question", state["subgraph_config"].search_request.query)
    llm: LLM = state["subgraph_fast_llm"]
    state["subgraph_db_session"]
    chat_session_id = state["subgraph_config"].chat_session_id
    sub_question_id = state.get("sub_question_id")
    if sub_question_id is None:
        level, question_nr = 0, 0
    else:
        level, question_nr = parse_question_id(sub_question_id)

    if chat_session_id is None:
        raise ValueError("chat_session_id must be provided for agent search")

    msg = [
        HumanMessage(
            content=REWRITE_PROMPT_MULTI_ORIGINAL.format(question=question),
        )
    ]

    llm_response_list = dispatch_separated(
        llm.stream(prompt=msg), dispatch_subquery(level, question_nr)
    )

    llm_response = merge_message_runs(llm_response_list, chunk_separator="")[0].content

    rewritten_queries = llm_response.split("\n")

    return QueryExpansionUpdate(
        expanded_queries=rewritten_queries,
    )


def doc_retrieval(state: RetrievalInput) -> DocRetrievalUpdate:
    """
    Retrieve documents

    Args:
        state (RetrievalInput): Primary state + the query to retrieve

    Updates:
        expanded_retrieval_results: list[ExpandedRetrievalResult]
        retrieved_documents: list[InferenceSection]
    """
    query_to_retrieve = state["query_to_retrieve"]
    search_tool = state["subgraph_search_tool"]

    retrieved_docs: list[InferenceSection] = []
    if not query_to_retrieve.strip():
        logger.warning("Empty query, skipping retrieval")
        return DocRetrievalUpdate(
            expanded_retrieval_results=[],
            retrieved_documents=[],
        )

    query_info = None
    # new db session to avoid concurrency issues
    with get_session_context_manager() as db_session:
        for tool_response in search_tool.run(
            query=query_to_retrieve,
            force_no_rerank=True,
            alternate_db_session=db_session,
        ):
            # get retrieved docs to send to the rest of the graph
            if tool_response.id == SEARCH_RESPONSE_SUMMARY_ID:
                response = cast(SearchResponseSummary, tool_response.response)
                retrieved_docs = response.top_sections
                query_info = SearchQueryInfo(
                    predicted_search=response.predicted_search,
                    final_filters=response.final_filters,
                    recency_bias_multiplier=response.recency_bias_multiplier,
                )

    retrieved_docs = retrieved_docs[:AGENT_MAX_QUERY_RETRIEVAL_RESULTS]
    pre_rerank_docs = retrieved_docs
    if search_tool.search_pipeline is not None:
        pre_rerank_docs = (
            search_tool.search_pipeline._retrieved_sections or retrieved_docs
        )

    if AGENT_RETRIEVAL_STATS:
        fit_scores = get_fit_scores(
            pre_rerank_docs,
            retrieved_docs,
        )
    else:
        fit_scores = None

    expanded_retrieval_result = QueryResult(
        query=query_to_retrieve,
        search_results=retrieved_docs,
        stats=fit_scores,
        query_info=query_info,
    )
    return DocRetrievalUpdate(
        expanded_retrieval_results=[expanded_retrieval_result],
        retrieved_documents=retrieved_docs,
    )


def verification_kickoff(
    state: ExpandedRetrievalState,
) -> Command[Literal["doc_verification"]]:
    documents = state["retrieved_documents"]
    verification_question = state.get(
        "question", state["subgraph_config"].search_request.query
    )
    sub_question_id = state.get("sub_question_id")
    return Command(
        update={},
        goto=[
            Send(
                node="doc_verification",
                arg=DocVerificationInput(
                    doc_to_verify=doc,
                    question=verification_question,
                    base_search=False,
                    sub_question_id=sub_question_id,
                    **in_subgraph_extract_core_fields(state),
                ),
            )
            for doc in documents
        ],
    )


def doc_verification(state: DocVerificationInput) -> DocVerificationUpdate:
    """
    Check whether the document is relevant for the original user question

    Args:
        state (DocVerificationInput): The current state

    Updates:
        verified_documents: list[InferenceSection]
    """

    question = state["question"]
    doc_to_verify = state["doc_to_verify"]
    document_content = doc_to_verify.combined_content

    msg = [
        HumanMessage(
            content=VERIFIER_PROMPT.format(
                question=question, document_content=document_content
            )
        )
    ]

    fast_llm = state["subgraph_fast_llm"]

    response = fast_llm.invoke(msg)

    verified_documents = []
    if isinstance(response.content, str) and "yes" in response.content.lower():
        verified_documents.append(doc_to_verify)

    return DocVerificationUpdate(
        verified_documents=verified_documents,
    )


def doc_reranking(state: ExpandedRetrievalState) -> DocRerankingUpdate:
    verified_documents = state["verified_documents"]

    # Rerank post retrieval and verification. First, create a search query
    # then create the list of reranked sections

    question = state.get("question", state["subgraph_config"].search_request.query)
    with get_session_context_manager() as db_session:
        _search_query = retrieval_preprocessing(
            search_request=SearchRequest(query=question),
            user=state["subgraph_search_tool"].user,  # bit of a hack
            llm=state["subgraph_fast_llm"],
            db_session=db_session,
        )

    # skip section filtering

    if (
        _search_query.rerank_settings
        and _search_query.rerank_settings.rerank_model_name
        and _search_query.rerank_settings.num_rerank > 0
    ):
        reranked_documents = rerank_sections(
            _search_query,
            verified_documents,
        )
    else:
        logger.warning("No reranking settings found, using unranked documents")
        reranked_documents = verified_documents

    if AGENT_RERANKING_STATS:
        fit_scores = get_fit_scores(verified_documents, reranked_documents)
    else:
        fit_scores = RetrievalFitStats(fit_score_lift=0, rerank_effect=0, fit_scores={})

    # TODO: stream deduped docs here, or decide to use search tool ranking/verification

    return DocRerankingUpdate(
        reranked_documents=[
            doc for doc in reranked_documents if type(doc) == InferenceSection
        ][:AGENT_RERANKING_MAX_QUERY_RETRIEVAL_RESULTS],
        sub_question_retrieval_stats=fit_scores,
    )


def _calculate_sub_question_retrieval_stats(
    verified_documents: list[InferenceSection],
    expanded_retrieval_results: list[QueryResult],
) -> AgentChunkStats:
    chunk_scores: dict[str, dict[str, list[int | float]]] = defaultdict(
        lambda: defaultdict(list)
    )

    for expanded_retrieval_result in expanded_retrieval_results:
        for doc in expanded_retrieval_result.search_results:
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
        if doc_chunk_id in verified_doc_chunk_ids:
            raw_chunk_stats_counts["verified_count"] += 1

            valid_chunk_scores = [
                score for score in chunk_data["score"] if score is not None
            ]
            raw_chunk_stats_scores["verified_scores"] += float(
                np.mean(valid_chunk_scores)
            )
        else:
            raw_chunk_stats_counts["rejected_count"] += 1
            valid_chunk_scores = [
                score for score in chunk_data["score"] if score is not None
            ]
            raw_chunk_stats_scores["rejected_scores"] += float(
                np.mean(valid_chunk_scores)
            )
            dismissed_doc_chunk_ids.append(doc_chunk_id)

    if raw_chunk_stats_counts["verified_count"] == 0:
        verified_avg_scores = 0.0
    else:
        verified_avg_scores = raw_chunk_stats_scores["verified_scores"] / float(
            raw_chunk_stats_counts["verified_count"]
        )

    rejected_scores = raw_chunk_stats_scores.get("rejected_scores", None)
    if rejected_scores is not None:
        rejected_avg_scores = rejected_scores / float(
            raw_chunk_stats_counts["rejected_count"]
        )
    else:
        rejected_avg_scores = None

    chunk_stats = AgentChunkStats(
        verified_count=raw_chunk_stats_counts["verified_count"],
        verified_avg_scores=verified_avg_scores,
        rejected_count=raw_chunk_stats_counts["rejected_count"],
        rejected_avg_scores=rejected_avg_scores,
        verified_doc_chunk_ids=verified_doc_chunk_ids,
        dismissed_doc_chunk_ids=dismissed_doc_chunk_ids,
    )

    return chunk_stats


def format_results(state: ExpandedRetrievalState) -> ExpandedRetrievalUpdate:
    level, question_nr = parse_question_id(state.get("sub_question_id") or "0_0")
    query_infos = [
        result.query_info
        for result in state["expanded_retrieval_results"]
        if result.query_info is not None
    ]
    if len(query_infos) == 0:
        raise ValueError("No query info found")

    # main question docs will be sent later after aggregation and deduping with sub-question docs
    if not (level == 0 and question_nr == 0):
        for tool_response in yield_search_responses(
            query=state["question"],
            reranked_sections=state[
                "retrieved_documents"
            ],  # TODO: rename params. this one is supposed to be the sections pre-merging
            final_context_sections=state["reranked_documents"],
            search_query_info=query_infos[0],  # TODO: handle differing query infos?
            get_section_relevance=lambda: None,  # TODO: add relevance
            search_tool=state["subgraph_search_tool"],
        ):
            dispatch_custom_event(
                "tool_response",
                ExtendedToolResponse(
                    id=tool_response.id,
                    response=tool_response.response,
                    level=level,
                    level_question_nr=question_nr,
                ),
            )
    sub_question_retrieval_stats = _calculate_sub_question_retrieval_stats(
        verified_documents=state["verified_documents"],
        expanded_retrieval_results=state["expanded_retrieval_results"],
    )

    if sub_question_retrieval_stats is None:
        sub_question_retrieval_stats = AgentChunkStats()
    # else:
    #    sub_question_retrieval_stats = [sub_question_retrieval_stats]

    return ExpandedRetrievalUpdate(
        expanded_retrieval_result=ExpandedRetrievalResult(
            expanded_queries_results=state["expanded_retrieval_results"],
            all_documents=state["reranked_documents"],
            sub_question_retrieval_stats=sub_question_retrieval_stats,
        ),
    )
