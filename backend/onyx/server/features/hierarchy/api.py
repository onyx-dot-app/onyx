from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.access.hierarchy_access import get_user_external_group_ids
from onyx.auth.users import current_user
from onyx.configs.app_configs import ENABLE_OPENSEARCH_INDEXING_FOR_ONYX
from onyx.configs.constants import DocumentSource
from onyx.db.document import get_accessible_documents_for_hierarchy_node_paginated
from onyx.db.engine.sql_engine import get_session
from onyx.db.hierarchy import get_accessible_hierarchy_nodes_for_source
from onyx.db.models import User
from onyx.db.opensearch_migration import get_opensearch_retrieval_state
from onyx.server.features.hierarchy.constants import DOCUMENT_PAGE_SIZE
from onyx.server.features.hierarchy.constants import HIERARCHY_NODE_DOCUMENTS_PATH
from onyx.server.features.hierarchy.constants import HIERARCHY_NODES_LIST_PATH
from onyx.server.features.hierarchy.constants import HIERARCHY_NODES_PREFIX
from onyx.server.features.hierarchy.models import DocumentPageCursor
from onyx.server.features.hierarchy.models import DocumentSortDirection
from onyx.server.features.hierarchy.models import DocumentSortField
from onyx.server.features.hierarchy.models import DocumentSummary
from onyx.server.features.hierarchy.models import HierarchyNodeDocumentsRequest
from onyx.server.features.hierarchy.models import HierarchyNodeDocumentsResponse
from onyx.server.features.hierarchy.models import HierarchyNodesResponse
from onyx.server.features.hierarchy.models import HierarchyNodeSummary

OPENSEARCH_NOT_ENABLED_MESSAGE = (
    "Per-source knowledge selection is coming soon in v3.0! "
    "OpenSearch indexing must be enabled to use this feature."
)

router = APIRouter(prefix=HIERARCHY_NODES_PREFIX)


def _require_opensearch(db_session: Session) -> None:
    if not ENABLE_OPENSEARCH_INDEXING_FOR_ONYX or not get_opensearch_retrieval_state(
        db_session
    ):
        raise HTTPException(
            status_code=403,
            detail=OPENSEARCH_NOT_ENABLED_MESSAGE,
        )


def _get_user_access_info(
    user: User | None, db_session: Session
) -> tuple[str | None, list[str]]:
    if not user:
        return None, []
    return user.email, get_user_external_group_ids(db_session, user)


@router.get(HIERARCHY_NODES_LIST_PATH)
def list_accessible_hierarchy_nodes(
    source: DocumentSource,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> HierarchyNodesResponse:
    _require_opensearch(db_session)
    user_email, external_group_ids = _get_user_access_info(user, db_session)
    nodes = get_accessible_hierarchy_nodes_for_source(
        db_session=db_session,
        source=source,
        user_email=user_email,
        external_group_ids=external_group_ids,
    )
    return HierarchyNodesResponse(
        nodes=[
            HierarchyNodeSummary(
                id=node.id,
                title=node.display_name,
                link=node.link,
                parent_id=node.parent_id,
            )
            for node in nodes
        ]
    )


@router.post(HIERARCHY_NODE_DOCUMENTS_PATH)
def list_accessible_hierarchy_node_documents(
    documents_request: HierarchyNodeDocumentsRequest,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> HierarchyNodeDocumentsResponse:
    _require_opensearch(db_session)
    user_email, external_group_ids = _get_user_access_info(user, db_session)
    cursor = documents_request.cursor
    sort_field = documents_request.sort_field
    sort_direction = documents_request.sort_direction

    sort_by_name = sort_field == DocumentSortField.NAME
    sort_ascending = sort_direction == DocumentSortDirection.ASC

    documents = get_accessible_documents_for_hierarchy_node_paginated(
        db_session=db_session,
        parent_hierarchy_node_id=documents_request.parent_hierarchy_node_id,
        user_email=user_email,
        external_group_ids=external_group_ids,
        limit=DOCUMENT_PAGE_SIZE + 1,
        sort_by_name=sort_by_name,
        sort_ascending=sort_ascending,
        cursor_last_modified=cursor.last_modified if cursor else None,
        cursor_last_synced=cursor.last_synced if cursor else None,
        cursor_name=cursor.name if cursor else None,
        cursor_document_id=cursor.document_id if cursor else None,
    )
    document_summaries = [
        DocumentSummary(
            id=document.id,
            title=document.semantic_id,
            link=document.link,
            parent_id=document.parent_hierarchy_node_id,
            last_modified=document.last_modified,
            last_synced=document.last_synced,
        )
        for document in documents[:DOCUMENT_PAGE_SIZE]
    ]
    next_cursor = None
    if len(documents) > DOCUMENT_PAGE_SIZE and document_summaries:
        last_document = document_summaries[-1]
        # For name sorting, we always have a title; for last_updated, we need last_modified
        can_create_cursor = sort_by_name or last_document.last_modified is not None
        if can_create_cursor:
            next_cursor = DocumentPageCursor.from_document(last_document, sort_field)
    return HierarchyNodeDocumentsResponse(
        documents=document_summaries,
        next_cursor=next_cursor,
        sort_field=sort_field,
        sort_direction=sort_direction,
        folder_position=documents_request.folder_position,
    )
