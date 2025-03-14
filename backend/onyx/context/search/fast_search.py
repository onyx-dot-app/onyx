from collections.abc import Callable
from typing import cast
from typing import Optional

from sqlalchemy.orm import Session

from onyx.context.search.enums import QueryFlow
from onyx.context.search.enums import SearchType
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import RetrievalMetricsContainer
from onyx.context.search.models import SearchQuery
from onyx.context.search.models import SearchRequest
from onyx.context.search.retrieval.search_runner import retrieve_chunks
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.llm.interfaces import LLM
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Constant for the maximum number of search results to return in fast search
FAST_SEARCH_MAX_HITS = 300


class FastSearchPipeline:
    """A streamlined version of SearchPipeline that only retrieves chunks without section expansion or merging.

    This is optimized for quickly returning a large number of search results without the overhead
    of section expansion, reranking, and relevance evaluation.
    """

    def __init__(
        self,
        search_request: SearchRequest,
        user: User | None,
        llm: LLM,
        fast_llm: LLM,
        skip_query_analysis: bool,
        db_session: Session,
        bypass_acl: bool = False,
        retrieval_metrics_callback: Optional[
            Callable[[RetrievalMetricsContainer], None]
        ] = None,
        max_results: int = FAST_SEARCH_MAX_HITS,
    ):
        self.search_request = search_request
        self.user = user
        self.llm = llm
        self.fast_llm = fast_llm
        self.skip_query_analysis = skip_query_analysis
        self.db_session = db_session
        self.bypass_acl = bypass_acl
        self.retrieval_metrics_callback = retrieval_metrics_callback
        self.max_results = max_results

        self.search_settings = get_current_search_settings(db_session)
        self.document_index = get_default_document_index(self.search_settings, None)

        # Preprocessing steps generate this
        self._search_query: Optional[SearchQuery] = None
        self._predicted_search_type: Optional[SearchType] = None

        # Initial document index retrieval chunks
        self._retrieved_chunks: Optional[list[InferenceChunk]] = None

        # Default flow type
        self._predicted_flow: Optional[QueryFlow] = QueryFlow.QUESTION_ANSWER

    def _run_preprocessing(self) -> None:
        """Run a simplified version of preprocessing that only prepares the search query.

        This skips complex query analysis and just focuses on preparing the basic search parameters.
        """
        # Create a simplified search query with the necessary parameters
        self._search_query = SearchQuery(
            query=self.search_request.query,
            search_type=self.search_request.search_type,
            filters=self.search_request.human_selected_filters
            or IndexFilters(access_control_list=None),
            hybrid_alpha=0.5,  # Default hybrid search balance
            recency_bias_multiplier=self.search_request.recency_bias_multiplier or 1.0,
            num_hits=self.max_results,  # Use the higher limit here
            offset=self.search_request.offset or 0,
            chunks_above=0,  # Skip section expansion
            chunks_below=0,  # Skip section expansion
            precomputed_query_embedding=self.search_request.precomputed_query_embedding,
            precomputed_is_keyword=self.search_request.precomputed_is_keyword,
            processed_keywords=self.search_request.precomputed_keywords,
        )
        self._predicted_search_type = self._search_query.search_type

    @property
    def search_query(self) -> SearchQuery:
        """Get the search query, running preprocessing if necessary."""
        if self._search_query is not None:
            return self._search_query

        self._run_preprocessing()
        return cast(SearchQuery, self._search_query)

    @property
    def predicted_search_type(self) -> SearchType:
        """Get the predicted search type."""
        if self._predicted_search_type is not None:
            return self._predicted_search_type

        self._run_preprocessing()
        return cast(SearchType, self._predicted_search_type)

    @property
    def predicted_flow(self) -> QueryFlow:
        """Get the predicted query flow."""
        if self._predicted_flow is not None:
            return self._predicted_flow

        self._run_preprocessing()
        return cast(QueryFlow, self._predicted_flow)

    @property
    def retrieved_chunks(self) -> list[InferenceChunk]:
        """Get the retrieved chunks from the document index."""
        if self._retrieved_chunks is not None:
            return self._retrieved_chunks

        # Use the existing retrieve_chunks function with our search query
        self._retrieved_chunks = retrieve_chunks(
            query=self.search_query,
            document_index=self.document_index,
            db_session=self.db_session,
            retrieval_metrics_callback=self.retrieval_metrics_callback,
        )

        return self._retrieved_chunks


def run_fast_search(
    search_request: SearchRequest,
    user: User | None,
    llm: LLM,
    fast_llm: LLM,
    db_session: Session,
    max_results: int = FAST_SEARCH_MAX_HITS,
) -> list[InferenceChunk]:
    """Run a fast search that returns up to 300 results without section expansion or merging.

    Args:
        search_request: The search request containing the query and filters
        user: The current user
        llm: The main LLM instance
        fast_llm: The faster LLM instance for some operations
        db_session: The database session
        max_results: Maximum number of results to return (default: 300)

    Returns:
        A list of InferenceChunk objects representing the search results
    """
    # Create a modified search request with optimized parameters
    # Skip unnecessary processing by setting these properties
    modified_request = search_request.model_copy(
        update={
            "chunks_above": 0,  # Skip section expansion
            "chunks_below": 0,  # Skip section expansion
            "evaluation_type": None,  # Skip LLM evaluation
            "limit": max_results,  # Use higher limit
        }
    )

    # Create and run the fast search pipeline
    pipeline = FastSearchPipeline(
        search_request=modified_request,
        user=user,
        llm=llm,
        fast_llm=fast_llm,
        skip_query_analysis=True,  # Skip complex query analysis
        db_session=db_session,
        max_results=max_results,
    )

    # Just get the retrieved chunks without further processing
    return pipeline.retrieved_chunks
