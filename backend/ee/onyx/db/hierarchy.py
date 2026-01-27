"""EE version of hierarchy node access control.

This module provides permission-aware hierarchy node access for Enterprise Edition.
It filters hierarchy nodes based on user email and external group membership.
"""

from sqlalchemy import any_
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from onyx.configs.constants import DocumentSource
from onyx.db.models import HierarchyNode


def _build_hierarchy_access_filter(
    user_email: str | None,
    external_group_ids: list[str],
) -> ColumnElement[bool]:
    """Build SQLAlchemy filter for hierarchy node access.

    A user can access a hierarchy node if any of the following are true:
    - The node is marked as public (is_public=True)
    - The user's email is in the node's external_user_emails list
    - Any of the user's external group IDs overlap with the node's external_user_group_ids
    """
    access_filters: list[ColumnElement[bool]] = [HierarchyNode.is_public.is_(True)]
    if user_email:
        access_filters.append(any_(HierarchyNode.external_user_emails) == user_email)
    if external_group_ids:
        access_filters.append(
            HierarchyNode.external_user_group_ids.overlap(
                postgresql.array(external_group_ids)
            )
        )
    return or_(*access_filters)


def _get_accessible_hierarchy_nodes_for_source(
    db_session: Session,
    source: DocumentSource,
    user_email: str | None,
    external_group_ids: list[str],
) -> list[HierarchyNode]:
    """
    EE version: Returns hierarchy nodes filtered by user permissions.

    A user can access a hierarchy node if any of the following are true:
    - The node is marked as public (is_public=True)
    - The user's email is in the node's external_user_emails list
    - Any of the user's external group IDs overlap with the node's external_user_group_ids

    Args:
        db_session: SQLAlchemy session
        source: Document source type
        user_email: User's email for permission checking
        external_group_ids: User's external group IDs for permission checking

    Returns:
        List of HierarchyNode objects the user has access to
    """
    stmt = select(HierarchyNode).where(HierarchyNode.source == source)
    stmt = stmt.where(_build_hierarchy_access_filter(user_email, external_group_ids))
    stmt = stmt.order_by(HierarchyNode.display_name)
    return list(db_session.execute(stmt).scalars().all())
