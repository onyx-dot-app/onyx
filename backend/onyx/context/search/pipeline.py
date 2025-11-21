from collections import defaultdict
from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.chat.models import ContextualPruningConfig
from onyx.chat.models import PromptConfig
from onyx.chat.models import SectionRelevancePiece
from onyx.chat.prune_and_merge import _merge_sections
from onyx.chat.prune_and_merge import ChunkRange
from onyx.chat.prune_and_merge import merge_chunk_intervals
from onyx.chat.prune_and_merge import prune_and_merge_sections
from onyx.configs.chat_configs import DISABLE_LLM_DOC_RELEVANCE
from onyx.context.search.enums import LLMEvaluationType
from onyx.context.search.enums import QueryFlow
from onyx.context.search.enums import SearchType
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import ChunkIndexRequest
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import InferenceSection
from onyx.context.search.models import RerankMetricsContainer
from onyx.context.search.models import RetrievalMetricsContainer
from onyx.context.search.models import SearchQuery
from onyx.context.search.models import SearchRequest
from onyx.context.search.postprocessing.postprocessing import search_postprocessing
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.preprocessing.preprocessing import retrieval_preprocessing
from onyx.context.search.retrieval.search_runner import retrieve_chunks
from onyx.context.search.retrieval.search_runner import search_chunks
from onyx.context.search.utils import inference_section_from_chunks
from onyx.context.search.utils import relevant_sections_to_indices
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import DocumentIndex
from onyx.document_index.interfaces import VespaChunkRequest
from onyx.llm.interfaces import LLM
from onyx.onyxbot.slack.models import SlackContext
from onyx.secondary_llm_flows.agentic_evaluation import evaluate_inference_section
from onyx.secondary_llm_flows.source_filter import extract_source_filter
from onyx.secondary_llm_flows.time_filter import extract_time_filter
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import FunctionCall
from onyx.utils.threadpool_concurrency import run_functions_in_parallel
from onyx.utils.timing import log_function_time
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from shared_configs.configs import MULTI_TENANT
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()


@log_function_time(print_only=True)
def _build_index_filters(
    user_provided_filters: BaseFilters | None,
    user: User | None,  # Used for ACLs
    project_id: int | None,
    user_file_ids: list[UUID] | None,
    persona_document_sets: list[str] | None,
    persona_time_cutoff: datetime | None,
    db_session: Session,
    auto_detect_filters: bool = False,
    query: str | None = None,
    llm: LLM | None = None,
    bypass_acl: bool = False,
) -> IndexFilters:
    if auto_detect_filters and (llm is None or query is None):
        raise RuntimeError("LLM and query are required for auto detect filters")

    base_filters = user_provided_filters or BaseFilters()

    if (
        user_provided_filters
        and user_provided_filters.document_set is None
        and persona_document_sets is not None
    ):
        base_filters.document_set = persona_document_sets

    time_filter = base_filters.time_cutoff or persona_time_cutoff
    source_filter = base_filters.source_type

    detected_time_filter = None
    detected_source_filter = None
    if auto_detect_filters:
        time_filter_fnc = FunctionCall(extract_time_filter, (query, llm), {})
        if not source_filter:
            source_filter_fnc = FunctionCall(
                extract_source_filter, (query, llm, db_session), {}
            )
        else:
            source_filter_fnc = None

        functions_to_run = [fn for fn in [time_filter_fnc, source_filter_fnc] if fn]
        parallel_results = run_functions_in_parallel(functions_to_run)
        # Detected favor recent is not used for now
        detected_time_filter, _detected_favor_recent = parallel_results[
            time_filter_fnc.result_id
        ]
        if source_filter_fnc:
            detected_source_filter = parallel_results[source_filter_fnc.result_id]

    # If the detected time filter is more recent, use that one
    if time_filter and detected_time_filter and detected_time_filter > time_filter:
        time_filter = detected_time_filter

    # If the user has explicitly set a source filter, use that one
    if not source_filter and detected_source_filter:
        source_filter = detected_source_filter

    user_acl_filters = (
        None if bypass_acl else build_access_filters_for_user(user, db_session)
    )

    final_filters = IndexFilters(
        user_file_ids=user_file_ids,
        project_id=project_id,
        source_type=source_filter,
        document_set=persona_document_sets,
        time_cutoff=time_filter,
        tags=base_filters.tags,
        access_control_list=user_acl_filters,
        tenant_id=get_current_tenant_id() if MULTI_TENANT else None,
    )
    return final_filters


def merge_individual_chunks(
    chunks: list[InferenceChunk],
) -> list[InferenceSection]:
    """Merge adjacent chunks from the same document into sections.

    Chunks are considered adjacent if their chunk_ids differ by 1 and they
    are from the same document. The section maintains the position of the
    first chunk in the original list.
    """
    if not chunks:
        return []

    # Create a mapping from (document_id, chunk_id) to original index
    # This helps us find the chunk that appears first in the original list
    chunk_to_original_index: dict[tuple[str, int], int] = {}
    for idx, chunk in enumerate(chunks):
        chunk_to_original_index[(chunk.document_id, chunk.chunk_id)] = idx

    # Group chunks by document_id
    doc_chunks: dict[str, list[InferenceChunk]] = defaultdict(list)
    for chunk in chunks:
        doc_chunks[chunk.document_id].append(chunk)

    # For each document, sort chunks by chunk_id to identify adjacent chunks
    for doc_id in doc_chunks:
        doc_chunks[doc_id].sort(key=lambda c: c.chunk_id)

    # Create a mapping from (document_id, chunk_id) to the section it belongs to
    # This helps us maintain the original order
    chunk_to_section: dict[tuple[str, int], InferenceSection] = {}

    # Process each document's chunks
    for doc_id, doc_chunk_list in doc_chunks.items():
        if not doc_chunk_list:
            continue

        # Group adjacent chunks into sections
        current_section_chunks = [doc_chunk_list[0]]

        for i in range(1, len(doc_chunk_list)):
            prev_chunk = doc_chunk_list[i - 1]
            curr_chunk = doc_chunk_list[i]

            # Check if chunks are adjacent (chunk_id difference is 1)
            if curr_chunk.chunk_id == prev_chunk.chunk_id + 1:
                # Add to current section
                current_section_chunks.append(curr_chunk)
            else:
                # Create section from previous chunks
                # Find the chunk that appears first in the original list
                center_chunk = min(
                    current_section_chunks,
                    key=lambda c: chunk_to_original_index.get(
                        (c.document_id, c.chunk_id), float("inf")
                    ),
                )
                section = inference_section_from_chunks(
                    center_chunk=center_chunk,
                    chunks=current_section_chunks.copy(),
                )
                if section:
                    for chunk in current_section_chunks:
                        chunk_to_section[(chunk.document_id, chunk.chunk_id)] = section

                # Start new section
                current_section_chunks = [curr_chunk]

        # Create section for the last group
        if current_section_chunks:
            # Find the chunk that appears first in the original list
            center_chunk = min(
                current_section_chunks,
                key=lambda c: chunk_to_original_index.get(
                    (c.document_id, c.chunk_id), float("inf")
                ),
            )
            section = inference_section_from_chunks(
                center_chunk=center_chunk,
                chunks=current_section_chunks.copy(),
            )
            if section:
                for chunk in current_section_chunks:
                    chunk_to_section[(chunk.document_id, chunk.chunk_id)] = section

    # Build result list maintaining original order
    # Use (document_id, chunk_id) of center_chunk as unique identifier for sections
    seen_section_ids: set[tuple[str, int]] = set()
    result: list[InferenceSection] = []

    for chunk in chunks:
        section = chunk_to_section.get((chunk.document_id, chunk.chunk_id))
        if section:
            section_id = (
                section.center_chunk.document_id,
                section.center_chunk.chunk_id,
            )
            if section_id not in seen_section_ids:
                seen_section_ids.add(section_id)
                result.append(section)
        else:
            # Chunk wasn't part of any merged section, create a single-chunk section
            single_section = inference_section_from_chunks(
                center_chunk=chunk,
                chunks=[chunk],
            )
            if single_section:
                single_section_id = (
                    single_section.center_chunk.document_id,
                    single_section.center_chunk.chunk_id,
                )
                if single_section_id not in seen_section_ids:
                    seen_section_ids.add(single_section_id)
                    result.append(single_section)

    return result


@log_function_time(print_only=True, debug_only=True)
def search_pipeline(
    # Query and settings
    chunk_search_request: ChunkSearchRequest,
    # Document index to search over
    # Note that federated sources will also be used (not related to this arg)
    document_index: DocumentIndex,
    # Used for ACLs and federated search
    user: User | None,
    # Used for default filters and settings
    persona: Persona | None,
    db_session: Session,
    auto_detect_filters: bool = False,
    llm: LLM | None = None,
    # Needed for federated Slack search
    slack_context: SlackContext | None = None,
    # If a project ID is provided, it will be exclusively scoped to that project
    project_id: int | None = None,
) -> list[InferenceChunk]:
    user_uploaded_persona_files: list[UUID] | None = (
        [user_file.id for user_file in persona.user_files] if persona else None
    )

    persona_document_sets: list[str] | None = (
        [persona_document_set.name for persona_document_set in persona.document_sets]
        if persona
        else None
    )
    persona_time_cutoff: datetime | None = (
        persona.search_start_date if persona else None
    )

    filters = _build_index_filters(
        user_provided_filters=chunk_search_request.user_selected_filters,
        user=user,
        project_id=project_id,
        user_file_ids=user_uploaded_persona_files,
        persona_document_sets=persona_document_sets,
        persona_time_cutoff=persona_time_cutoff,
        db_session=db_session,
        auto_detect_filters=auto_detect_filters,
        query=chunk_search_request.query,
        llm=llm,
        bypass_acl=chunk_search_request.bypass_acl,
    )

    query_request = ChunkIndexRequest(
        query=chunk_search_request.query,
        hybrid_alpha=chunk_search_request.hybrid_alpha,
        recency_bias_multiplier=chunk_search_request.recency_bias_multiplier,
        query_keywords=chunk_search_request.query_keywords,
        filters=filters,
    )

    retrieved_chunks = search_chunks(
        query_request=query_request,
        # Needed for federated Slack search
        user_id=user.id if user else None,
        document_index=document_index,
        db_session=db_session,
        slack_context=slack_context,
    )

    # For some specific connectors like Salesforce, a user that has access to an object doesn't mean
    # that they have access to all of the fields of the object.
    censored_chunks: list[InferenceChunk] = fetch_ee_implementation_or_noop(
        "onyx.external_permissions.post_query_censoring",
        "_post_query_chunk_censoring",
        retrieved_chunks,
    )(
        chunks=retrieved_chunks,
        user=user,
    )

    return censored_chunks


class SearchPipeline:
    def __init__(
        self,
        search_request: SearchRequest,
        user: User | None,
        llm: LLM,
        fast_llm: LLM,
        skip_query_analysis: bool,
        db_session: Session,
        bypass_acl: bool = False,  # NOTE: VERY DANGEROUS, USE WITH CAUTION
        retrieval_metrics_callback: (
            Callable[[RetrievalMetricsContainer], None] | None
        ) = None,
        retrieved_sections_callback: (
            Callable[[list[InferenceSection]], None] | None
        ) = None,
        rerank_metrics_callback: Callable[[RerankMetricsContainer], None] | None = None,
        prompt_config: PromptConfig | None = None,
        contextual_pruning_config: ContextualPruningConfig | None = None,
        slack_context: SlackContext | None = None,
    ):
        # NOTE: The Search Request contains a lot of fields that are overrides, many of them can be None
        # and typically are None. The preprocessing will fetch default values to replace these empty overrides.
        self.search_request = search_request
        self.user = user
        self.llm = llm
        self.fast_llm = fast_llm
        self.skip_query_analysis = skip_query_analysis
        self.db_session = db_session
        self.bypass_acl = bypass_acl
        self.retrieval_metrics_callback = retrieval_metrics_callback
        self.rerank_metrics_callback = rerank_metrics_callback

        self.search_settings = get_current_search_settings(db_session)
        self.document_index = get_default_document_index(self.search_settings, None)
        self.prompt_config: PromptConfig | None = prompt_config
        self.contextual_pruning_config: ContextualPruningConfig | None = (
            contextual_pruning_config
        )
        self.slack_context: SlackContext | None = slack_context

        # Preprocessing steps generate this
        self._search_query: SearchQuery | None = None
        self._predicted_search_type: SearchType | None = None

        # Initial document index retrieval chunks
        self._retrieved_chunks: list[InferenceChunk] | None = None
        # Another call made to the document index to get surrounding sections
        self._retrieved_sections: list[InferenceSection] | None = None

        self.retrieved_sections_callback = retrieved_sections_callback
        # Reranking and LLM section selection can be run together
        # If only LLM selection is on, the reranked chunks are yielded immediatly
        self._reranked_sections: list[InferenceSection] | None = None
        self._final_context_sections: list[InferenceSection] | None = None

        self._section_relevance: list[SectionRelevancePiece] | None = None

        # Generates reranked chunks and LLM selections
        self._postprocessing_generator: (
            Iterator[list[InferenceSection] | list[SectionRelevancePiece]] | None
        ) = None

        # No longer computed but keeping around in case it's reintroduced later
        self._predicted_flow: QueryFlow | None = QueryFlow.QUESTION_ANSWER

    """Pre-processing"""

    def _run_preprocessing(self) -> None:
        final_search_query = retrieval_preprocessing(
            search_request=self.search_request,
            user=self.user,
            llm=self.llm,
            skip_query_analysis=self.skip_query_analysis,
            db_session=self.db_session,
            bypass_acl=self.bypass_acl,
        )
        self._search_query = final_search_query
        self._predicted_search_type = final_search_query.search_type

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

    """Retrieval and Postprocessing"""

    def _get_chunks(self) -> list[InferenceChunk]:
        if self._retrieved_chunks is not None:
            return self._retrieved_chunks

        # These chunks do not include large chunks and have been deduped
        self._retrieved_chunks = retrieve_chunks(
            query=self.search_query,
            user_id=self.user.id if self.user else None,
            document_index=self.document_index,
            db_session=self.db_session,
            retrieval_metrics_callback=self.retrieval_metrics_callback,
            slack_context=self.slack_context,  # Pass Slack context
        )

        return cast(list[InferenceChunk], self._retrieved_chunks)

    @log_function_time(print_only=True)
    def _get_sections(self) -> list[InferenceSection]:
        """Returns an expanded section from each of the chunks.
        If whole docs (instead of above/below context) is specified then it will give back all of the whole docs
        that have a corresponding chunk.

        This step should be fast for any document index implementation.

        Current implementation timing is approximately broken down in timing as:
        - 200 ms to get the embedding of the query
        - 15 ms to get chunks from the document index
        - possibly more to get additional surrounding chunks
        - possibly more for query expansion (multilingual)
        """
        if self._retrieved_sections is not None:
            return self._retrieved_sections

        # These chunks are ordered, deduped, and contain no large chunks
        retrieved_chunks = self._get_chunks()

        # If ee is enabled, censor the chunk sections based on user access
        # Otherwise, return the retrieved chunks
        censored_chunks: list[InferenceChunk] = fetch_ee_implementation_or_noop(
            "onyx.external_permissions.post_query_censoring",
            "_post_query_chunk_censoring",
            retrieved_chunks,
        )(
            chunks=retrieved_chunks,
            user=self.user,
        )

        above = self.search_query.chunks_above
        below = self.search_query.chunks_below

        expanded_inference_sections = []
        inference_chunks: list[InferenceChunk] = []
        chunk_requests: list[VespaChunkRequest] = []

        # Full doc setting takes priority
        if self.search_query.full_doc:
            seen_document_ids = set()

            # This preserves the ordering since the chunks are retrieved in score order
            for chunk in censored_chunks:
                if chunk.document_id not in seen_document_ids:
                    seen_document_ids.add(chunk.document_id)
                    chunk_requests.append(
                        VespaChunkRequest(
                            document_id=chunk.document_id,
                        )
                    )

            inference_chunks.extend(
                self.document_index.id_based_retrieval(
                    chunk_requests=chunk_requests,
                    filters=IndexFilters(access_control_list=None),
                )
            )

            # Create a dictionary to group chunks by document_id
            grouped_inference_chunks: dict[str, list[InferenceChunk]] = {}
            for chunk in inference_chunks:
                if chunk.document_id not in grouped_inference_chunks:
                    grouped_inference_chunks[chunk.document_id] = []
                grouped_inference_chunks[chunk.document_id].append(chunk)

            for chunk_group in grouped_inference_chunks.values():
                inference_section = inference_section_from_chunks(
                    center_chunk=chunk_group[0],
                    chunks=chunk_group,
                )

                if inference_section is not None:
                    expanded_inference_sections.append(inference_section)
                else:
                    logger.warning(
                        "Skipped creation of section for full docs, no chunks found"
                    )

            self._retrieved_sections = expanded_inference_sections
            return expanded_inference_sections

        # General flow:
        # - Combine chunks into lists by document_id
        # - For each document, run merge-intervals to get combined ranges
        #   - This allows for less queries to the document index
        # - Fetch all of the new chunks with contents for the combined ranges
        # - Reiterate the chunks again and map to the results above based on the chunk.
        #   This maintains the original chunks ordering. Note, we cannot simply sort by score here
        #   as reranking flow may wipe the scores for a lot of the chunks.
        doc_chunk_ranges_map = defaultdict(list)
        for chunk in censored_chunks:
            # The list of ranges for each document is ordered by score
            doc_chunk_ranges_map[chunk.document_id].append(
                ChunkRange(
                    chunks=[chunk],
                    start=max(0, chunk.chunk_id - above),
                    # No max known ahead of time, filter will handle this anyway
                    end=chunk.chunk_id + below,
                )
            )

        # List of ranges, outside list represents documents, inner list represents ranges
        merged_ranges = [
            merge_chunk_intervals(ranges) for ranges in doc_chunk_ranges_map.values()
        ]

        flat_ranges: list[ChunkRange] = [r for ranges in merged_ranges for r in ranges]

        for chunk_range in flat_ranges:
            # Don't need to fetch chunks within range for merging if chunk_above / below are 0.
            if above == below == 0:
                inference_chunks.extend(chunk_range.chunks)

            else:
                chunk_requests.append(
                    VespaChunkRequest(
                        document_id=chunk_range.chunks[0].document_id,
                        min_chunk_ind=chunk_range.start,
                        max_chunk_ind=chunk_range.end,
                    )
                )

        if chunk_requests:
            inference_chunks.extend(
                self.document_index.id_based_retrieval(
                    chunk_requests=chunk_requests,
                    filters=IndexFilters(access_control_list=None),
                    batch_retrieval=True,
                )
            )

        doc_chunk_ind_to_chunk = {
            (chunk.document_id, chunk.chunk_id): chunk for chunk in inference_chunks
        }

        # In case of failed parallel calls to Vespa, at least we should have the initial retrieved chunks
        doc_chunk_ind_to_chunk.update(
            {(chunk.document_id, chunk.chunk_id): chunk for chunk in censored_chunks}
        )

        # Build the surroundings for all of the initial retrieved chunks
        for chunk in censored_chunks:
            start_ind = max(0, chunk.chunk_id - above)
            end_ind = chunk.chunk_id + below

            # Since the index of the max_chunk is unknown, just allow it to be None and filter after
            surrounding_chunks_or_none = [
                doc_chunk_ind_to_chunk.get((chunk.document_id, chunk_ind))
                for chunk_ind in range(start_ind, end_ind + 1)  # end_ind is inclusive
            ]
            # The None will apply to the would be "chunks" that are larger than the index of the last chunk
            # of the document
            surrounding_chunks = [
                chunk for chunk in surrounding_chunks_or_none if chunk is not None
            ]

            inference_section = inference_section_from_chunks(
                center_chunk=chunk,
                chunks=surrounding_chunks,
            )
            if inference_section is not None:
                expanded_inference_sections.append(inference_section)
            else:
                logger.warning("Skipped creation of section, no chunks found")

        self._retrieved_sections = expanded_inference_sections
        return expanded_inference_sections

    @property
    def retrieved_sections(self) -> list[InferenceSection]:
        if self._retrieved_sections is not None:
            return self._retrieved_sections

        self._retrieved_sections = self._get_sections()
        return self._retrieved_sections

    @property
    def merged_retrieved_sections(self) -> list[InferenceSection]:
        """Should be used to display in the UI in order to prevent displaying
        multiple sections for the same document as separate "documents"."""
        return _merge_sections(sections=self.retrieved_sections)

    @property
    def reranked_sections(self) -> list[InferenceSection]:
        """Reranking is always done at the chunk level since section merging could create arbitrarily
        long sections which could be:
        1. Longer than the maximum context limit of even large rerankers
        2. Slow to calculate due to the quadratic scaling laws of Transformers

        See implementation in search_postprocessing for details
        """
        if self._reranked_sections is not None:
            return self._reranked_sections

        retrieved_sections = self.retrieved_sections
        if self.retrieved_sections_callback is not None:
            self.retrieved_sections_callback(retrieved_sections)

        self._postprocessing_generator = search_postprocessing(
            search_query=self.search_query,
            retrieved_sections=retrieved_sections,
            llm=self.fast_llm,
            rerank_metrics_callback=self.rerank_metrics_callback,
        )

        self._reranked_sections = cast(
            list[InferenceSection], next(self._postprocessing_generator)
        )

        return self._reranked_sections

    @property
    def final_context_sections(self) -> list[InferenceSection]:
        if self._final_context_sections is not None:
            return self._final_context_sections

        if (
            self.contextual_pruning_config is not None
            and self.prompt_config is not None
        ):
            from onyx.llm.utils import check_number_of_tokens

            # For backwards compatibility with non-v2 flows, use query token count
            # and pass prompt_config for proper token calculation
            query_token_count = check_number_of_tokens(self.search_query.query)

            self._final_context_sections = prune_and_merge_sections(
                sections=self.reranked_sections,
                section_relevance_list=None,
                llm_config=self.llm.config,
                existing_input_tokens=query_token_count,
                contextual_pruning_config=self.contextual_pruning_config,
                prompt_config=self.prompt_config,
            )

        else:
            logger.error(
                "Contextual pruning or prompt config not set, using default merge"
            )
            self._final_context_sections = _merge_sections(
                sections=self.reranked_sections
            )
        return self._final_context_sections

    @property
    def section_relevance(self) -> list[SectionRelevancePiece] | None:
        if self._section_relevance is not None:
            return self._section_relevance

        if (
            self.search_query.evaluation_type == LLMEvaluationType.SKIP
            or DISABLE_LLM_DOC_RELEVANCE
        ):
            return None

        if self.search_query.evaluation_type == LLMEvaluationType.UNSPECIFIED:
            raise ValueError(
                "Attempted to access section relevance scores on search query with evaluation type `UNSPECIFIED`."
                + "The search query evaluation type should have been specified."
            )

        if self.search_query.evaluation_type == LLMEvaluationType.AGENTIC:
            sections = self.final_context_sections
            functions = [
                FunctionCall(
                    evaluate_inference_section,
                    (section, self.search_query.query, self.llm),
                )
                for section in sections
            ]
            try:
                results = run_functions_in_parallel(function_calls=functions)
                self._section_relevance = list(results.values())
            except Exception as e:
                raise ValueError(
                    "An issue occured during the agentic evaluation process."
                ) from e

        elif self.search_query.evaluation_type == LLMEvaluationType.BASIC:
            if DISABLE_LLM_DOC_RELEVANCE:
                raise ValueError(
                    "Basic search evaluation operation called while DISABLE_LLM_DOC_RELEVANCE is enabled."
                )
            # NOTE: final_context_sections must be accessed before accessing self._postprocessing_generator
            # since the property sets the generator. DO NOT REMOVE.
            _ = self.final_context_sections

            self._section_relevance = next(
                cast(
                    Iterator[list[SectionRelevancePiece]],
                    self._postprocessing_generator,
                )
            )

        else:
            # All other cases should have been handled above
            raise ValueError(
                f"Unexpected evaluation type: {self.search_query.evaluation_type}"
            )

        return self._section_relevance

    @property
    def section_relevance_list(self) -> list[bool]:
        return section_relevance_list_impl(
            section_relevance=self.section_relevance,
            final_context_sections=self.final_context_sections,
        )


def section_relevance_list_impl(
    section_relevance: list[SectionRelevancePiece] | None,
    final_context_sections: list[InferenceSection],
) -> list[bool]:
    llm_indices = relevant_sections_to_indices(
        relevance_sections=section_relevance,
        items=final_context_sections,
    )
    return [ind in llm_indices for ind in range(len(final_context_sections))]
