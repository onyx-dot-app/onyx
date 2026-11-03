from collections.abc import Sequence

from sqlalchemy import exists
from sqlalchemy import select
from sqlalchemy import tuple_
from sqlalchemy.orm import Session

from onyx.access.hierarchy_access import get_user_external_group_ids
from onyx.configs.constants import DocumentSource
from onyx.db.connector import fetch_canvas_cc_pair_for_lti_course
from onyx.db.connector import fetch_lti_course_google_drive_cc_pairs
from onyx.db.connector import fetch_lti_course_website_cc_pairs
from onyx.db.document import get_accessible_documents_for_hierarchy_node_paginated
from onyx.db.document import get_lti_course_website_document_ids
from onyx.db.document import (
    get_lti_course_website_documents_for_hierarchy_node_paginated,
)
from onyx.db.document_access import apply_document_access_filter
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.hierarchy import get_accessible_hierarchy_nodes_for_source
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import HierarchyNode
from onyx.db.models import HierarchyNodeByConnectorCredentialPair
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.hierarchy.constants import DOCUMENT_PAGE_SIZE
from onyx.server.features.hierarchy.models import DocumentPageCursor
from onyx.server.features.hierarchy.models import DocumentSortDirection
from onyx.server.features.hierarchy.models import DocumentSortField
from onyx.server.lti.models import LtiCourseKnowledgeScope

LTI_COURSE_KNOWLEDGE_SOURCES = {
    DocumentSource.CANVAS,
    DocumentSource.GOOGLE_DRIVE,
    DocumentSource.WEB,
}


def _cc_pair_keys(
    cc_pairs: Sequence[ConnectorCredentialPair],
) -> list[tuple[int, int]]:
    return [(cc_pair.connector_id, cc_pair.credential_id) for cc_pair in cc_pairs]


def _course_cc_pairs(
    db_session: Session,
    course_id: str,
    source: DocumentSource,
) -> list[ConnectorCredentialPair]:
    if source == DocumentSource.CANVAS:
        cc_pair = fetch_canvas_cc_pair_for_lti_course(
            db_session=db_session,
            lti_context_id=course_id,
        )
        return [cc_pair] if cc_pair is not None else []

    if source == DocumentSource.GOOGLE_DRIVE:
        return fetch_lti_course_google_drive_cc_pairs(
            db_session=db_session,
            lti_context_id=course_id,
        )

    if source == DocumentSource.WEB:
        return [
            cc_pair
            for cc_pair in fetch_lti_course_website_cc_pairs(
                db_session=db_session,
                lti_context_id=course_id,
            )
            if cc_pair.status != ConnectorCredentialPairStatus.DELETING
        ]

    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        f"{source.value} is not supported for LTI course tutor knowledge",
    )


def _owned_hierarchy_node_ids(
    db_session: Session,
    cc_pair_keys: list[tuple[int, int]],
) -> set[int]:
    if not cc_pair_keys:
        return set()

    stmt = select(HierarchyNodeByConnectorCredentialPair.hierarchy_node_id).where(
        tuple_(
            HierarchyNodeByConnectorCredentialPair.connector_id,
            HierarchyNodeByConnectorCredentialPair.credential_id,
        ).in_(cc_pair_keys)
    )
    return set(db_session.execute(stmt).scalars().all())


def _accessible_hierarchy_node_ids(
    db_session: Session,
    source: DocumentSource,
    user_email: str,
    external_group_ids: list[str],
) -> set[int]:
    return {
        node.id
        for node in get_accessible_hierarchy_nodes_for_source(
            db_session=db_session,
            source=source,
            user_email=user_email,
            external_group_ids=external_group_ids,
        )
    }


def get_lti_course_knowledge_scope(
    db_session: Session,
    course_id: str,
    source: DocumentSource,
    user_email: str,
    external_group_ids: list[str],
) -> LtiCourseKnowledgeScope:
    cc_pair_keys = _cc_pair_keys(_course_cc_pairs(db_session, course_id, source))
    owned_node_ids = _owned_hierarchy_node_ids(db_session, cc_pair_keys)
    if source == DocumentSource.WEB:
        # The course's private connector group is an internal Onyx group, while
        # the generic hierarchy filter only understands source-level external
        # permissions. The LTI launch and course cc-pairs provide this scope.
        return LtiCourseKnowledgeScope(
            cc_pair_keys=cc_pair_keys,
            accessible_node_ids=owned_node_ids,
        )

    accessible_node_ids = _accessible_hierarchy_node_ids(
        db_session=db_session,
        source=source,
        user_email=user_email,
        external_group_ids=external_group_ids,
    )
    return LtiCourseKnowledgeScope(
        cc_pair_keys=cc_pair_keys,
        accessible_node_ids=owned_node_ids & accessible_node_ids,
    )


def get_lti_course_accessible_hierarchy_nodes(
    db_session: Session,
    course_id: str,
    source: DocumentSource,
    user_email: str,
    external_group_ids: list[str],
) -> list[HierarchyNode]:
    scope = get_lti_course_knowledge_scope(
        db_session=db_session,
        course_id=course_id,
        source=source,
        user_email=user_email,
        external_group_ids=external_group_ids,
    )
    if not scope.accessible_node_ids:
        return []

    stmt = (
        select(HierarchyNode)
        .where(HierarchyNode.id.in_(scope.accessible_node_ids))
        .order_by(HierarchyNode.display_name)
    )
    return list(db_session.execute(stmt).scalars().all())


def get_lti_course_accessible_documents_for_hierarchy_node(
    db_session: Session,
    course_id: str,
    parent_hierarchy_node_id: int,
    user_email: str,
    external_group_ids: list[str],
    cursor: DocumentPageCursor | None,
    sort_field: DocumentSortField,
    sort_direction: DocumentSortDirection,
) -> list[Document]:
    parent_node = db_session.get(HierarchyNode, parent_hierarchy_node_id)
    if parent_node is None or parent_node.source not in LTI_COURSE_KNOWLEDGE_SOURCES:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "No course knowledge folder found with that id",
        )

    scope = get_lti_course_knowledge_scope(
        db_session=db_session,
        course_id=course_id,
        source=parent_node.source,
        user_email=user_email,
        external_group_ids=external_group_ids,
    )
    if parent_hierarchy_node_id not in scope.accessible_node_ids:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "No course knowledge folder found with that id",
        )

    if parent_node.source == DocumentSource.WEB:
        return get_lti_course_website_documents_for_hierarchy_node_paginated(
            db_session=db_session,
            parent_hierarchy_node_id=parent_hierarchy_node_id,
            connector_credential_pairs=scope.cc_pair_keys,
            limit=DOCUMENT_PAGE_SIZE + 1,
            sort_by_name=sort_field == DocumentSortField.NAME,
            sort_ascending=sort_direction == DocumentSortDirection.ASC,
            cursor_last_modified=cursor.last_modified if cursor else None,
            cursor_last_synced=cursor.last_synced if cursor else None,
            cursor_name=cursor.name if cursor else None,
            cursor_document_id=cursor.document_id if cursor else None,
        )

    return get_accessible_documents_for_hierarchy_node_paginated(
        db_session=db_session,
        parent_hierarchy_node_id=parent_hierarchy_node_id,
        user_email=user_email,
        external_group_ids=external_group_ids,
        connector_credential_pairs=scope.cc_pair_keys,
        limit=DOCUMENT_PAGE_SIZE + 1,
        sort_by_name=sort_field == DocumentSortField.NAME,
        sort_ascending=sort_direction == DocumentSortDirection.ASC,
        cursor_last_modified=cursor.last_modified if cursor else None,
        cursor_last_synced=cursor.last_synced if cursor else None,
        cursor_name=cursor.name if cursor else None,
        cursor_document_id=cursor.document_id if cursor else None,
    )


def _all_lti_course_knowledge_scope(
    db_session: Session,
    course_id: str,
    user: User,
) -> LtiCourseKnowledgeScope:
    external_group_ids = get_user_external_group_ids(db_session, user)
    all_cc_pair_keys: list[tuple[int, int]] = []
    all_accessible_node_ids: set[int] = set()

    for source in LTI_COURSE_KNOWLEDGE_SOURCES:
        scope = get_lti_course_knowledge_scope(
            db_session=db_session,
            course_id=course_id,
            source=source,
            user_email=user.email,
            external_group_ids=external_group_ids,
        )
        all_cc_pair_keys.extend(scope.cc_pair_keys)
        all_accessible_node_ids.update(scope.accessible_node_ids)

    return LtiCourseKnowledgeScope(
        cc_pair_keys=all_cc_pair_keys,
        accessible_node_ids=all_accessible_node_ids,
    )


def validate_lti_course_knowledge_scope(
    db_session: Session,
    course_id: str,
    user: User,
    hierarchy_node_ids: list[int],
    document_ids: list[str],
) -> None:
    if not hierarchy_node_ids and not document_ids:
        return

    scope = _all_lti_course_knowledge_scope(
        db_session=db_session,
        course_id=course_id,
        user=user,
    )

    invalid_hierarchy_node_ids = set(hierarchy_node_ids) - scope.accessible_node_ids
    if invalid_hierarchy_node_ids:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Tutor knowledge includes folders outside this Canvas course",
        )

    if not document_ids:
        return

    if not scope.cc_pair_keys or not scope.accessible_node_ids:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Tutor knowledge includes documents outside this Canvas course",
        )

    external_group_ids = get_user_external_group_ids(db_session, user)
    web_scope = get_lti_course_knowledge_scope(
        db_session=db_session,
        course_id=course_id,
        source=DocumentSource.WEB,
        user_email=user.email,
        external_group_ids=external_group_ids,
    )
    allowed_web_document_ids = get_lti_course_website_document_ids(
        db_session=db_session,
        document_ids=document_ids,
        hierarchy_node_ids=web_scope.accessible_node_ids,
        connector_credential_pairs=web_scope.cc_pair_keys,
    )
    remaining_document_ids = set(document_ids) - allowed_web_document_ids
    if not remaining_document_ids:
        return

    stmt = select(Document.id).where(
        Document.id.in_(remaining_document_ids),
        Document.parent_hierarchy_node_id.in_(
            scope.accessible_node_ids - web_scope.accessible_node_ids
        ),
        exists()
        .where(DocumentByConnectorCredentialPair.id == Document.id)
        .where(
            tuple_(
                DocumentByConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id,
            ).in_(scope.cc_pair_keys)
        )
        .correlate(Document),
    )
    stmt = apply_document_access_filter(
        stmt,
        user.email,
        external_group_ids,
    )
    allowed_document_ids = set(db_session.execute(stmt).scalars().all())
    if remaining_document_ids - allowed_document_ids:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Tutor knowledge includes documents outside this Canvas course",
        )
