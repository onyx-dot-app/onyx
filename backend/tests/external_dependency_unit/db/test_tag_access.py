from collections.abc import Generator
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.db.enums import AccessType
from onyx.db.models import (
    Credential,
    Document,
    Document__Tag,
    DocumentByConnectorCredentialPair,
    Tag,
    User,
)
from onyx.kg.models import KGStage
from onyx.server.query_and_chat.query_backend import get_tags
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


@pytest.fixture()
def tag_user(db_session: Session) -> Generator[User, None, None]:
    user = User(
        id=uuid4(),
        email=f"tags-{uuid4().hex}@example.com",
        hashed_password="unused",
        is_active=True,
        is_superuser=False,
        is_verified=True,
    )
    db_session.add(user)
    db_session.flush()
    yield user
    db_session.rollback()


@pytest.mark.parametrize(
    "access", ["public", "email", "external_group", "owner", "prior_email"]
)
def test_tags_require_document_access(
    db_session: Session, tag_user: User, access: str
) -> None:
    prefix = uuid4().hex
    pair = make_cc_pair(db_session, commit=False)
    pair.access_type = AccessType.PRIVATE
    document = Document(
        id=prefix,
        semantic_id=prefix,
        kg_stage=KGStage.NOT_STARTED,
        is_public=access == "public",
        external_user_emails=[tag_user.email] if access == "email" else [],
        external_user_group_ids=[prefix] if access == "external_group" else [],
    )
    if access == "prior_email":
        tag_user.prior_emails = [f"previous-{prefix}@example.com"]
        document.external_user_emails = list(tag_user.prior_emails)
    if access == "owner":
        credential = db_session.get(Credential, pair.credential_id)
        assert credential is not None
        credential.user_id = tag_user.id
    allowed = Tag(
        tag_key=prefix, tag_value="allowed", source=DocumentSource.MOCK_CONNECTOR
    )
    orphan = Tag(
        tag_key=prefix, tag_value="orphan", source=DocumentSource.MOCK_CONNECTOR
    )
    db_session.add_all([document, allowed, orphan])
    db_session.flush()
    db_session.add_all(
        [
            Document__Tag(document_id=document.id, tag_id=allowed.id),
            DocumentByConnectorCredentialPair(
                id=document.id,
                connector_id=pair.connector_id,
                credential_id=pair.credential_id,
                has_been_indexed=True,
            ),
        ]
    )
    db_session.flush()
    with patch(
        "onyx.server.query_and_chat.query_backend.get_user_external_group_ids",
        return_value=[prefix],
    ):
        result = get_tags(match_pattern=prefix, user=tag_user, db_session=db_session)
    assert [tag.tag_value for tag in result.tags] == ["allowed"]

    document.is_public = False
    if access == "prior_email":
        tag_user.prior_emails = []
    else:
        document.external_user_emails = []
    document.external_user_group_ids = []
    if access == "owner":
        credential = db_session.get(Credential, pair.credential_id)
        assert credential is not None
        credential.user_id = None
    db_session.flush()
    with patch(
        "onyx.server.query_and_chat.query_backend.get_user_external_group_ids",
        return_value=[],
    ):
        result = get_tags(match_pattern=prefix, user=tag_user, db_session=db_session)
    assert result.tags == []


@pytest.mark.parametrize("pattern", ["%", "_", "key=%", "key=_"])
def test_tag_prefix_wildcards_are_literal(
    db_session: Session, tag_user: User, pattern: str
) -> None:
    pair = make_cc_pair(db_session, commit=False)
    pair.access_type = AccessType.PUBLIC
    document = Document(
        id=uuid4().hex, semantic_id="prefix", kg_stage=KGStage.NOT_STARTED
    )
    tag = Tag(tag_key="key", tag_value="value", source=DocumentSource.MOCK_CONNECTOR)
    db_session.add_all([document, tag])
    db_session.flush()
    db_session.add_all(
        [
            Document__Tag(document_id=document.id, tag_id=tag.id),
            DocumentByConnectorCredentialPair(
                id=document.id,
                connector_id=pair.connector_id,
                credential_id=pair.credential_id,
                has_been_indexed=True,
            ),
        ]
    )
    db_session.flush()
    assert (
        get_tags(match_pattern=pattern, user=tag_user, db_session=db_session).tags == []
    )
    assert (
        len(
            get_tags(match_pattern="KEY=VAL", user=tag_user, db_session=db_session).tags
        )
        == 1
    )


@pytest.mark.parametrize(("limit", "expected"), [(0, 1), (-1, 1), (1000, 100)])
def test_valid_tags_limit_is_bounded(
    db_session: Session, tag_user: User, limit: int, expected: int
) -> None:
    prefix = uuid4().hex
    pair = make_cc_pair(db_session, commit=False)
    pair.access_type = AccessType.PUBLIC
    document = Document(id=prefix, semantic_id=prefix, kg_stage=KGStage.NOT_STARTED)
    tags = [
        Tag(tag_key=prefix, tag_value=str(i), source=DocumentSource.MOCK_CONNECTOR)
        for i in range(105)
    ]
    db_session.add_all([document, *tags])
    db_session.flush()
    db_session.add(
        DocumentByConnectorCredentialPair(
            id=document.id,
            connector_id=pair.connector_id,
            credential_id=pair.credential_id,
            has_been_indexed=True,
        )
    )
    db_session.add_all(
        [Document__Tag(document_id=document.id, tag_id=tag.id) for tag in tags]
    )
    db_session.flush()
    result = get_tags(
        match_pattern=prefix, limit=limit, user=tag_user, db_session=db_session
    )
    assert len(result.tags) == expected
