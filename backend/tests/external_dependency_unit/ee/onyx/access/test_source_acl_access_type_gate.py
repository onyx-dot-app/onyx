"""Source ACL columns on a Document (is_public, external_*) only grant access
while a live cc_pair of the document is perm-synced. Each test rolls its
transaction back."""

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ee.onyx.access.access import _get_access_for_documents
from ee.onyx.server.documents.cc_pair import sync_cc_pair, sync_cc_pair_groups
from onyx.access.models import ExternalAccess
from onyx.access.utils import prefix_external_group, prefix_user_email
from onyx.configs.constants import PUBLIC_DOC_PAT, DocumentSource
from onyx.connectors.models import Document as ConnectorDocument
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.document_access import get_accessible_documents_by_ids
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    DocumentByConnectorCredentialPair,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.indexing.indexing_pipeline import _upsert_documents_in_db
from onyx.server.models import StatusResponse
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_OLD = datetime.now(timezone.utc) - timedelta(days=1)
_EMAIL = "source-reader@example.com"
_GROUP = "source_group"


def _pair(
    db_session: Session,
    access_type: AccessType,
    status: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.ACTIVE,
) -> ConnectorCredentialPair:
    pair = make_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE, commit=False)
    pair.access_type = access_type
    pair.status = status
    db_session.flush()
    return pair


def _doc_with_source_acl(db_session: Session, *pairs: ConnectorCredentialPair) -> str:
    doc_id = f"acl-gate-{uuid4().hex[:8]}"
    db_session.add(
        Document(
            id=doc_id,
            semantic_id=doc_id,
            chunk_count=1,
            last_modified=_OLD,
            last_synced=_OLD,
            is_public=True,
            external_user_emails=[_EMAIL],
            external_user_group_ids=[_GROUP],
        )
    )
    db_session.flush()
    for pair in pairs:
        db_session.add(
            DocumentByConnectorCredentialPair(
                id=doc_id,
                connector_id=pair.connector_id,
                credential_id=pair.credential_id,
                has_been_indexed=True,
            )
        )
    db_session.flush()
    return doc_id


_SOURCE_ACL = {
    PUBLIC_DOC_PAT,
    prefix_user_email(_EMAIL),
    prefix_external_group(_GROUP),
}


@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize(
    "access_types,expect_source_acl",
    [
        ([AccessType.SYNC], True),
        ([AccessType.SYNC_RESTRICTED], True),
        ([AccessType.PRIVATE], False),
        ([AccessType.PRIVATE, AccessType.SYNC], True),
    ],
)
def test_acl_uses_source_columns_only_for_perm_synced_pairs(
    db_session: Session, access_types: list[AccessType], expect_source_acl: bool
) -> None:
    try:
        pairs = [_pair(db_session, access_type) for access_type in access_types]
        doc_id = _doc_with_source_acl(db_session, *pairs)

        acl = _get_access_for_documents([doc_id], db_session)[doc_id].to_acl()

        assert _SOURCE_ACL <= acl if expect_source_acl else not (_SOURCE_ACL & acl)
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
def test_deleting_sync_pair_does_not_keep_source_acl(db_session: Session) -> None:
    try:
        deleting = _pair(
            db_session, AccessType.SYNC, ConnectorCredentialPairStatus.DELETING
        )
        doc_id = _doc_with_source_acl(
            db_session, deleting, _pair(db_session, AccessType.PRIVATE)
        )

        acl = _get_access_for_documents([doc_id], db_session)[doc_id].to_acl()

        assert not (_SOURCE_ACL & acl)
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize(
    "access_type,expect_visible",
    [(AccessType.SYNC, True), (AccessType.PRIVATE, False)],
)
def test_document_filter_uses_source_columns_only_for_perm_synced_pairs(
    db_session: Session, access_type: AccessType, expect_visible: bool
) -> None:
    try:
        doc_id = _doc_with_source_acl(db_session, _pair(db_session, access_type))

        docs = get_accessible_documents_by_ids(
            db_session, [doc_id], user_email=_EMAIL, external_group_ids=[_GROUP]
        )

        assert [doc.id for doc in docs] == ([doc_id] if expect_visible else [])
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize(
    "access_type,expect_written",
    [(AccessType.SYNC, True), (AccessType.PRIVATE, False)],
)
def test_indexing_writes_source_acl_only_for_perm_synced_pairs(
    db_session: Session, access_type: AccessType, expect_written: bool
) -> None:
    # upsert_documents commits, so this test cleans up its own rows.
    pair = make_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)
    pair.access_type = access_type
    db_session.commit()
    doc_id = f"acl-gate-index-{uuid4().hex[:8]}"
    try:
        _upsert_documents_in_db(
            [
                ConnectorDocument(
                    id=doc_id,
                    source=DocumentSource.GOOGLE_DRIVE,
                    sections=[],
                    semantic_identifier=doc_id,
                    metadata={},
                    external_access=ExternalAccess(
                        external_user_emails={_EMAIL},
                        external_user_group_ids={_GROUP},
                        is_public=True,
                    ),
                )
            ],
            IndexAttemptMetadata(
                connector_id=pair.connector_id, credential_id=pair.credential_id
            ),
            db_session,
        )

        db_session.expire_all()
        row = db_session.get(Document, doc_id)
        assert row is not None
        assert bool(row.is_public) is expect_written
        assert bool(row.external_user_emails) is expect_written
        assert bool(row.external_user_group_ids) is expect_written
    finally:
        db_session.rollback()
        db_session.execute(delete(Document).where(Document.id == doc_id))
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize("route", [sync_cc_pair, sync_cc_pair_groups])
def test_manual_sync_refused_for_non_perm_synced_pair(
    db_session: Session, route: Callable[..., StatusResponse[None]]
) -> None:
    pair = make_cc_pair(db_session, DocumentSource.GOOGLE_DRIVE)
    pair.access_type = AccessType.PRIVATE
    db_session.commit()
    admin = create_test_user(db_session, "acl-gate-admin", is_admin=True)
    try:
        with pytest.raises(OnyxError) as exc_info:
            route(cc_pair_id=pair.id, user=admin, db_session=db_session)

        assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT
    finally:
        db_session.rollback()
        delete_test_user(db_session, admin)
        db_session.commit()
        cleanup_cc_pair(db_session, pair)
