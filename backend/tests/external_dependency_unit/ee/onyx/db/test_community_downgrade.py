"""A downgrade to Community makes every connector public and drops the
permissions synced from the sources. Each test rolls its transaction back."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ee.onyx.access.access import _get_access_for_documents
from ee.onyx.db.community_downgrade import make_all_cc_pairs_public__no_commit
from onyx.configs.constants import DocumentSource
from onyx.db.connector_credential_pair import has_perm_synced_cc_pairs
from onyx.db.enums import AccessType, HierarchyNodeType
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    DocumentByConnectorCredentialPair,
    HierarchyNode,
    PublicExternalUserGroup,
    User,
    User__ExternalUserGroupId,
    UserGroup,
    UserGroup__CCPairDataAccess,
)
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

_SYNCED_EMAIL = "reader@example.com"
_SYNCED_GROUP = "mock_connector_readers"
_OLD = datetime.now(timezone.utc) - timedelta(days=1)


def _make_pair_with_doc(
    db_session: Session, access_type: AccessType
) -> tuple[ConnectorCredentialPair, str]:
    """A pair of the given access type with one indexed document that was last
    modified and synced a day ago."""
    pair = make_cc_pair(db_session, commit=False)
    pair.access_type = access_type
    doc_id = f"downgrade-{uuid4().hex[:8]}"
    db_session.add(
        Document(
            id=doc_id,
            semantic_id=doc_id,
            chunk_count=1,
            last_modified=_OLD,
            last_synced=_OLD,
        )
    )
    db_session.flush()
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=doc_id,
            connector_id=pair.connector_id,
            credential_id=pair.credential_id,
            has_been_indexed=True,
        )
    )
    db_session.flush()
    return pair, doc_id


def _get_doc(db_session: Session, doc_id: str) -> Document:
    db_session.expire_all()
    return db_session.scalars(select(Document).where(Document.id == doc_id)).one()


@pytest.mark.parametrize("access_type", [AccessType.SYNC, AccessType.SYNC_RESTRICTED])
@pytest.mark.usefixtures("tenant_context")
def test_perm_synced_pair_becomes_public(
    db_session: Session, access_type: AccessType
) -> None:
    try:
        pair, doc_id = _make_pair_with_doc(db_session, access_type)
        pair.auto_sync_options = {"customer_id": "123"}
        pair.last_time_perm_sync = _OLD
        pair.last_time_external_group_sync = _OLD
        # _get_doc expires the session, which would drop these unsaved values.
        db_session.flush()
        doc = _get_doc(db_session, doc_id)
        doc.external_user_emails = [_SYNCED_EMAIL]
        doc.external_user_group_ids = [_SYNCED_GROUP]
        doc.is_public = True
        node = HierarchyNode(
            raw_node_id=f"downgrade-{uuid4().hex[:8]}",
            display_name="Restricted folder",
            source=DocumentSource.MOCK_CONNECTOR,
            node_type=HierarchyNodeType.FOLDER,
            external_user_emails=[_SYNCED_EMAIL],
            external_user_group_ids=[_SYNCED_GROUP],
        )
        db_session.add(node)
        user = User(
            id=uuid4(),
            email=f"downgrade-{uuid4().hex[:8]}@example.com",
            hashed_password="unused",
            is_active=True,
            is_superuser=False,
            is_verified=True,
        )
        db_session.add(user)
        db_session.flush()
        db_session.add_all(
            [
                User__ExternalUserGroupId(
                    user_id=user.id,
                    external_user_group_id=_SYNCED_GROUP,
                    cc_pair_id=pair.id,
                ),
                PublicExternalUserGroup(
                    external_user_group_id=f"public-{uuid4().hex[:8]}",
                    cc_pair_id=pair.id,
                ),
            ]
        )
        db_session.flush()
        pair_id = pair.id
        assert has_perm_synced_cc_pairs(db_session)

        changed_ids = make_all_cc_pairs_public__no_commit(db_session)

        assert pair_id in changed_ids
        db_session.refresh(pair)
        assert pair.access_type == AccessType.PUBLIC
        assert pair.last_time_perm_sync is None
        assert pair.last_time_external_group_sync is None
        # SQL NULL, not a JSON null.
        assert db_session.scalar(
            select(ConnectorCredentialPair.auto_sync_options.is_(None)).where(
                ConnectorCredentialPair.id == pair_id
            )
        )
        assert not has_perm_synced_cc_pairs(db_session)

        doc = _get_doc(db_session, doc_id)
        assert doc.external_user_emails is None
        assert doc.external_user_group_ids is None
        assert doc.is_public is False
        db_session.refresh(node)
        assert node.external_user_emails is None
        assert node.external_user_group_ids is None
        # Newer than last_synced, so metadata sync rewrites the chunk ACL.
        assert doc.last_modified is not None and doc.last_modified > _OLD

        access = _get_access_for_documents([doc_id], db_session)[doc_id]
        assert access.is_public
        assert not access.external_user_emails
        assert not access.external_user_group_ids

        assert not db_session.scalars(
            select(User__ExternalUserGroupId).where(
                User__ExternalUserGroupId.cc_pair_id == pair_id
            )
        ).all()
        assert not db_session.scalars(
            select(PublicExternalUserGroup).where(
                PublicExternalUserGroup.cc_pair_id == pair_id
            )
        ).all()
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
def test_private_pair_loses_its_data_access_groups(db_session: Session) -> None:
    try:
        pair, doc_id = _make_pair_with_doc(db_session, AccessType.PRIVATE)
        group = UserGroup(name=f"downgrade-{uuid4().hex[:8]}")
        db_session.add(group)
        db_session.flush()
        db_session.add(
            UserGroup__CCPairDataAccess(user_group_id=group.id, cc_pair_id=pair.id)
        )
        db_session.flush()

        make_all_cc_pairs_public__no_commit(db_session)

        db_session.refresh(pair)
        assert pair.access_type == AccessType.PUBLIC
        assert not db_session.scalars(
            select(UserGroup__CCPairDataAccess).where(
                UserGroup__CCPairDataAccess.cc_pair_id == pair.id
            )
        ).all()
        access = _get_access_for_documents([doc_id], db_session)[doc_id]
        assert access.is_public
        assert not access.user_groups
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
def test_public_pair_loses_stale_permissions_without_a_resync(
    db_session: Session,
) -> None:
    try:
        pair, doc_id = _make_pair_with_doc(db_session, AccessType.PUBLIC)
        _get_doc(db_session, doc_id).external_user_emails = [_SYNCED_EMAIL]
        db_session.flush()

        changed_ids = make_all_cc_pairs_public__no_commit(db_session)

        assert pair.id not in changed_ids
        doc = _get_doc(db_session, doc_id)
        assert doc.external_user_emails is None
        # The document is public either way, so its chunk ACL needs no rewrite.
        assert doc.last_modified == _OLD
    finally:
        db_session.rollback()
