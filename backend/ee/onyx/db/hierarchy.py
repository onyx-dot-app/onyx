"""EE hierarchy access control for source and connector permissions."""

from uuid import UUID

from sqlalchemy import String, and_, any_, cast, or_, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.configs.constants import DocumentSource
from onyx.db.enums import (
    AccessType,
    ConnectorCredentialPairStatus,
    HierarchyNodeType,
)
from onyx.db.hierarchy import HIERARCHY_NODE_SEARCH_LIMIT, escape_like_pattern
from onyx.db.models import (
    ConnectorCredentialPair,
    Credential,
    HierarchyNode,
    HierarchyNodeByConnectorCredentialPair,
    User__UserGroup,
    UserGroup__ConnectorCredentialPair,
)


def _build_connector_access_filter(user_id: UUID) -> ColumnElement[bool]:
    """Grant the connector-level access applied to indexed documents."""
    node_cc_pair = HierarchyNodeByConnectorCredentialPair
    cc_pair = ConnectorCredentialPair
    group_cc_pair = UserGroup__ConnectorCredentialPair
    user_group = User__UserGroup

    stmt = (
        select(1)
        .select_from(node_cc_pair)
        .join(
            cc_pair,
            and_(
                cc_pair.connector_id == node_cc_pair.connector_id,
                cc_pair.credential_id == node_cc_pair.credential_id,
            ),
        )
        .join(Credential, Credential.id == cc_pair.credential_id)
        .outerjoin(
            group_cc_pair,
            and_(
                group_cc_pair.cc_pair_id == cc_pair.id,
                group_cc_pair.is_current.is_(True),
            ),
        )
        .outerjoin(
            user_group,
            and_(
                user_group.user_group_id == group_cc_pair.user_group_id,
                user_group.user_id == user_id,
            ),
        )
        .where(
            node_cc_pair.hierarchy_node_id == HierarchyNode.id,
            cc_pair.status != ConnectorCredentialPairStatus.DELETING,
            or_(
                cc_pair.access_type == AccessType.PUBLIC,
                and_(
                    cc_pair.access_type != AccessType.SYNC,
                    or_(
                        Credential.user_id == user_id,
                        user_group.user_id == user_id,
                    ),
                ),
            ),
        )
    )
    return stmt.exists()


def _build_hierarchy_access_filter(
    user_email: str,
    external_group_ids: list[str],
    user_id: UUID | None = None,
) -> ColumnElement[bool]:
    """Grant access through the node ACL or an associated connector."""
    access_filters: list[ColumnElement[bool]] = [
        HierarchyNode.node_type == HierarchyNodeType.SOURCE,
        HierarchyNode.is_public.is_(True),
    ]
    if user_email:
        access_filters.append(any_(HierarchyNode.external_user_emails) == user_email)
    if external_group_ids:
        access_filters.append(
            HierarchyNode.external_user_group_ids.overlap(
                cast(postgresql.array(external_group_ids), postgresql.ARRAY(String))
            )
        )
    if user_id:
        access_filters.append(_build_connector_access_filter(user_id))
    return or_(*access_filters)


def _get_accessible_hierarchy_nodes_for_source(
    db_session: Session,
    source: DocumentSource,
    user_email: str,
    external_group_ids: list[str],
    user_id: UUID | None = None,
) -> list[HierarchyNode]:
    """EE version: hierarchy nodes the user can access, always including the SOURCE root."""
    stmt = select(HierarchyNode).where(
        HierarchyNode.source == source,
        HierarchyNode.node_type != HierarchyNodeType.STUB,
    )
    stmt = stmt.where(
        _build_hierarchy_access_filter(user_email, external_group_ids, user_id)
    )
    stmt = stmt.order_by(HierarchyNode.display_name)
    return list(db_session.execute(stmt).scalars().all())


def _search_accessible_hierarchy_nodes(
    db_session: Session,
    query: str,
    sources: list[DocumentSource] | None,
    user_email: str,
    external_group_ids: list[str],
    limit: int = HIERARCHY_NODE_SEARCH_LIMIT,
    user_id: UUID | None = None,
) -> list[HierarchyNode]:
    """EE version: ACL-filtered case-insensitive display_name search."""
    pattern = f"%{escape_like_pattern(query)}%"
    stmt = (
        select(HierarchyNode)
        .where(
            HierarchyNode.node_type.notin_(
                [HierarchyNodeType.STUB, HierarchyNodeType.SOURCE]
            ),
            HierarchyNode.display_name.ilike(pattern, escape="\\"),
            _build_hierarchy_access_filter(user_email, external_group_ids, user_id),
        )
        .order_by(HierarchyNode.display_name)
        .limit(limit)
    )
    if sources:
        stmt = stmt.where(HierarchyNode.source.in_(sources))
    return list(db_session.execute(stmt).scalars().all())


def _filter_accessible_hierarchy_node_ids(
    db_session: Session,
    node_ids: list[int],
    user_email: str,
    external_group_ids: list[str],
    user_id: UUID | None = None,
) -> set[int]:
    """EE version: keep only the node ids the user can access."""
    stmt = select(HierarchyNode.id).where(HierarchyNode.id.in_(node_ids))
    stmt = stmt.where(
        _build_hierarchy_access_filter(user_email, external_group_ids, user_id)
    )
    return set(db_session.execute(stmt).scalars().all())
