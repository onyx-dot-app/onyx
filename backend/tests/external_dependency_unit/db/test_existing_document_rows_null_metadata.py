"""The permission syncs read a connector's stored rows. Connectors that never set
document metadata store it as null, and those rows must still read."""

from collections.abc import Generator, Sequence
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.document import get_documents_for_connector_credential_pair_limited_columns
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    DocumentByConnectorCredentialPair,
)
from onyx.db.utils import DocumentRow
from onyx.kg.models import KGStage
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair: ConnectorCredentialPair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        cleanup_cc_pair(db_session, pair)


def _store(
    db_session: Session, pair: ConnectorCredentialPair, metadata: dict[str, str] | None
) -> str:
    doc_id: str = f"null-metadata-{uuid4().hex}"
    db_session.add(
        Document(
            id=doc_id,
            semantic_id=doc_id,
            kg_stage=KGStage.NOT_STARTED,
            doc_metadata=metadata,
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
    db_session.commit()
    return doc_id


def test_rows_with_null_metadata_read_as_empty(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    without: str = _store(db_session, cc_pair, None)
    with_metadata: str = _store(db_session, cc_pair, {"repo": "onyx"})

    rows: Sequence[DocumentRow] = (
        get_documents_for_connector_credential_pair_limited_columns(
            db_session=db_session,
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
        )
    )

    assert {row.id: row.doc_metadata for row in rows} == {
        without: {},
        with_metadata: {"repo": "onyx"},
    }
