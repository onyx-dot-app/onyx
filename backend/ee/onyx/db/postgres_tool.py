"""EE version of the Postgres tool access filters.

Only the hierarchy-node access filter differs between editions: MIT has no
permission sync, so its version filters nothing. Document ACL filtering is
unversioned (`onyx.db.document_access`) and chat-history scoping is
ownership-based, so neither needs an EE override.
"""

from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from ee.onyx.db.hierarchy import build_hierarchy_access_filter


def _hierarchy_node_access_filter(
    db_session: Session,
    user_email: str | None,
    external_group_ids: list[str],
    user_id: UUID | None,
) -> ColumnElement[bool]:
    """EE version: SOURCE-root nodes, node ACL matches, and connector-level access."""
    return build_hierarchy_access_filter(
        db_session, user_email or "", external_group_ids, user_id
    )
