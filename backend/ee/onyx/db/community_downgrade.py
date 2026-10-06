"""Database changes for dropping a self-hosted deployment to the Community tier."""

from sqlalchemy import delete, null, or_, select, update
from sqlalchemy.orm import Session

from onyx.db.document import mark_cc_pair_documents_for_sync__no_commit
from onyx.db.enums import AccessType
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    HierarchyNode,
    PublicExternalUserGroup,
    User__ExternalUserGroupId,
    UserGroup__CCPairDataAccess,
)


def make_all_cc_pairs_public__no_commit(db_session: Session) -> list[int]:
    """Community has only public connectors, so every other pair becomes one and
    the permissions synced from its source stop applying. Returns the ids of the
    pairs that changed.

    The index keeps the old chunk ACLs until metadata sync has rewritten the
    documents this marks."""
    # Id order and a key-share lock, like every other locker of these rows: no
    # deadlock with them, and inserts that reference a pair are not blocked.
    cc_pair_ids = list(
        db_session.scalars(
            select(ConnectorCredentialPair.id)
            .where(ConnectorCredentialPair.access_type != AccessType.PUBLIC)
            .order_by(ConnectorCredentialPair.id)
            .with_for_update(key_share=True)
        )
    )
    if cc_pair_ids:
        db_session.execute(
            update(ConnectorCredentialPair)
            .where(ConnectorCredentialPair.id.in_(cc_pair_ids))
            .values(
                access_type=AccessType.PUBLIC,
                # null(): a plain None would store a JSON null in the JSONB column.
                auto_sync_options=null(),
                last_time_perm_sync=None,
                last_time_external_group_sync=None,
            )
        )
        mark_cc_pair_documents_for_sync__no_commit(db_session, cc_pair_ids)

    # Not scoped to the changed pairs: with every pair public, nothing may keep a
    # data-access group or a synced permission, whichever pair wrote it. A sync
    # already in flight can still write some back, which grants nothing on a public pair.
    db_session.execute(delete(UserGroup__CCPairDataAccess))
    db_session.execute(delete(User__ExternalUserGroupId))
    db_session.execute(delete(PublicExternalUserGroup))
    db_session.execute(
        update(Document)
        .where(
            or_(
                Document.external_user_emails.is_not(None),
                Document.external_user_group_ids.is_not(None),
                Document.is_public.is_(True),
            )
        )
        .values(
            external_user_emails=None,
            external_user_group_ids=None,
            is_public=False,
        )
    )
    # is_public stays: a node is readable through its now-public pair, and the
    # next indexing run of a public pair sets it.
    db_session.execute(
        update(HierarchyNode)
        .where(
            or_(
                HierarchyNode.external_user_emails.is_not(None),
                HierarchyNode.external_user_group_ids.is_not(None),
            )
        )
        .values(external_user_emails=None, external_user_group_ids=None)
    )
    return cc_pair_ids
