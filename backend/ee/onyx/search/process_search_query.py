from collections.abc import Generator

from sqlalchemy.orm import Session

from ee.onyx.db.search import create_search_query
from ee.onyx.secondary_llm_flows.query_expansion import expand_keywords
from ee.onyx.server.query_and_chat.models import SearchDocWithContent
from ee.onyx.server.query_and_chat.models import SearchFullResponse
from ee.onyx.server.query_and_chat.models import SendSearchQueryRequest
from ee.onyx.server.query_and_chat.streaming_models import LLMSelectedDocsPacket
from ee.onyx.server.query_and_chat.streaming_models import SearchDocsPacket
from ee.onyx.server.query_and_chat.streaming_models import SearchErrorPacket
from ee.onyx.server.query_and_chat.streaming_models import SearchQueriesPacket
from onyx.context.search.models import BaseFilters
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.models import InferenceChunk
from onyx.context.search.pipeline import merge_individual_chunks
from onyx.context.search.pipeline import search_pipeline
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.interfaces import DocumentIndex
from onyx.llm.factory import get_default_llm
from onyx.secondary_llm_flows.document_filter import select_sections_for_expansion
from onyx.tools.tool_implementations.search.search_utils import (
    weighted_reciprocal_rank_fusion,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel

logger = setup_logger()


# This is just a heuristic that also happens to work well for the UI/UX
# Users would not find it useful to see a huge list of suggested docs
# but more than 1 is also likely good as many questions may target more than 1 doc.
TARGET_NUM_SECTIONS_FOR_LLM_SELECTION = 3


def _run_single_search(
    query: str,
    filters: BaseFilters | None,
    document_index: DocumentIndex,
    user: User,
    db_session: Session,
    num_hits: int | None = None,
) -> list[InferenceChunk]:
    """Execute a single search query and return chunks."""
    chunk_search_request = ChunkSearchRequest(
        query=query,
        user_selected_filters=filters,
        limit=num_hits,
    )

    return search_pipeline(
        chunk_search_request=chunk_search_request,
        document_index=document_index,
        user=user,
        persona=None,  # No persona for direct search
        db_session=db_session,
    )


def stream_search_query(
    request: SendSearchQueryRequest,
    user: User,
    db_session: Session,
) -> Generator[
    SearchQueriesPacket | SearchDocsPacket | LLMSelectedDocsPacket | SearchErrorPacket,
    None,
    None,
]:
    """
    Core search function that yields streaming packets.
    Used by both streaming and non-streaming endpoints.
    """
    # Get document index
    search_settings = get_current_search_settings(db_session)
    # This flow is for search so we do not get all indices.
    document_index = get_default_document_index(search_settings, None)

    # Determine queries to execute
    original_query = request.search_query
    keyword_expansions: list[str] = []

    if request.run_query_expansion:
        try:
            llm = get_default_llm()
            keyword_expansions = expand_keywords(
                user_query=original_query,
                llm=llm,
            )
            if keyword_expansions:
                logger.debug(
                    f"Query expansion generated {len(keyword_expansions)} keyword queries"
                )
        except Exception as e:
            logger.warning(f"Query expansion failed: {e}; using original query only.")
            keyword_expansions = []

    # Build list of all executed queries for tracking
    all_executed_queries = [original_query] + keyword_expansions

    if not user.is_anonymous:
        create_search_query(
            db_session=db_session,
            user_id=user.id,
            query=request.search_query,
            query_expansions=keyword_expansions if keyword_expansions else None,
        )

    # Execute search(es)
    if not keyword_expansions:
        # Single query (original only) - no threading needed
        chunks = _run_single_search(
            query=original_query,
            filters=request.filters,
            document_index=document_index,
            user=user,
            db_session=db_session,
            num_hits=request.num_hits,
        )
    else:
        # Multiple queries - run in parallel and merge with RRF
        # First query is the original (semantic), rest are keyword expansions
        search_functions = [
            (
                _run_single_search,
                (
                    query,
                    request.filters,
                    document_index,
                    user,
                    db_session,
                    request.num_hits,
                ),
            )
            for query in all_executed_queries
        ]

        # Run all searches in parallel
        all_search_results: list[list[InferenceChunk]] = (
            run_functions_tuples_in_parallel(
                search_functions,
                allow_failures=True,
            )
        )

        # Separate original query results from keyword expansion results
        # Note that in rare cases, the original query may have failed and so we may be
        # just overweighting one set of keyword results, should be not a big deal though.
        original_result = all_search_results[0] if all_search_results else []
        keyword_results = all_search_results[1:] if len(all_search_results) > 1 else []

        # Build valid results and weights
        # Original query (semantic): weight 2.0
        # Keyword expansions: weight 1.0 each
        valid_results: list[list[InferenceChunk]] = []
        weights: list[float] = []

        if original_result:
            valid_results.append(original_result)
            weights.append(2.0)

        for keyword_result in keyword_results:
            if keyword_result:
                valid_results.append(keyword_result)
                weights.append(1.0)

        if not valid_results:
            logger.warning("All parallel searches returned empty results")
            chunks = []
        else:
            chunks = weighted_reciprocal_rank_fusion(
                ranked_results=valid_results,
                weights=weights,
                id_extractor=lambda chunk: f"{chunk.document_id}_{chunk.chunk_id}",
            )

    # Merge chunks into sections
    sections = merge_individual_chunks(chunks)

    # Truncate to the requested number of hits
    sections = sections[: request.num_hits]

    # Apply LLM document selection if requested
    # num_docs_fed_to_llm_selection specifies how many sections to feed to the LLM for selection
    # The LLM will always try to select TARGET_NUM_SECTIONS_FOR_LLM_SELECTION sections from those fed to it
    # llm_selected_doc_ids will be:
    #   - None if LLM selection was not requested or failed
    #   - Empty list if LLM selection ran but selected nothing
    #   - List of doc IDs if LLM selection succeeded
    run_llm_selection = (
        request.num_docs_fed_to_llm_selection is not None
        and request.num_docs_fed_to_llm_selection >= 1
    )
    llm_selected_doc_ids: list[str] | None = None
    llm_selection_failed = False
    if run_llm_selection and sections:
        try:
            llm = get_default_llm()
            sections_to_evaluate = sections[: request.num_docs_fed_to_llm_selection]
            selected_sections, _ = select_sections_for_expansion(
                sections=sections_to_evaluate,
                user_query=original_query,
                llm=llm,
                max_sections=TARGET_NUM_SECTIONS_FOR_LLM_SELECTION,
                try_to_fill_to_max=True,
            )
            # Extract unique document IDs from selected sections (may be empty)
            llm_selected_doc_ids = list(
                dict.fromkeys(
                    section.center_chunk.document_id for section in selected_sections
                )
            )
            logger.debug(
                f"LLM document selection evaluated {len(sections_to_evaluate)} sections, "
                f"selected {len(selected_sections)} sections with doc IDs: {llm_selected_doc_ids}"
            )
        except Exception as e:
            # Allowing a blanket exception here as this step is not critical and the rest of the results are still valid
            logger.warning(f"LLM document selection failed: {e}")
            llm_selection_failed = True
    elif run_llm_selection and not sections:
        # LLM selection requested but no sections to evaluate
        llm_selected_doc_ids = []

    # Convert to SearchDocWithContent list, optionally including content
    search_docs = SearchDocWithContent.from_inference_sections(
        sections,
        include_content=request.include_content,
        is_internet=False,
    )

    # Yield queries packet
    yield SearchQueriesPacket(all_executed_queries=all_executed_queries)

    # Yield docs packet
    yield SearchDocsPacket(search_docs=search_docs)

    # Yield LLM selected docs packet if LLM selection was requested
    # - llm_selected_doc_ids is None if selection failed
    # - llm_selected_doc_ids is empty list if no docs were selected
    # - llm_selected_doc_ids is list of IDs if docs were selected
    if run_llm_selection:
        yield LLMSelectedDocsPacket(
            llm_selected_doc_ids=None if llm_selection_failed else llm_selected_doc_ids
        )


def gather_search_stream(
    packets: Generator[
        SearchQueriesPacket
        | SearchDocsPacket
        | LLMSelectedDocsPacket
        | SearchErrorPacket,
        None,
        None,
    ],
) -> SearchFullResponse:
    """
    Aggregate all streaming packets into SearchFullResponse.
    """
    all_executed_queries: list[str] = []
    search_docs: list[SearchDocWithContent] = []
    llm_selected_doc_ids: list[str] | None = None
    error: str | None = None

    for packet in packets:
        if isinstance(packet, SearchQueriesPacket):
            all_executed_queries = packet.all_executed_queries
        elif isinstance(packet, SearchDocsPacket):
            search_docs = packet.search_docs
        elif isinstance(packet, LLMSelectedDocsPacket):
            llm_selected_doc_ids = packet.llm_selected_doc_ids
        elif isinstance(packet, SearchErrorPacket):
            error = packet.error

    return SearchFullResponse(
        all_executed_queries=all_executed_queries,
        search_docs=search_docs,
        doc_selection_reasoning=None,
        llm_selected_doc_ids=llm_selected_doc_ids,
        error=error,
    )
