"""Companion tool to the internal search tool that serves deeper pages of a
prior search.

Page windows slice into the search's cached RRF-merged section list (see
``SearchToolTurnState``). When a requested page runs past what was cached, the
tool re-runs the exact same query specs against the document index with an
offset, RRF-merges the new window with globally consistent ranks, dedups
against everything already cached, and extends the cached list. Every served
page gets the same LLM relevance-selection + context-expansion treatment as
the original search results.
"""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.models import InferenceChunk
from onyx.context.search.models import PersonaSearchInfo
from onyx.context.search.models import SearchDocsResponse
from onyx.context.search.pipeline import merge_individual_chunks
from onyx.context.search.pipeline import search_pipeline
from onyx.db.models import User
from onyx.document_index.interfaces_new import DocumentIndex
from onyx.document_index.opensearch.constants import (
    DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW,
)
from onyx.llm.interfaces import LLM
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.tools.interface import Tool
from onyx.tools.models import PaginateSearchResultsOverrideKwargs
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse
from onyx.tools.tool_implementations.search.constants import (
    MAX_PAGINATION_FALLBACK_ROUNDS,
)
from onyx.tools.tool_implementations.search.search_tool import (
    run_post_retrieval_pipeline,
)
from onyx.tools.tool_implementations.search.search_tool import SearchTool
from onyx.tools.tool_implementations.search.search_utils import (
    weighted_reciprocal_rank_fusion,
)
from onyx.tools.tool_implementations.search.turn_state import ExecutedQuerySpec
from onyx.tools.tool_implementations.search.turn_state import SearchEntry
from onyx.tools.tool_implementations.search.turn_state import SearchToolTurnState
from onyx.tools.tool_implementations.utils import (
    convert_inference_sections_to_llm_string,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel
from onyx.utils.timing import log_function_time

logger = setup_logger()

SEARCH_QUERY_ID_FIELD = "search_query_id"
PAGE_FIELD = "page"


class PaginateSearchResultsTool(Tool[PaginateSearchResultsOverrideKwargs]):
    NAME = "paginate_search_results"
    DISPLAY_NAME = "Paginate Search Results"
    DESCRIPTION = (
        "Fetch an additional page of results from a previous internal_search call, "
        "instead of repeating the same queries. Requires a valid search_query_id "
        "(returned by an earlier internal_search result) and a page number. Pages are "
        "0-indexed: the original internal_search returned page 0, so request page 1 for "
        "the second set of results (starting at index 1), page 2 for the third set, and "
        "so on."
    )

    def __init__(
        self,
        # Shares the internal search tool's DB tool id — this is a companion
        # tool that exists exactly when the search tool does.
        tool_id: int,
        emitter: Emitter,
        user: User,
        persona_search_info: PersonaSearchInfo,
        llm: LLM,
        document_index: DocumentIndex,
        turn_state: SearchToolTurnState,
    ) -> None:
        super().__init__(emitter=emitter)

        self.user = user
        self.persona_search_info = persona_search_info
        self.llm = llm
        self.document_index = document_index
        self.turn_state = turn_state

        self._id = tool_id

    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        # Available exactly when the internal search tool is.
        return SearchTool.is_available(db_session)

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    def tool_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        SEARCH_QUERY_ID_FIELD: {
                            "type": "integer",
                            "description": (
                                "The search_query_id returned by a previous "
                                "internal_search result."
                            ),
                        },
                        PAGE_FIELD: {
                            "type": "integer",
                            "description": (
                                "The 0-indexed page of results to fetch. The original "
                                "search is page 0, so use 1 for the second set of "
                                "results (starting at index 1), 2 for the third set, "
                                "etc."
                            ),
                        },
                    },
                    "required": [SEARCH_QUERY_ID_FIELD, PAGE_FIELD],
                },
            },
        }

    def emit_start(self, placement: Placement) -> None:
        # Reuses the search tool's packet types so the frontend renders a
        # pagination call exactly like a search section.
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=SearchToolStart(),
            )
        )

    @log_function_time(print_only=True)
    def run(
        self,
        placement: Placement,
        override_kwargs: PaginateSearchResultsOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        try:
            search_query_id = int(llm_kwargs[SEARCH_QUERY_ID_FIELD])
            page = int(llm_kwargs[PAGE_FIELD])
        except (KeyError, TypeError, ValueError):
            raise ToolCallException(
                message=(
                    "paginate_search_results called without valid integer "
                    f"'{SEARCH_QUERY_ID_FIELD}' and '{PAGE_FIELD}' parameters"
                ),
                llm_facing_message=(
                    "The paginate_search_results tool requires an integer "
                    f"'{SEARCH_QUERY_ID_FIELD}' (from a prior internal_search result) "
                    f"and an integer '{PAGE_FIELD}', like: "
                    f'{{"{SEARCH_QUERY_ID_FIELD}": 1, "{PAGE_FIELD}": 1}}'
                ),
            )
        if page < 0:
            raise ToolCallException(
                message=f"paginate_search_results called with negative page {page}",
                llm_facing_message=(
                    f"'{PAGE_FIELD}' must be >= 0 (page 0 is the original search)."
                ),
            )

        entry = self.turn_state.get(search_query_id)
        if entry is None:
            raise ToolCallException(
                message=(
                    f"paginate_search_results called with unknown search_query_id "
                    f"{search_query_id}"
                ),
                llm_facing_message=(
                    f"Unknown search_query_id {search_query_id}. Use a search_query_id "
                    "returned by a prior internal_search result in this turn, or run a "
                    "new internal_search."
                ),
            )

        num_hits = override_kwargs.num_hits or NUM_RETURNED_HITS

        with entry.lock:
            # Idempotent re-serve: the same page always returns the same
            # content with the same citation numbers. This also covers page 0
            # (the original search response is stashed at search time).
            cached_response = entry.page_responses.get(page)
            if cached_response is not None:
                return cached_response

            window_start = page * num_hits
            window_end = window_start + num_hits

            fallback_rounds = 0
            while (
                len(entry.merged_sections) < window_end
                and not entry.exhausted
                and fallback_rounds < MAX_PAGINATION_FALLBACK_ROUNDS
            ):
                self._fetch_more_results(entry, num_hits)
                fallback_rounds += 1

            window = entry.merged_sections[window_start:window_end]

            if not window:
                empty_response, _ = convert_inference_sections_to_llm_string(
                    top_sections=[],
                    search_query_id=search_query_id,
                    page=page,
                    note=(
                        "No further results for this search. Run a new "
                        "internal_search with different queries to keep searching."
                    ),
                )
                tool_response = ToolResponse(
                    rich_response=SearchDocsResponse(
                        search_docs=[],
                        citation_mapping={},
                        displayed_docs=None,
                    ),
                    llm_facing_response=empty_response,
                )
                entry.page_responses[page] = tool_response
                return tool_response

            tool_response = run_post_retrieval_pipeline(
                sections=window,
                user_query=entry.user_query,
                llm=self.llm,
                document_index=self.document_index,
                emitter=self.emitter,
                placement=placement,
                starting_citation_num=override_kwargs.starting_citation_num,
                max_llm_chunks=override_kwargs.max_llm_chunks,
                include_link=override_kwargs.include_link,
                search_query_id=search_query_id,
                page=page,
            )
            entry.page_responses[page] = tool_response
            return tool_response

    def _fetch_more_results(self, entry: SearchEntry, num_hits: int) -> None:
        """Extend the entry's merged section list with one more retrieval
        window of every original query, fetched from the document index with an
        offset. Must be called with ``entry.lock`` held.

        Latches ``entry.exhausted`` when nothing new can be fetched: window
        limits reached, all re-queries failed (e.g. the index doesn't support
        offsets), or a full round yielded no unseen chunks.
        """
        offset = entry.per_query_fetch_depth
        if offset + num_hits > DEFAULT_OPENSEARCH_MAX_RESULT_WINDOW:
            logger.info(
                "Pagination fallback would exceed the max result window "
                "(offset %s + %s hits) — marking search exhausted",
                offset,
                num_hits,
            )
            entry.exhausted = True
            return

        run_queries: list[tuple[Callable, tuple]] = [
            (self._run_offset_query, (spec, entry, num_hits, offset))
            for spec in entry.query_specs
        ]
        # Failures (e.g. NotImplementedError from a non-OpenSearch index)
        # resolve to None instead of aborting the whole page.
        per_query_results: list[list[InferenceChunk] | None] = (
            run_functions_tuples_in_parallel(run_queries, allow_failures=True)
        )

        successful_results: list[list[InferenceChunk]] = []
        successful_weights: list[float] = []
        for spec, result in zip(entry.query_specs, per_query_results):
            if result is None:
                continue
            successful_results.append(result)
            successful_weights.append(spec.weight)

        if not successful_results:
            logger.warning(
                "All pagination fallback queries failed — marking search exhausted"
            )
            entry.exhausted = True
            return

        # rank_offset keeps RRF scores consistent with the earlier windows of
        # the same queries (an item at local rank 1 of this window is globally
        # at rank offset + 1).
        merged_chunks = weighted_reciprocal_rank_fusion(
            ranked_results=successful_results,
            weights=successful_weights,
            id_extractor=lambda chunk: f"{chunk.document_id}_{chunk.chunk_id}",
            rank_offset=offset,
        )

        new_chunks = [
            chunk
            for chunk in merged_chunks
            if (chunk.document_id, chunk.chunk_id) not in entry.cached_chunk_ids
        ]

        entry.per_query_fetch_depth = offset + num_hits

        if not new_chunks:
            logger.info(
                "Pagination fallback fetched no unseen chunks — marking search "
                "exhausted"
            )
            entry.exhausted = True
            return

        new_sections = merge_individual_chunks(new_chunks)
        entry.merged_sections.extend(new_sections)
        entry.cached_chunk_ids.update(
            (chunk.document_id, chunk.chunk_id)
            for section in new_sections
            for chunk in section.chunks
        )
        logger.info(
            "Pagination fallback (offset %s) added %s sections (%s total cached)",
            offset,
            len(new_sections),
            len(entry.merged_sections),
        )

    def _run_offset_query(
        self,
        spec: ExecutedQuerySpec,
        entry: SearchEntry,
        num_hits: int,
        offset: int,
    ) -> list[InferenceChunk]:
        """Re-run one of the search's original queries against the document
        index with an offset. Federated sources (e.g. Slack) are deliberately
        excluded — pagination only covers the document index."""
        return search_pipeline(
            chunk_search_request=ChunkSearchRequest(
                query=spec.query,
                hybrid_alpha=spec.hybrid_alpha,
                # Match SearchTool._run_search_for_query: project scope ignores
                # user filters.
                user_selected_filters=(
                    entry.effective_filters if entry.project_id_filter is None else None
                ),
                bypass_acl=entry.bypass_acl,
                limit=num_hits,
                offset=offset,
            ),
            project_id_filter=entry.project_id_filter,
            persona_id_filter=entry.persona_id_filter,
            document_index=self.document_index,
            user=self.user,
            persona_search_info=self.persona_search_info,
            acl_filters=entry.acl_filters,
            embedding_model=entry.embedding_model,
            prefetched_federated_retrieval_infos=[],
        )
