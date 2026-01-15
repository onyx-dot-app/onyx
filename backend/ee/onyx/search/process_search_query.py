from collections.abc import Generator

from sqlalchemy.orm import Session

from ee.onyx.db.search import create_search_query
from ee.onyx.server.query_and_chat.models import SearchFullResponse
from ee.onyx.server.query_and_chat.models import SendSearchQueryRequest
from ee.onyx.server.query_and_chat.streaming_models import SearchDocsPacket
from ee.onyx.server.query_and_chat.streaming_models import SearchErrorPacket
from ee.onyx.server.query_and_chat.streaming_models import SearchQueriesPacket
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.pipeline import merge_individual_chunks
from onyx.context.search.pipeline import search_pipeline
from onyx.context.search.utils import convert_inference_sections_to_search_docs
from onyx.db.models import User
from onyx.document_index.factory import get_current_primary_default_document_index


def stream_search_query(
    request: SendSearchQueryRequest,
    user: User | None,
    db_session: Session,
) -> Generator[SearchQueriesPacket | SearchDocsPacket | SearchErrorPacket, None, None]:
    """
    Core search function that yields streaming packets.
    Used by both streaming and non-streaming endpoints.
    """
    # Check for not-yet-implemented features
    if request.run_query_expansion:
        raise NotImplementedError("Query expansion is not yet implemented")
    if request.num_docs_fed_to_llm_selection is not None:
        raise NotImplementedError("LLM document selection is not yet implemented")

    # Get document index
    document_index = get_current_primary_default_document_index(db_session)

    # Build search request
    chunk_search_request = ChunkSearchRequest(
        query=request.search_query,
        user_selected_filters=request.filters,
    )

    # Execute search
    chunks = search_pipeline(
        chunk_search_request=chunk_search_request,
        document_index=document_index,
        user=user,
        persona=None,  # No persona for direct search
        db_session=db_session,
    )

    # Merge chunks into sections
    sections = merge_individual_chunks(chunks)

    # Convert to SearchDoc list
    search_docs = convert_inference_sections_to_search_docs(sections, is_internet=False)

    # Track executed queries (just the original for now)
    all_executed_queries = [request.search_query]

    # Yield queries packet
    yield SearchQueriesPacket(all_executed_queries=all_executed_queries)

    # Yield docs packet
    yield SearchDocsPacket(search_docs=search_docs)

    # Save search query to DB (only if user is authenticated)
    if user is not None:
        create_search_query(
            db_session=db_session,
            user_id=user.id,
            query=request.search_query,
            query_expansions=None,  # No expansions for now
        )


def gather_search_stream(
    packets: Generator[
        SearchQueriesPacket | SearchDocsPacket | SearchErrorPacket, None, None
    ],
) -> SearchFullResponse:
    """
    Aggregate all streaming packets into SearchFullResponse.
    """
    all_executed_queries: list[str] = []
    search_docs: list = []
    error: str | None = None

    for packet in packets:
        if isinstance(packet, SearchQueriesPacket):
            all_executed_queries = packet.all_executed_queries
        elif isinstance(packet, SearchDocsPacket):
            search_docs = packet.search_docs
        elif isinstance(packet, SearchErrorPacket):
            error = packet.error

    return SearchFullResponse(
        all_executed_queries=all_executed_queries,
        search_docs=search_docs,
        doc_selection_reasoning=None,
        llm_selected_doc_ids=None,
        error=error,
    )
