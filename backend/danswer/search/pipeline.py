from collections.abc import Callable
from collections.abc import Generator
from typing import cast

from sqlalchemy.orm import Session

from danswer.configs.chat_configs import MULTILINGUAL_QUERY_EXPANSION
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.models import User
from danswer.document_index.factory import get_default_document_index
from danswer.indexing.models import InferenceChunk
from danswer.search.enums import QueryFlow
from danswer.search.enums import SearchType
from danswer.search.models import RerankMetricsContainer
from danswer.search.models import RetrievalMetricsContainer
from danswer.search.models import SearchQuery
from danswer.search.models import SearchRequest
from danswer.search.postprocessing.postprocessing import search_postprocessing
from danswer.search.preprocessing.preprocessing import retrieval_preprocessing
from danswer.search.retrieval.search_runner import retrieve_chunks


class SearchPipeline:
    def __init__(
        self,
        search_request: SearchRequest,
        user: User | None,
        db_session: Session,
        bypass_acl: bool = False,  # NOTE: VERY DANGEROUS, USE WITH CAUTION
        retrieval_metrics_callback: Callable[[RetrievalMetricsContainer], None]
        | None = None,
        rerank_metrics_callback: Callable[[RerankMetricsContainer], None] | None = None,
    ):
        self.search_request = search_request
        self.user = user
        self.db_session = db_session
        self.bypass_acl = bypass_acl
        self.retrieval_metrics_callback = retrieval_metrics_callback
        self.rerank_metrics_callback = rerank_metrics_callback

        self.embedding_model = get_current_db_embedding_model(db_session)
        self.document_index = get_default_document_index(
            primary_index_name=self.embedding_model.index_name,
            secondary_index_name=None,
        )

        self._search_query: SearchQuery | None = None
        self._predicted_search_type: SearchType | None = None
        self._predicted_flow: QueryFlow | None = None

        self._retrieved_docs: list[InferenceChunk] | None = None
        self._reranked_docs: list[InferenceChunk] | None = None
        self._relevant_chunk_indicies: list[int] | None = None

        # generator state
        self._postprocessing_generator: Generator[
            list[InferenceChunk] | list[str], None, None
        ] | None = None

    """Pre-processing"""

    def _run_preprocessing(self) -> None:
        (
            final_search_query,
            predicted_search_type,
            predicted_flow,
        ) = retrieval_preprocessing(
            search_request=self.search_request,
            user=self.user,
            db_session=self.db_session,
            bypass_acl=self.bypass_acl,
        )
        self._predicted_search_type = predicted_search_type
        self._predicted_flow = predicted_flow
        self._search_query = final_search_query

    @property
    def search_query(self) -> SearchQuery:
        if self._search_query is not None:
            return self._search_query

        self._run_preprocessing()
        return cast(SearchQuery, self._search_query)

    @property
    def predicted_search_type(self) -> SearchType:
        if self._predicted_search_type is not None:
            return self._predicted_search_type

        self._run_preprocessing()
        return cast(SearchType, self._predicted_search_type)

    @property
    def predicted_flow(self) -> QueryFlow:
        if self._predicted_flow is not None:
            return self._predicted_flow

        self._run_preprocessing()
        return cast(QueryFlow, self._predicted_flow)

    """Retrieval"""

    @property
    def retrieved_docs(self) -> list[InferenceChunk]:
        if self._retrieved_docs is not None:
            return self._retrieved_docs

        self._retrieved_docs = retrieve_chunks(
            query=self.search_query,
            document_index=self.document_index,
            db_session=self.db_session,
            hybrid_alpha=self.search_request.hybrid_alpha,
            multilingual_expansion_str=MULTILINGUAL_QUERY_EXPANSION,
            retrieval_metrics_callback=self.retrieval_metrics_callback,
        )

        # self._retrieved_docs = chunks_to_search_docs(retrieved_chunks)
        return cast(list[InferenceChunk], self._retrieved_docs)

    """Post-Processing"""

    @property
    def reranked_docs(self) -> list[InferenceChunk]:
        if self._reranked_docs is not None:
            return self._reranked_docs

        self._postprocessing_generator = search_postprocessing(
            search_query=self.search_query,
            retrieved_chunks=self.retrieved_docs,
            rerank_metrics_callback=self.rerank_metrics_callback,
        )
        self._reranked_docs = cast(
            list[InferenceChunk], next(self._postprocessing_generator)
        )
        return self._reranked_docs

    @property
    def relevant_chunk_indicies(self) -> list[int]:
        if self._relevant_chunk_indicies is not None:
            return self._relevant_chunk_indicies

        # run first step of postprocessing generator if not already done
        reranked_docs = self.reranked_docs

        relevant_chunk_ids = next(
            cast(Generator[list[str], None, None], self._postprocessing_generator)
        )
        self._relevant_chunk_indicies = [
            ind
            for ind, chunk in enumerate(reranked_docs)
            if chunk.unique_id in relevant_chunk_ids
        ]
        return self._relevant_chunk_indicies

    @property
    def chunk_relevance_list(self) -> list[bool]:
        return [
            True if ind in self.relevant_chunk_indicies else False
            for ind in range(len(self.reranked_docs))
        ]
