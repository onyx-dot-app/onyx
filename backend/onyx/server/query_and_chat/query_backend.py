from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.auth.users import current_curator_or_admin_user
from onyx.auth.users import current_user
from onyx.configs.constants import DocumentSource
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import SearchDoc
from onyx.context.search.preprocessing.access_filters import (
    build_access_filters_for_user,
)
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.search_settings import get_current_search_settings
from onyx.db.tag import find_tags
from onyx.document_index.factory import get_default_document_index
from onyx.document_index.vespa.index import VespaIndex
from onyx.server.query_and_chat.models import AdminSearchRequest
from onyx.server.query_and_chat.models import AdminSearchResponse
from onyx.server.query_and_chat.models import SourceTag
from onyx.server.query_and_chat.models import TagResponse
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

admin_router = APIRouter(prefix="/admin")
basic_router = APIRouter(prefix="/query")


@admin_router.post("/search")
def admin_search(
    question: AdminSearchRequest,
    user: User = Depends(current_curator_or_admin_user),
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
    # This flow is for search so we do not get all indices.
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
