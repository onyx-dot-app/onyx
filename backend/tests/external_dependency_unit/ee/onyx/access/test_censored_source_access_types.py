"""get_document_access_types reports every non-deleting cc_pair a document is
indexed under, and the EE access computation opens a censoring-only source's
document at retrieval only when one of those pairs is perm-synced. Each test
rolls its transaction back."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ee.onyx.access.access import _get_access_for_documents
from onyx.configs.constants import DocumentSource
from onyx.db.document import get_document_access_types
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    DocumentByConnectorCredentialPair,
)
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

_OLD = datetime.now(timezone.utc) - timedelta(days=1)


def _pair(
    db_session: Session,
    access_type: AccessType,
    status: ConnectorCredentialPairStatus = ConnectorCredentialPairStatus.ACTIVE,
) -> ConnectorCredentialPair:
    pair = make_cc_pair(db_session, DocumentSource.SALESFORCE, commit=False)
    pair.access_type = access_type
    pair.status = status
    db_session.flush()
    return pair


def _doc(db_session: Session, *pairs: ConnectorCredentialPair) -> str:
    doc_id = f"censor-{uuid4().hex[:8]}"
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


@pytest.mark.usefixtures("tenant_context")
def test_access_types_cover_every_pair_except_deleting(db_session: Session) -> None:
    try:
        private = _pair(db_session, AccessType.PRIVATE)
        synced = _pair(db_session, AccessType.SYNC)
        deleting = _pair(
            db_session, AccessType.PUBLIC, ConnectorCredentialPairStatus.DELETING
        )
        both = _doc(db_session, private, synced)
        deleting_only = _doc(db_session, deleting)
        private_only = _doc(db_session, private)

        result = get_document_access_types(
            db_session, [both, deleting_only, private_only, "missing"]
        )

        assert result == {
            both: {AccessType.PRIVATE, AccessType.SYNC},
            private_only: {AccessType.PRIVATE},
        }
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize(
    "access_type,expected_public",
    [
        (AccessType.SYNC, True),
        (AccessType.SYNC_RESTRICTED, True),
        (AccessType.PRIVATE, False),
    ],
)
def test_censoring_only_source_opens_perm_synced_documents(
    db_session: Session, access_type: AccessType, expected_public: bool
) -> None:
    try:
        doc_id = _doc(db_session, _pair(db_session, access_type))

        access = _get_access_for_documents([doc_id], db_session)[doc_id]

        assert access.is_public is expected_public
    finally:
        db_session.rollback()
