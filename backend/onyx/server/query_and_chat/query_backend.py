import json
from collections.abc import Generator
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_user
from onyx.chat.chat_utils import combine_message_thread
from onyx.chat.chat_utils import prepare_chat_message_request
from onyx.chat.models import AnswerStream
from onyx.chat.models import PersonaOverrideConfig
from onyx.chat.models import QADocsResponse
from onyx.chat.process_message import gather_stream
from onyx.chat.process_message import stream_chat_message_objects
from onyx.configs.chat_configs import NUM_RETURNED_HITS
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.configs.onyxbot_configs import MAX_THREAD_CONTEXT_PERCENTAGE
from onyx.context.search.models import ChunkSearchRequest
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import SavedSearchDocWithContent
from onyx.context.search.models import SearchDoc
from onyx.context.search.pipeline import merge_individual_chunks
from onyx.context.search.pipeline import search_pipeline
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.context.search.utils import dedupe_documents
from onyx.context.search.utils import drop_llm_indices
from onyx.context.search.utils import relevant_sections_to_indices
from onyx.db.chat import get_chat_messages_by_session
from onyx.db.chat import get_chat_session_by_id
from onyx.db.chat import get_chat_sessions_by_user
from onyx.db.chat import get_search_docs_for_chat_message
from onyx.db.chat import get_valid_messages_from_query_sessions
from onyx.db.chat import translate_db_message_to_chat_message_detail
from onyx.db.chat import translate_db_search_doc_to_saved_search_doc
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.persona import get_persona_by_id
from onyx.db.search_settings import get_current_search_settings
from onyx.db.tag import find_tags
from onyx.db.usage import increment_usage
from onyx.db.usage import UsageType
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.vespa.index import VespaIndex
from onyx.llm.factory import get_default_llm
from onyx.llm.factory import get_llm_for_persona
from onyx.natural_language_processing.utils import get_tokenizer
from onyx.server.query_and_chat.models import AdminSearchRequest
from onyx.server.query_and_chat.models import AdminSearchResponse
from onyx.server.query_and_chat.models import ChatSessionDetails
from onyx.server.query_and_chat.models import ChatSessionsResponse
from onyx.server.query_and_chat.models import DocumentSearchPagination
from onyx.server.query_and_chat.models import DocumentSearchRequest
from onyx.server.query_and_chat.models import DocumentSearchResponse
from onyx.server.query_and_chat.models import MessageOrigin
from onyx.server.query_and_chat.models import OneShotQARequest
from onyx.server.query_and_chat.models import OneShotQAResponse
from onyx.server.query_and_chat.models import SearchSessionDetailResponse
from onyx.server.query_and_chat.models import SourceTag
from onyx.server.query_and_chat.models import TagResponse
from onyx.server.usage_limits import check_usage_and_raise
from onyx.server.usage_limits import is_usage_limits_enabled
from onyx.server.utils import get_json_line
from onyx.server.utils import PUBLIC_API_TAGS
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

admin_router = APIRouter(prefix="/admin")
basic_router = APIRouter(prefix="/query")


def _normalize_pagination(limit: int | None, offset: int | None) -> tuple[int, int]:
    if limit is None:
        resolved_limit = NUM_RETURNED_HITS
    else:
        resolved_limit = limit

    if resolved_limit <= 0:
        raise HTTPException(
            status_code=400, detail="retrieval_options.limit must be positive"
        )

    if offset is None:
        resolved_offset = 0
    else:
        resolved_offset = offset

    if resolved_offset < 0:
        raise HTTPException(
            status_code=400, detail="retrieval_options.offset cannot be negative"
        )

    return resolved_limit, resolved_offset


@basic_router.post("/document-search", tags=PUBLIC_API_TAGS)
def handle_search_request(
    search_request: DocumentSearchRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> DocumentSearchResponse:
    """Simple search endpoint, does not create a new message or records in the DB"""
    query = search_request.message
    logger.notice(f"Received document search query: {query}")

    llm = get_default_llm()
    pagination_limit, pagination_offset = _normalize_pagination(
        limit=search_request.retrieval_options.limit,
        offset=search_request.retrieval_options.offset,
    )

    search_settings = get_current_search_settings(db_session)
    document_index = get_default_document_index(search_settings, None)

    chunk_search_request = ChunkSearchRequest(
        query=query,
        user_selected_filters=search_request.retrieval_options.filters,
        limit=pagination_limit + 1,
        offset=pagination_offset,
        bypass_acl=False,
    )

    retrieved_chunks = search_pipeline(
        chunk_search_request=chunk_search_request,
        document_index=document_index,
        user=user,
        persona=None,
        db_session=db_session,
        auto_detect_filters=search_request.retrieval_options.enable_auto_detect_filters
        or False,
        llm=llm,
    )

    top_sections = merge_individual_chunks(retrieved_chunks)
    relevance_sections: list = []
    top_docs = [
        SavedSearchDocWithContent(
            document_id=section.center_chunk.document_id,
            chunk_ind=section.center_chunk.chunk_id,
            content=section.center_chunk.content,
            semantic_identifier=section.center_chunk.semantic_identifier or "Unknown",
            link=(
                section.center_chunk.source_links.get(0)
                if section.center_chunk.source_links
                else None
            ),
            blurb=section.center_chunk.blurb,
            source_type=section.center_chunk.source_type,
            boost=section.center_chunk.boost,
            hidden=section.center_chunk.hidden,
            metadata=section.center_chunk.metadata,
            score=section.center_chunk.score or 0.0,
            match_highlights=section.center_chunk.match_highlights,
            updated_at=section.center_chunk.updated_at,
            primary_owners=section.center_chunk.primary_owners,
            secondary_owners=section.center_chunk.secondary_owners,
            is_internet=False,
            db_doc_id=0,
        )
        for section in top_sections
    ]

    # Track whether the underlying retrieval produced more items than requested
    has_more_results = len(top_docs) > pagination_limit

    # Deduping happens at the last step to avoid harming quality by dropping content early on
    deduped_docs = top_docs
    dropped_inds = None

    if search_request.retrieval_options.dedupe_docs:
        deduped_docs, dropped_inds = dedupe_documents(top_docs)

    llm_indices = relevant_sections_to_indices(
        relevance_sections=relevance_sections, items=deduped_docs
    )

    if dropped_inds:
        llm_indices = drop_llm_indices(
            llm_indices=llm_indices,
            search_docs=deduped_docs,
            dropped_indices=dropped_inds,
        )

    paginated_docs = deduped_docs[:pagination_limit]
    llm_indices = [index for index in llm_indices if index < len(paginated_docs)]
    has_more = has_more_results
    pagination = DocumentSearchPagination(
        offset=pagination_offset,
        limit=pagination_limit,
        returned_count=len(paginated_docs),
        has_more=has_more,
        next_offset=(pagination_offset + pagination_limit) if has_more else None,
    )

    return DocumentSearchResponse(
        top_documents=paginated_docs,
        llm_indices=llm_indices,
        pagination=pagination,
    )


def get_answer_stream(
    query_request: OneShotQARequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> AnswerStream:
    query = query_request.messages[0].message
    logger.notice(f"Received query for Answer API: {query}")

    if (
        query_request.persona_override_config is None
        and query_request.persona_id is None
    ):
        raise KeyError("Must provide persona ID or Persona Config")

    persona_info: Persona | PersonaOverrideConfig | None = None
    if query_request.persona_override_config is not None:
        persona_info = query_request.persona_override_config
    elif query_request.persona_id is not None:
        persona_info = get_persona_by_id(
            persona_id=query_request.persona_id,
            user=user,
            db_session=db_session,
            is_for_edit=False,
        )

    llm = get_llm_for_persona(persona=persona_info, user=user)

    llm_tokenizer = get_tokenizer(
        model_name=llm.config.model_name,
        provider_type=llm.config.model_provider,
    )

    max_history_tokens = int(
        llm.config.max_input_tokens * MAX_THREAD_CONTEXT_PERCENTAGE
    )

    combined_message = combine_message_thread(
        messages=query_request.messages,
        max_tokens=max_history_tokens,
        llm_tokenizer=llm_tokenizer,
    )

    # Also creates a new chat session
    # Origin is hardcoded to API since this endpoint is only accessible via API calls
    request = prepare_chat_message_request(
        message_text=combined_message,
        user=user,
        persona_id=query_request.persona_id,
        persona_override_config=query_request.persona_override_config,
        message_ts_to_respond_to=None,
        retrieval_details=query_request.retrieval_options,
        rerank_settings=query_request.rerank_settings,
        db_session=db_session,
        skip_gen_ai_answer_generation=query_request.skip_gen_ai_answer_generation,
        origin=MessageOrigin.API,
    )

    packets = stream_chat_message_objects(
        new_msg_req=request,
        user=user,
        db_session=db_session,
    )

    return packets


@basic_router.post("/answer-with-citation")
def get_answer_with_citation(
    request: OneShotQARequest,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> OneShotQAResponse:
    # Check and track non-streaming API usage limits
    if is_usage_limits_enabled():
        tenant_id = get_current_tenant_id()
        check_usage_and_raise(
            db_session=db_session,
            usage_type=UsageType.NON_STREAMING_API_CALLS,
            tenant_id=tenant_id,
            pending_amount=1,
        )
        increment_usage(
            db_session=db_session,
            usage_type=UsageType.NON_STREAMING_API_CALLS,
            amount=1,
        )
        db_session.commit()

    try:
        packets = get_answer_stream(request, user, db_session)
        answer = gather_stream(packets)

        if answer.error_msg:
            raise RuntimeError(answer.error_msg)

        return OneShotQAResponse(
            answer=answer.answer,
            chat_message_id=answer.message_id,
            error_msg=answer.error_msg,
            citations=answer.citation_info,
            docs=QADocsResponse(
                top_documents=answer.top_documents,
                predicted_flow=None,
                predicted_search=None,
                applied_source_filters=None,
                applied_time_cutoff=None,
                recency_bias_multiplier=0.0,
            ),
        )
    except Exception as e:
        logger.error(f"Error in get_answer_with_citation: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="An internal server error occurred")


@basic_router.post("/stream-answer-with-citation")
def stream_answer_with_citation(
    request: OneShotQARequest,
    db_session: Session = Depends(get_session),
    user: User | None = Depends(current_user),
) -> StreamingResponse:
    def stream_generator() -> Generator[str, None, None]:
        try:
            for packet in get_answer_stream(request, user, db_session):
                serialized = get_json_line(packet.model_dump())
                yield serialized
        except Exception as e:
            logger.exception("Error in answer streaming")
            yield json.dumps({"error": str(e)})

    return StreamingResponse(stream_generator(), media_type="application/json")


@admin_router.post("/search")
def admin_search(
    question: AdminSearchRequest,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> AdminSearchResponse:
    tenant_id = get_current_tenant_id()

    query = question.query
    logger.notice(f"Received admin search query: {query}")
    user_acl_filters = build_access_filters_for_user(user, db_session)

    final_filters = IndexFilters(
        source_type=question.filters.source_type,
        document_set=question.filters.document_set,
        time_cutoff=question.filters.time_cutoff,
        tags=question.filters.tags,
        access_control_list=user_acl_filters,
        tenant_id=tenant_id,
    )
    search_settings = get_current_search_settings(db_session)
    document_index = get_default_document_index(search_settings, None)

    if not isinstance(document_index, VespaIndex):
        raise HTTPException(
            status_code=400,
            detail="Cannot use admin-search when using a non-Vespa document index",
        )
    if not query or query.strip() == "":
        matching_chunks = document_index.random_retrieval(filters=final_filters)
    else:
        matching_chunks = document_index.admin_retrieval(
            query=query, filters=final_filters
        )

    documents = SearchDoc.from_chunks_or_sections(matching_chunks)

    # Deduplicate documents by id
    deduplicated_documents: list[SearchDoc] = []
    seen_documents: set[str] = set()
    for document in documents:
        if document.document_id not in seen_documents:
            deduplicated_documents.append(document)
            seen_documents.add(document.document_id)
    return AdminSearchResponse(documents=deduplicated_documents)


@basic_router.get("/valid-tags")
def get_tags(
    match_pattern: str | None = None,
    # If this is empty or None, then tags for all sources are considered
    sources: list[DocumentSource] | None = None,
    allow_prefix: bool = True,  # This is currently the only option
    limit: int = 50,
    _: User = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> TagResponse:
    if not allow_prefix:
        raise NotImplementedError("Cannot disable prefix match for now")

    key_prefix = match_pattern
    value_prefix = match_pattern
    require_both_to_match = False

    # split on = to allow the user to type in "author=bob"
    EQUAL_PAT = "="
    if match_pattern and EQUAL_PAT in match_pattern:
        split_pattern = match_pattern.split(EQUAL_PAT)
        key_prefix = split_pattern[0]
        value_prefix = EQUAL_PAT.join(split_pattern[1:])
        require_both_to_match = True

    db_tags = find_tags(
        tag_key_prefix=key_prefix,
        tag_value_prefix=value_prefix,
        sources=sources,
        limit=limit,
        db_session=db_session,
        require_both_to_match=require_both_to_match,
    )
    server_tags = [
        SourceTag(
            tag_key=db_tag.tag_key, tag_value=db_tag.tag_value, source=db_tag.source
        )
        for db_tag in db_tags
    ]
    return TagResponse(tags=server_tags)


@basic_router.get("/user-searches")
def get_user_search_sessions(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionsResponse:
    user_id = user.id if user is not None else None

    try:
        search_sessions = get_chat_sessions_by_user(
            user_id=user_id, deleted=False, db_session=db_session
        )
    except ValueError:
        raise HTTPException(
            status_code=404, detail="Chat session does not exist or has been deleted"
        )
    # Extract IDs from search sessions
    search_session_ids = [chat.id for chat in search_sessions]
    # Fetch first messages for each session, only including those with documents
    sessions_with_documents = get_valid_messages_from_query_sessions(
        search_session_ids, db_session
    )
    sessions_with_documents_dict = dict(sessions_with_documents)

    # Prepare response with detailed information for each valid search session
    response = ChatSessionsResponse(
        sessions=[
            ChatSessionDetails(
                id=search.id,
                name=sessions_with_documents_dict[search.id],
                persona_id=search.persona_id,
                time_created=search.time_created.isoformat(),
                time_updated=search.time_updated.isoformat(),
                shared_status=search.shared_status,
                current_alternate_model=search.current_alternate_model,
            )
            for search in search_sessions
            if search.id
            in sessions_with_documents_dict  # Only include sessions with documents
        ]
    )

    return response


@basic_router.get("/search-session/{session_id}")
def get_search_session(
    session_id: UUID,
    is_shared: bool = False,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SearchSessionDetailResponse:
    user_id = user.id if user is not None else None

    try:
        search_session = get_chat_session_by_id(
            chat_session_id=session_id,
            user_id=user_id,
            db_session=db_session,
            is_shared=is_shared,
        )
    except ValueError:
        raise ValueError("Search session does not exist or has been deleted")

    session_messages = get_chat_messages_by_session(
        chat_session_id=session_id,
        user_id=user_id,
        db_session=db_session,
        # we already did a permission check above with the call to
        # `get_chat_session_by_id`, so we can skip it here
        skip_permission_check=True,
        # we need the tool call objs anyways, so just fetch them in a single call
        prefetch_top_two_level_tool_calls=True,
    )
    docs_response: list[SearchDoc] = []
    for message in session_messages:
        if (
            message.message_type == MessageType.ASSISTANT
            or message.message_type == MessageType.SYSTEM
        ):
            docs = get_search_docs_for_chat_message(
                db_session=db_session, chat_message_id=message.id
            )
            for doc in docs:
                server_doc = translate_db_search_doc_to_saved_search_doc(doc)
                docs_response.append(server_doc)

    response = SearchSessionDetailResponse(
        search_session_id=session_id,
        description=search_session.description,
        documents=docs_response,
        messages=[
            translate_db_message_to_chat_message_detail(
                msg, remove_doc_content=is_shared  # if shared, don't leak doc content
            )
            for msg in session_messages
        ],
    )
    return response
