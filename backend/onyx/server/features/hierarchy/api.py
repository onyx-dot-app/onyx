from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.access.hierarchy_access import get_user_external_group_ids
from onyx.auth.users import current_user
from onyx.configs.constants import DocumentSource
from onyx.db.document import get_accessible_documents_for_hierarchy_node_paginated
from onyx.db.engine.sql_engine import get_session
from onyx.db.hierarchy import get_accessible_hierarchy_nodes_for_source
from onyx.db.models import User
from onyx.server.features.hierarchy.constants import DOCUMENT_PAGE_SIZE
from onyx.server.features.hierarchy.constants import HIERARCHY_NODE_DOCUMENTS_PATH
from onyx.server.features.hierarchy.constants import HIERARCHY_NODES_LIST_PATH
from onyx.server.features.hierarchy.constants import HIERARCHY_NODES_PREFIX
from onyx.server.features.hierarchy.models import DocumentPageCursor
from onyx.server.features.hierarchy.models import DocumentSummary
from onyx.server.features.hierarchy.models import HierarchyNodeDocumentsRequest
from onyx.server.features.hierarchy.models import HierarchyNodeDocumentsResponse
from onyx.server.features.hierarchy.models import HierarchyNodesResponse
from onyx.server.features.hierarchy.models import HierarchyNodeSummary


router = APIRouter(prefix=HIERARCHY_NODES_PREFIX)


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
    user_email, external_group_ids = _get_user_access_info(user, db_session)
    cursor = documents_request.cursor
    documents = get_accessible_documents_for_hierarchy_node_paginated(
        db_session=db_session,
        parent_hierarchy_node_id=documents_request.parent_hierarchy_node_id,
        user_email=user_email,
        external_group_ids=external_group_ids,
        cursor_last_modified=cursor.last_modified if cursor else None,
        cursor_last_synced=cursor.last_synced if cursor else None,
        cursor_document_id=cursor.document_id if cursor else None,
        limit=DOCUMENT_PAGE_SIZE + 1,
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
        if last_document.last_modified is not None:
            next_cursor = DocumentPageCursor.from_document(last_document)
    return HierarchyNodeDocumentsResponse(
        documents=document_summaries, next_cursor=next_cursor
    )
