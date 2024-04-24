from collections import defaultdict
from collections.abc import Callable
from collections.abc import Generator
from typing import cast

from pydantic import BaseModel
from sqlalchemy.orm import Session

from danswer.configs.chat_configs import MULTILINGUAL_QUERY_EXPANSION
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.models import User
from danswer.document_index.factory import get_default_document_index
from danswer.search.enums import QueryFlow
from danswer.search.enums import SearchType
from danswer.search.models import IndexFilters
from danswer.search.models import InferenceChunk
from danswer.search.models import InferenceSection
from danswer.search.models import RerankMetricsContainer
from danswer.search.models import RetrievalMetricsContainer
from danswer.search.models import SearchQuery
from danswer.search.models import SearchRequest
from danswer.search.postprocessing.postprocessing import search_postprocessing
from danswer.search.preprocessing.preprocessing import retrieval_preprocessing
from danswer.search.retrieval.search_runner import retrieve_chunks
from danswer.utils.threadpool_concurrency import run_functions_tuples_in_parallel


class ChunkRange(BaseModel):
    chunk: InferenceChunk
    start: int
    end: int
    combined_content: str | None = None


def merge_chunk_intervals(chunk_ranges: list[ChunkRange]) -> list[ChunkRange]:
    """This acts on a single document to merge the overlapping ranges of sections
    Algo explained here for easy understanding: https://leetcode.com/problems/merge-intervals
    """
    sorted_ranges = sorted(chunk_ranges, key=lambda x: x.start)

    ans: list[ChunkRange] = []

    for chunk_range in sorted_ranges:
        if not ans or ans[-1].end < chunk_range.start:
            ans.append(chunk_range)
        else:
            ans[-1].end = max(ans[-1].end, chunk_range.end)

    return ans


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

        self._retrieved_chunks: list[InferenceChunk] | None = None
        self._retrieved_sections: list[InferenceSection] | None = None
        self._reranked_chunks: list[InferenceChunk] | None = None
        self._reranked_sections: list[InferenceSection] | None = None
        self._relevant_chunk_indices: list[int] | None = None

        # If chunks have been merged, the LLM filter flow no longer applies
        # as the indices no longer match. Can be implemented later as needed
        self.ran_merge_chunk = False

        # generator state
        self._postprocessing_generator: Generator[
            list[InferenceChunk] | list[str], None, None
        ] | None = None

    def _combine_chunks(self, post_rerank: bool) -> list[InferenceSection]:
        if not post_rerank and self._retrieved_sections:
            return self._retrieved_sections
        if post_rerank and self._reranked_sections:
            return self._reranked_sections

        if not post_rerank:
            chunks = self.retrieved_chunks
        else:
            chunks = self.reranked_chunks

        if self._search_query is None:
            # Should never happen
            raise RuntimeError("Failed in Query Preprocessing")

        functions_with_args: list[tuple[Callable, tuple]] = []
        final_inference_sections = []

        # Nothing to combine, just return the chunks
        if (
            not self._search_query.chunks_above
            and not self._search_query.chunks_below
            and not self._search_query.full_doc
        ):
            return [InferenceSection.from_chunk(chunk) for chunk in chunks]

        # If chunk merges have been run, LLM reranking loses meaning
        # Needs reimplementation, out of scope for now
        self.ran_merge_chunk = True

        # Full doc setting takes priority
        if self._search_query.full_doc:
            seen_document_ids = set()
            unique_chunks = []
            for chunk in chunks:
                if chunk.document_id not in seen_document_ids:
                    seen_document_ids.add(chunk.document_id)
                    unique_chunks.append(chunk)

                    functions_with_args.append(
                        (
                            self.document_index.id_based_retrieval,
                            (
                                chunk.document_id,
                                None,  # Start chunk ind
                                None,  # End chunk ind
                                # There is no chunk level permissioning, this expansion around chunks
                                # can be assumed to be safe
                                IndexFilters(access_control_list=None),
                            ),
                        )
                    )

            list_inference_chunks = run_functions_tuples_in_parallel(
                functions_with_args, allow_failures=False
            )

            for ind, chunk in enumerate(unique_chunks):
                inf_chunks = list_inference_chunks[ind]
                combined_content = "\n".join([chunk.content for chunk in inf_chunks])
                final_inference_sections.append(
                    InferenceSection.from_chunk(chunk, content=combined_content)
                )

            return final_inference_sections

        # General flow:
        # - Combine chunks into lists by document_id
        # - For each document, run merge-intervals to get combined ranges
        # - Fetch all of the new chunks with contents for the combined ranges
        # - Map it back to the combined ranges (which each know their "center" chunk)
        # - Reiterate the chunks again and map to the results above based on the chunk.
        #   This maintains the original chunks ordering. Note, we cannot simply sort by score here
        #   as reranking flow may wipe the scores for a lot of the chunks.
        doc_chunk_ranges_map = defaultdict(list)
        for chunk in chunks:
            doc_chunk_ranges_map[chunk.document_id].append(
                ChunkRange(
                    chunk=chunk,
                    start=max(0, chunk.chunk_id - self._search_query.chunks_above),
                    # No max known ahead of time, filter will handle this anyway
                    end=chunk.chunk_id + self._search_query.chunks_below,
                )
            )

        merged_ranges = [
            merge_chunk_intervals(ranges) for ranges in doc_chunk_ranges_map.values()
        ]
        reverse_map = {r.chunk: r for doc_ranges in merged_ranges for r in doc_ranges}

        for chunk_range in reverse_map.values():
            functions_with_args.append(
                (
                    self.document_index.id_based_retrieval,
                    (
                        chunk_range.chunk.document_id,
                        chunk_range.start,
                        chunk_range.end,
                        # There is no chunk level permissioning, this expansion around chunks
                        # can be assumed to be safe
                        IndexFilters(access_control_list=None),
                    ),
                )
            )

        # list of list of inference chunks where the inner list needs to be combined for content
        list_inference_chunks = run_functions_tuples_in_parallel(
            functions_with_args, allow_failures=False
        )

        for ind, chunk_range in enumerate(reverse_map.values()):
            inf_chunks = list_inference_chunks[ind]
            combined_content = "\n".join([chunk.content for chunk in inf_chunks])
            chunk_range.combined_content = combined_content

        for chunk in chunks:
            if chunk not in reverse_map:
                continue
            chunk_range = reverse_map[chunk]
            final_inference_sections.append(
                InferenceSection.from_chunk(
                    chunk_range.chunk, content=chunk_range.combined_content
                )
            )

        return final_inference_sections

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
    def retrieved_chunks(self) -> list[InferenceChunk]:
        if self._retrieved_chunks is not None:
            return self._retrieved_chunks

        self._retrieved_chunks = retrieve_chunks(
            query=self.search_query,
            document_index=self.document_index,
            db_session=self.db_session,
            hybrid_alpha=self.search_request.hybrid_alpha,
            multilingual_expansion_str=MULTILINGUAL_QUERY_EXPANSION,
            retrieval_metrics_callback=self.retrieval_metrics_callback,
        )

        return cast(list[InferenceChunk], self._retrieved_chunks)

    @property
    def retrieved_sections(self) -> list[InferenceSection]:
        # Calls retrieved_chunks inside
        self._retrieved_sections = self._combine_chunks(post_rerank=False)
        return self._retrieved_sections

    """Post-Processing"""

    @property
    def reranked_chunks(self) -> list[InferenceChunk]:
        if self._reranked_chunks is not None:
            return self._reranked_chunks

        self._postprocessing_generator = search_postprocessing(
            search_query=self.search_query,
            retrieved_chunks=self.retrieved_chunks,
            rerank_metrics_callback=self.rerank_metrics_callback,
        )
        self._reranked_chunks = cast(
            list[InferenceChunk], next(self._postprocessing_generator)
        )
        return self._reranked_chunks

    @property
    def reranked_sections(self) -> list[InferenceSection]:
        # Calls reranked_chunks inside
        self._reranked_sections = self._combine_chunks(post_rerank=True)
        return self._reranked_sections

    @property
    def relevant_chunk_indices(self) -> list[int]:
        # If chunks have been merged, then we cannot simply rely on the leading chunk
        # relevance, there is no way to get the full relevance of the Section now
        # without running a more token heavy pass. This can be an option but not
        # implementing now.
        if self.ran_merge_chunk:
            return []

        if self._relevant_chunk_indices is not None:
            return self._relevant_chunk_indices

        # run first step of postprocessing generator if not already done
        reranked_docs = self.reranked_chunks

        relevant_chunk_ids = next(
            cast(Generator[list[str], None, None], self._postprocessing_generator)
        )
        self._relevant_chunk_indices = [
            ind
            for ind, chunk in enumerate(reranked_docs)
            if chunk.unique_id in relevant_chunk_ids
        ]
        return self._relevant_chunk_indices

    @property
    def chunk_relevance_list(self) -> list[bool]:
        return [
            True if ind in self.relevant_chunk_indices else False
            for ind in range(len(self.reranked_chunks))
        ]

    @property
    def section_relevance_list(self) -> list[bool]:
        if self.ran_merge_chunk:
            return [False] * len(self.reranked_sections)

        return [
            True if ind in self.relevant_chunk_indices else False
            for ind in range(len(self.reranked_chunks))
        ]
