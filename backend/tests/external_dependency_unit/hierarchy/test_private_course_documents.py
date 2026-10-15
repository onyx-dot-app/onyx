from collections.abc import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import InputType
from onyx.db.document import get_accessible_documents_for_hierarchy_node_paginated
from onyx.db.document_access import get_accessible_documents_by_ids
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.enums import HierarchyNodeType
from onyx.db.lti_knowledge import (
    get_lti_course_accessible_documents_for_hierarchy_node,
)
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import HierarchyNode
from onyx.db.models import HierarchyNodeByConnectorCredentialPair
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserGroup__ConnectorCredentialPair
from onyx.db.models import UserRole
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.kg.models import KGStage
from onyx.server.features.hierarchy.models import DocumentSortDirection
from onyx.server.features.hierarchy.models import DocumentSortField
from onyx.server.lti.knowledge import validate_lti_course_knowledge_selection

pytestmark = pytest.mark.usefixtures("enable_ee")


@pytest.fixture()
def course_documents(
    db_session: Session,
) -> Generator[tuple[list[User], HierarchyNode, list[Document]], None, None]:
    tag = uuid4().hex
    users = [
        User(
            id=uuid4(),
            email=f"{name}-{tag}@example.com",
            hashed_password="unused",
            role=UserRole.BASIC,
        )
        for name in ("owner", "member", "outsider")
    ]
    node = HierarchyNode(
        raw_node_id=tag,
        display_name=f"Course {tag}",
        source=DocumentSource.GOOGLE_DRIVE,
        node_type=HierarchyNodeType.FOLDER,
        is_public=True,
    )
    group = UserGroup(name=f"Course {tag}", lti_context_id=tag)
    for user in users:
        db_session.add(user)
        db_session.flush()
    db_session.add_all([node, group])
    db_session.flush()
    credential = Credential(
        user_id=users[0].id, source=DocumentSource.GOOGLE_DRIVE, is_lti_credential=True
    )
    db_session.add(credential)
    db_session.flush()
    documents = []
    for label, access_type, status, current_group in (
        ("private", AccessType.PRIVATE, ConnectorCredentialPairStatus.ACTIVE, True),
        ("foreign", AccessType.PRIVATE, ConnectorCredentialPairStatus.ACTIVE, True),
        ("sync", AccessType.SYNC, ConnectorCredentialPairStatus.ACTIVE, True),
        ("deleted", AccessType.PRIVATE, ConnectorCredentialPairStatus.DELETING, True),
        ("old_group", AccessType.PRIVATE, ConnectorCredentialPairStatus.ACTIVE, False),
    ):
        connector = Connector(
            name=f"{label}-{tag}",
            source=DocumentSource.GOOGLE_DRIVE,
            input_type=InputType.POLL,
            connector_specific_config={
                "lti_context_id": tag if label == "private" else f"other-{tag}"
            },
        )
        db_session.add(connector)
        db_session.flush()
        pair = ConnectorCredentialPair(
            name=connector.name,
            connector_id=connector.id,
            credential_id=credential.id,
            creator_id=users[0].id,
            access_type=access_type,
            status=status,
        )
        document = Document(
            id=connector.name,
            semantic_id=label,
            parent_hierarchy_node_id=node.id,
            is_public=False,
            external_user_emails=None,
            external_user_group_ids=None,
            kg_stage=KGStage.NOT_STARTED,
        )
        db_session.add_all([pair, document])
        db_session.flush()
        db_session.add_all(
            [
                DocumentByConnectorCredentialPair(
                    id=document.id,
                    connector_id=connector.id,
                    credential_id=credential.id,
                    has_been_indexed=True,
                ),
                HierarchyNodeByConnectorCredentialPair(
                    hierarchy_node_id=node.id,
                    connector_id=connector.id,
                    credential_id=credential.id,
                ),
                UserGroup__ConnectorCredentialPair(
                    user_group_id=group.id, cc_pair_id=pair.id, is_current=current_group
                ),
            ]
        )
        documents.append(document)
    db_session.add(User__UserGroup(user_group_id=group.id, user_id=users[1].id))
    db_session.flush()
    yield users, node, documents
    db_session.rollback()


@pytest.mark.parametrize("user_index", [0, 1, 2])
def test_private_connector_access_and_sync_permissions(
    db_session: Session,
    course_documents: tuple[list[User], HierarchyNode, list[Document]],
    user_index: int,
) -> None:
    users, _, documents = course_documents
    accessible = get_accessible_documents_by_ids(
        db_session, [d.id for d in documents], users[user_index].email, []
    )
    expected = {documents[0].id, documents[1].id}
    if user_index == 0:
        expected.add(documents[4].id)
    if user_index == 2:
        expected = set()
    assert {d.id for d in accessible} == expected


@pytest.mark.parametrize("user_index", [0, 1, 2])
def test_course_picker_scopes_private_documents(
    db_session: Session,
    course_documents: tuple[list[User], HierarchyNode, list[Document]],
    user_index: int,
) -> None:
    users, node, documents = course_documents
    accessible = get_lti_course_accessible_documents_for_hierarchy_node(
        db_session,
        node.raw_node_id,
        node.id,
        users[user_index].email,
        [],
        None,
        DocumentSortField.NAME,
        DocumentSortDirection.ASC,
    )
    assert {d.id for d in accessible} == (
        {documents[0].id} if user_index < 2 else set()
    )


def test_empty_course_scope_and_anonymous_access_return_nothing(
    db_session: Session,
    course_documents: tuple[list[User], HierarchyNode, list[Document]],
) -> None:
    users, node, documents = course_documents
    accessible = get_accessible_documents_for_hierarchy_node_paginated(
        db_session,
        node.id,
        users[0].email,
        [],
        50,
        connector_credential_pairs=[],
    )
    assert accessible == []
    assert (
        get_accessible_documents_by_ids(db_session, [documents[0].id], None, []) == []
    )


@pytest.mark.parametrize("permission_kind", ["public", "email", "group"])
def test_source_permissions_still_allow_access_to_sync_documents(
    db_session: Session,
    course_documents: tuple[list[User], HierarchyNode, list[Document]],
    permission_kind: str,
) -> None:
    users, _, documents = course_documents
    document = documents[2]
    if permission_kind == "public":
        document.is_public = True
    elif permission_kind == "email":
        document.external_user_emails = [users[2].email]
    else:
        document.external_user_group_ids = ["external-course-group"]
    db_session.flush()
    accessible = get_accessible_documents_by_ids(
        db_session, [document.id], users[2].email, ["external-course-group"]
    )
    assert [d.id for d in accessible] == [document.id]


@pytest.mark.parametrize("foreign", [False, True])
def test_saving_private_document_selection_enforces_course_scope(
    db_session: Session,
    course_documents: tuple[list[User], HierarchyNode, list[Document]],
    foreign: bool,
) -> None:
    users, node, documents = course_documents
    with patch("onyx.server.lti.knowledge.require_lti_instructor_launch_context"):
        if foreign:
            with pytest.raises(OnyxError) as error:
                validate_lti_course_knowledge_selection(
                    db_session, node.raw_node_id, users[0], [], [documents[1].id]
                )
            assert error.value.error_code == OnyxErrorCode.UNAUTHORIZED
        else:
            validate_lti_course_knowledge_selection(
                db_session, node.raw_node_id, users[0], [], [documents[0].id]
            )
