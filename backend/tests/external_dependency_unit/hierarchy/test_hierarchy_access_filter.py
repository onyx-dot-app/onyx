"""Tests hierarchy node and document visibility through connector permissions."""

from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from ee.onyx.db.hierarchy import _get_accessible_hierarchy_nodes_for_source
from onyx.configs.constants import DocumentSource
from onyx.db.document import get_accessible_documents_for_hierarchy_node_paginated
from onyx.db.enums import AccessType, AccountType, HierarchyNodeType
from onyx.db.hierarchy import get_source_hierarchy_node
from onyx.db.models import (
    Credential,
    Document,
    DocumentByConnectorCredentialPair,
    HierarchyNode,
    HierarchyNodeByConnectorCredentialPair,
    User__UserGroup,
    UserGroup,
    UserGroup__ConnectorCredentialPair,
)
from onyx.kg.models import KGStage
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


class ConnectorAccessSeed(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    node: HierarchyNode
    document_id: str
    owner_id: UUID
    owner_email: str
    member_id: UUID
    member_email: str
    outsider_id: UUID
    outsider_email: str


class UserSeed(BaseModel):
    id: UUID
    email: str
    hashed_password: str
    is_active: bool
    is_superuser: bool
    is_verified: bool
    account_type: AccountType


def _make_node(
    raw_node_id: str,
    display_name: str,
    *,
    is_public: bool = False,
    external_user_emails: list[str] | None = None,
    external_user_group_ids: list[str] | None = None,
) -> HierarchyNode:
    return HierarchyNode(
        raw_node_id=raw_node_id,
        display_name=display_name,
        source=DocumentSource.GOOGLE_DRIVE,
        node_type=HierarchyNodeType.FOLDER,
        is_public=is_public,
        external_user_emails=external_user_emails,
        external_user_group_ids=external_user_group_ids,
    )


@pytest.fixture()
def seeded_nodes(db_session: Session) -> Generator[list[HierarchyNode], None, None]:
    """Seed nodes covering external ACL variants."""
    tag = uuid4().hex[:8]
    nodes = [
        _make_node(
            f"public_{tag}",
            f"Public Folder {tag}",
            is_public=True,
        ),
        _make_node(
            f"email_only_{tag}",
            f"Email-Only Folder {tag}",
            external_user_emails=["alice@example.com"],
        ),
        _make_node(
            f"group_only_{tag}",
            f"Group-Only Folder {tag}",
            external_user_group_ids=["group_engineering", "group_design"],
        ),
        _make_node(
            f"private_{tag}",
            f"Private Folder {tag}",
        ),
    ]
    for node in nodes:
        db_session.add(node)
    db_session.flush()

    yield nodes

    # Cleanup
    for node in nodes:
        db_session.delete(node)
    db_session.commit()


@pytest.fixture()
def connector_access_seed(
    db_session: Session,
) -> Generator[ConnectorAccessSeed, None, None]:
    tag = uuid4().hex[:8]
    user_rows = [
        UserSeed(
            id=uuid4(),
            email=f"{kind}_{tag}@example.com",
            hashed_password="unused",
            is_active=True,
            is_superuser=False,
            is_verified=True,
            account_type=AccountType.STANDARD,
        )
        for kind in ("owner", "member", "outsider")
    ]
    db_session.execute(
        text(
            'INSERT INTO "user" '
            "(id, email, hashed_password, is_active, is_superuser, is_verified, "
            "account_type) "
            "VALUES (:id, :email, :hashed_password, :is_active, :is_superuser, "
            ":is_verified, :account_type)"
        ),
        [user.model_dump(mode="json") for user in user_rows],
    )
    owner, member, outsider = user_rows

    cc_pair = make_cc_pair(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        commit=False,
    )
    cc_pair.access_type = AccessType.PRIVATE
    db_session.execute(
        update(Credential)
        .where(Credential.id == cc_pair.credential_id)
        .values(user_id=owner.id)
    )

    node = _make_node(
        raw_node_id=f"connector_private_{tag}",
        display_name=f"Connector Private Folder {tag}",
    )
    document = Document(
        id=f"connector_private_document_{tag}",
        semantic_id=f"Connector Private Document {tag}",
        parent_hierarchy_node_id=None,
        kg_stage=KGStage.NOT_STARTED,
    )
    group = UserGroup(name=f"hierarchy-access-group-{tag}")
    db_session.add_all([node, document, group])
    db_session.flush()
    document.parent_hierarchy_node_id = node.id
    db_session.add_all(
        [
            DocumentByConnectorCredentialPair(
                id=document.id,
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
                has_been_indexed=True,
            ),
            HierarchyNodeByConnectorCredentialPair(
                hierarchy_node_id=node.id,
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
            ),
            User__UserGroup(user_group_id=group.id, user_id=member.id),
            UserGroup__ConnectorCredentialPair(
                user_group_id=group.id,
                cc_pair_id=cc_pair.id,
                is_current=True,
            ),
        ]
    )
    db_session.flush()

    yield ConnectorAccessSeed(
        node=node,
        document_id=document.id,
        owner_id=owner.id,
        owner_email=owner.email,
        member_id=member.id,
        member_email=member.email,
        outsider_id=outsider.id,
        outsider_email=outsider.email,
    )
    db_session.rollback()


def test_group_overlap_filter(
    db_session: Session,
    seeded_nodes: list[HierarchyNode],
) -> None:
    """External group overlap grants node access."""
    results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email="",
        external_group_ids=["group_engineering"],
    )
    result_ids = {n.raw_node_id for n in results}

    public_node, _, group_node, private_node = seeded_nodes
    assert public_node.raw_node_id in result_ids
    assert group_node.raw_node_id in result_ids
    assert private_node.raw_node_id not in result_ids


def test_connector_credential_owner_can_access_node(
    db_session: Session,
    connector_access_seed: ConnectorAccessSeed,
) -> None:
    seed = connector_access_seed
    owner_results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email=seed.owner_email,
        external_group_ids=[],
        user_id=seed.owner_id,
    )
    outsider_results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email=seed.outsider_email,
        external_group_ids=[],
        user_id=seed.outsider_id,
    )

    assert seed.node.id in {node.id for node in owner_results}
    assert seed.node.id not in {node.id for node in outsider_results}


def test_connector_user_group_member_can_access_node(
    db_session: Session,
    connector_access_seed: ConnectorAccessSeed,
) -> None:
    seed = connector_access_seed
    member_results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email=seed.member_email,
        external_group_ids=[],
        user_id=seed.member_id,
    )
    outsider_results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email=seed.outsider_email,
        external_group_ids=[],
        user_id=seed.outsider_id,
    )

    assert seed.node.id in {node.id for node in member_results}
    assert seed.node.id not in {node.id for node in outsider_results}


def test_connector_credential_owner_can_access_hierarchy_document(
    db_session: Session,
    connector_access_seed: ConnectorAccessSeed,
) -> None:
    seed = connector_access_seed
    owner_results = get_accessible_documents_for_hierarchy_node_paginated(
        db_session=db_session,
        parent_hierarchy_node_id=seed.node.id,
        user_email=seed.owner_email,
        external_group_ids=[],
        user_id=seed.owner_id,
        limit=10,
    )
    outsider_results = get_accessible_documents_for_hierarchy_node_paginated(
        db_session=db_session,
        parent_hierarchy_node_id=seed.node.id,
        user_email=seed.outsider_email,
        external_group_ids=[],
        user_id=seed.outsider_id,
        limit=10,
    )

    assert seed.document_id in {document.id for document in owner_results}
    assert seed.document_id not in {document.id for document in outsider_results}


def test_connector_user_group_member_can_access_hierarchy_document(
    db_session: Session,
    connector_access_seed: ConnectorAccessSeed,
) -> None:
    seed = connector_access_seed
    member_results = get_accessible_documents_for_hierarchy_node_paginated(
        db_session=db_session,
        parent_hierarchy_node_id=seed.node.id,
        user_email=seed.member_email,
        external_group_ids=[],
        user_id=seed.member_id,
        limit=10,
    )
    outsider_results = get_accessible_documents_for_hierarchy_node_paginated(
        db_session=db_session,
        parent_hierarchy_node_id=seed.node.id,
        user_email=seed.outsider_email,
        external_group_ids=[],
        user_id=seed.outsider_id,
        limit=10,
    )

    assert seed.document_id in {document.id for document in member_results}
    assert seed.document_id not in {document.id for document in outsider_results}


def test_email_filter(
    db_session: Session,
    seeded_nodes: list[HierarchyNode],
) -> None:
    """User email matching should return the email-permissioned node."""
    results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email="alice@example.com",
        external_group_ids=[],
    )
    result_ids = {n.raw_node_id for n in results}

    public_node, email_node, group_node, private_node = seeded_nodes
    assert public_node.raw_node_id in result_ids
    assert email_node.raw_node_id in result_ids
    assert group_node.raw_node_id not in result_ids
    assert private_node.raw_node_id not in result_ids


def test_no_credentials_returns_only_public(
    db_session: Session,
    seeded_nodes: list[HierarchyNode],
) -> None:
    """With no email and no groups, only public nodes should be returned."""
    results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email="",
        external_group_ids=[],
    )
    result_ids = {n.raw_node_id for n in results}

    public_node, email_node, group_node, private_node = seeded_nodes
    assert public_node.raw_node_id in result_ids
    assert email_node.raw_node_id not in result_ids
    assert group_node.raw_node_id not in result_ids
    assert private_node.raw_node_id not in result_ids


def test_combined_email_and_group(
    db_session: Session,
    seeded_nodes: list[HierarchyNode],
) -> None:
    """Both email and group filters should apply together via OR."""
    results = _get_accessible_hierarchy_nodes_for_source(
        db_session,
        source=DocumentSource.GOOGLE_DRIVE,
        user_email="alice@example.com",
        external_group_ids=["group_design"],
    )
    result_ids = {n.raw_node_id for n in results}

    public_node, email_node, group_node, private_node = seeded_nodes
    assert public_node.raw_node_id in result_ids
    assert email_node.raw_node_id in result_ids
    assert group_node.raw_node_id in result_ids
    assert private_node.raw_node_id not in result_ids


def test_source_node_always_accessible(
    db_session: Session,
) -> None:
    """SOURCE roots are always returned, even when is_public is false."""
    source_node = get_source_hierarchy_node(db_session, DocumentSource.SLACK)
    assert source_node is not None
    original_is_public = source_node.is_public
    source_node.is_public = False

    tag = uuid4().hex[:8]
    private_child = HierarchyNode(
        raw_node_id=f"private_child_{tag}",
        display_name=f"Private Child {tag}",
        source=DocumentSource.SLACK,
        node_type=HierarchyNodeType.CHANNEL,
        is_public=False,
    )
    db_session.add(private_child)
    db_session.flush()

    try:
        results = _get_accessible_hierarchy_nodes_for_source(
            db_session,
            source=DocumentSource.SLACK,
            user_email="",
            external_group_ids=[],
        )
        result_ids = {n.id for n in results}
        assert source_node.id in result_ids
        assert private_child.id not in result_ids
    finally:
        source_node.is_public = original_is_public
        db_session.delete(private_child)
        db_session.commit()
