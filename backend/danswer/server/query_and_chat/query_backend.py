from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from danswer.auth.users import current_curator_or_admin_user
from danswer.auth.users import current_user
from danswer.configs.constants import DocumentSource
from danswer.configs.constants import MessageType
from danswer.db.chat import get_chat_messages_by_session
from danswer.db.chat import get_chat_session_by_id
from danswer.db.chat import get_chat_sessions_by_user
from danswer.db.chat import get_first_messages_for_chat_sessions
from danswer.db.chat import get_search_docs_for_chat_message
from danswer.db.chat import translate_db_message_to_chat_message_detail
from danswer.db.chat import translate_db_search_doc_to_server_search_doc
from danswer.db.embedding_model import get_current_db_embedding_model
from danswer.db.engine import get_session
from danswer.db.models import User
from danswer.db.tag import get_tags_by_value_prefix_for_source_types
from danswer.document_index.factory import get_default_document_index
from danswer.document_index.vespa.index import VespaIndex
from danswer.one_shot_answer.answer_question import stream_search_answer
from danswer.one_shot_answer.models import DirectQARequest
from danswer.search.models import IndexFilters
from danswer.search.models import SearchDoc
from danswer.search.preprocessing.access_filters import build_access_filters_for_user
from danswer.search.utils import chunks_or_sections_to_search_docs
from danswer.secondary_llm_flows.query_validation import get_query_answerability
from danswer.secondary_llm_flows.query_validation import stream_query_answerability
from danswer.server.query_and_chat.models import AdminSearchRequest
from danswer.server.query_and_chat.models import AdminSearchResponse
from danswer.server.query_and_chat.models import ChatSessionDetails
from danswer.server.query_and_chat.models import ChatSessionsResponse
from danswer.server.query_and_chat.models import QueryValidationResponse
from danswer.server.query_and_chat.models import SearchSessionDetailResponse
from danswer.server.query_and_chat.models import SimpleQueryRequest
from danswer.server.query_and_chat.models import SourceTag
from danswer.server.query_and_chat.models import TagResponse
from danswer.server.query_and_chat.token_limit import check_token_rate_limits
from danswer.utils.logger import setup_logger

logger = setup_logger()

admin_router = APIRouter(prefix="/admin")
basic_router = APIRouter(prefix="/query")


@admin_router.post("/search")
def admin_search(
    question: AdminSearchRequest,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> AdminSearchResponse:
    query = question.query
    logger.notice(f"Received admin search query: {query}")
    user_acl_filters = build_access_filters_for_user(user, db_session)
    final_filters = IndexFilters(
        source_type=question.filters.source_type,
        document_set=question.filters.document_set,
        time_cutoff=question.filters.time_cutoff,
        tags=question.filters.tags,
        access_control_list=user_acl_filters,
    )
    embedding_model = get_current_db_embedding_model(db_session)
    document_index = get_default_document_index(
        primary_index_name=embedding_model.index_name, secondary_index_name=None
    )
    if not isinstance(document_index, VespaIndex):
        raise HTTPException(
            status_code=400,
            detail="Cannot use admin-search when using a non-Vespa document index",
        )
    matching_chunks = document_index.admin_retrieval(query=query, filters=final_filters)

    documents = chunks_or_sections_to_search_docs(matching_chunks)

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

    db_tags = get_tags_by_value_prefix_for_source_types(
        tag_key_prefix=match_pattern,
        tag_value_prefix=match_pattern,
        sources=sources,
        limit=limit,
        db_session=db_session,
    )
    server_tags = [
        SourceTag(
            tag_key=db_tag.tag_key, tag_value=db_tag.tag_value, source=db_tag.source
        )
        for db_tag in db_tags
    ]
    return TagResponse(tags=server_tags)


@basic_router.post("/query-validation")
def query_validation(
    simple_query: SimpleQueryRequest, _: User = Depends(current_user)
) -> QueryValidationResponse:
    # Note if weak model prompt is chosen, this check does not occur and will simply return that
    # the query is valid, this is because weaker models cannot really handle this task well.
    # Additionally, some weak model servers cannot handle concurrent inferences.
    logger.notice(f"Validating query: {simple_query.query}")
    reasoning, answerable = get_query_answerability(simple_query.query)
    return QueryValidationResponse(reasoning=reasoning, answerable=answerable)


@basic_router.get("/user-searches")
def get_user_search_sessions(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> ChatSessionsResponse:
    user_id = user.id if user is not None else None

    try:
        search_sessions = get_chat_sessions_by_user(
            user_id=user_id, deleted=False, db_session=db_session, only_one_shot=True
        )
    except ValueError:
        raise HTTPException(
            status_code=404, detail="Chat session does not exist or has been deleted"
        )

    search_session_ids = [chat.id for chat in search_sessions]
    first_messages = get_first_messages_for_chat_sessions(
        search_session_ids, db_session
    )
    first_messages_dict = dict(first_messages)

    response = ChatSessionsResponse(
        sessions=[
            ChatSessionDetails(
                id=search.id,
                name=first_messages_dict.get(search.id, search.description),
                persona_id=search.persona_id,
                time_created=search.time_created.isoformat(),
                shared_status=search.shared_status,
                folder_id=search.folder_id,
                current_alternate_model=search.current_alternate_model,
            )
            for search in search_sessions
        ]
    )
    return response


@basic_router.get("/search-session/{session_id}")
def get_search_session(
    session_id: int,
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
        prefetch_tool_calls=True,
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
                server_doc = translate_db_search_doc_to_server_search_doc(doc)
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


# NOTE No longer used, after search/chat redesign.
# No search responses are answered with a conversational generative AI response
@basic_router.post("/stream-query-validation")
def stream_query_validation(
    simple_query: SimpleQueryRequest, _: User = Depends(current_user)
) -> StreamingResponse:
    # Note if weak model prompt is chosen, this check does not occur and will simply return that
    # the query is valid, this is because weaker models cannot really handle this task well.
    # Additionally, some weak model servers cannot handle concurrent inferences.
    logger.notice(f"Validating query: {simple_query.query}")
    return StreamingResponse(
        stream_query_answerability(simple_query.query), media_type="application/json"
    )


@basic_router.post("/stream-answer-with-quote")
def get_answer_with_quote(
    query_request: DirectQARequest,
    user: User = Depends(current_user),
    _: None = Depends(check_token_rate_limits),
) -> StreamingResponse:
    query = query_request.messages[0].message

    logger.notice(f"Received query for one shot answer with quotes: {query}")

    packets = stream_search_answer(
        query_req=query_request,
        user=user,
        max_document_tokens=None,
        max_history_tokens=0,
    )
    return StreamingResponse(packets, media_type="application/json")
