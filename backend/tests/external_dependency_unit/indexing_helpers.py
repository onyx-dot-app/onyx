"""Shared helpers for external-dependency indexing tests.

Three test files exercise the `Document` / `cc_pair` / `file_store` surfaces
against real Postgres + S3: `test_index_doc_batch_prepare`, `test_index_swap_workflow`,
and `test_document_deletion_file_cleanup`. The setup + teardown logic is
substantial and identical across all three, so it lives here.

Tests keep their own `cc_pair` fixture (dependencies differ per file), but
the body is just `make_cc_pair` + `cleanup_cc_pair`.
"""

from io import BytesIO
from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.models import Document
from onyx.connectors.models import InputType
from onyx.connectors.models import TextSection
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.file_record import get_filerecord_by_file_id_optional
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import Document as DBDocument
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import FileRecord
from onyx.file_store.file_store import get_default_file_store


def make_doc(
    doc_id: str,
    file_id: str | None = None,
    from_ingestion_api: bool = False,
) -> Document:
    """Minimal Document for indexing-pipeline tests. MOCK_CONNECTOR avoids
    triggering the hierarchy-node linking branch (NOTION/CONFLUENCE only)."""
    return Document(
        id=doc_id,
        source=DocumentSource.MOCK_CONNECTOR,
        semantic_identifier=f"semantic-{doc_id}",
        sections=[TextSection(text="content", link=None)],
        metadata={},
        file_id=file_id,
        from_ingestion_api=from_ingestion_api,
    )


def stage_file(content: bytes = b"raw bytes") -> str:
    """Write bytes to the file store as INDEXING_STAGING and return the file_id.

    Mirrors what the connector raw_file_callback would do during fetch.
    The `{"test": True}` metadata tag lets manual cleanup scripts find
    leftovers if a cleanup ever slips through.
    """
    return get_default_file_store().save_file(
        content=BytesIO(content),
        display_name=None,
        file_origin=FileOrigin.INDEXING_STAGING,
        file_type="application/octet-stream",
        file_metadata={"test": True},
    )


def get_doc_row(db_session: Session, doc_id: str) -> DBDocument | None:
    """Reload the document row fresh from DB so we see post-upsert state."""
    db_session.expire_all()
    return db_session.query(DBDocument).filter(DBDocument.id == doc_id).one_or_none()


def get_filerecord(db_session: Session, file_id: str) -> FileRecord | None:
    db_session.expire_all()
    return get_filerecord_by_file_id_optional(file_id=file_id, db_session=db_session)


def make_cc_pair(db_session: Session) -> ConnectorCredentialPair:
    """Create a Connector + Credential + ConnectorCredentialPair for a test.

    All names are UUID-suffixed so parallel test runs don't collide.
    """
    connector = Connector(
        name=f"test-connector-{uuid4().hex[:8]}",
        source=DocumentSource.MOCK_CONNECTOR,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        source=DocumentSource.MOCK_CONNECTOR,
        credential_json={},
    )
    db_session.add(credential)
    db_session.flush()

    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"test-cc-pair-{uuid4().hex[:8]}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        auto_sync_options=None,
    )
    db_session.add(pair)
    db_session.commit()
    db_session.refresh(pair)
    return pair


def cleanup_cc_pair(db_session: Session, pair: ConnectorCredentialPair) -> None:
    """Tear down everything created under `pair`.

    Deletes own join rows first (FK to document has no cascade), then for any
    doc that now has zero remaining cc_pair references, deletes its file +
    the document row. Finally removes the cc_pair, connector, credential.
    Safe against docs shared with other cc_pairs — those stay alive until
    their last reference is torn down.
    """
    db_session.expire_all()

    connector_id = pair.connector_id
    credential_id = pair.credential_id

    owned_doc_ids: list[str] = [
        row[0]
        for row in db_session.query(DocumentByConnectorCredentialPair.id)
        .filter(
            DocumentByConnectorCredentialPair.connector_id == connector_id,
            DocumentByConnectorCredentialPair.credential_id == credential_id,
        )
        .all()
    ]

    db_session.query(DocumentByConnectorCredentialPair).filter(
        DocumentByConnectorCredentialPair.connector_id == connector_id,
        DocumentByConnectorCredentialPair.credential_id == credential_id,
    ).delete(synchronize_session="fetch")
    db_session.flush()

    if owned_doc_ids:
        orphan_doc_ids: list[str] = [
            row[0]
            for row in db_session.query(DBDocument.id)
            .filter(DBDocument.id.in_(owned_doc_ids))
            .filter(
                ~db_session.query(DocumentByConnectorCredentialPair)
                .filter(DocumentByConnectorCredentialPair.id == DBDocument.id)
                .exists()
            )
            .all()
        ]
        orphan_file_ids: list[str] = [
            row[0]
            for row in db_session.query(DBDocument.file_id)
            .filter(
                DBDocument.id.in_(orphan_doc_ids),
                DBDocument.file_id.isnot(None),
            )
            .all()
        ]

        file_store = get_default_file_store()
        for fid in orphan_file_ids:
            try:
                file_store.delete_file(fid, error_on_missing=False)
            except Exception:
                pass

        if orphan_doc_ids:
            db_session.query(DBDocument).filter(
                DBDocument.id.in_(orphan_doc_ids)
            ).delete(synchronize_session="fetch")

    db_session.query(ConnectorCredentialPair).filter(
        ConnectorCredentialPair.id == pair.id
    ).delete(synchronize_session="fetch")
    db_session.query(Connector).filter(Connector.id == connector_id).delete(
        synchronize_session="fetch"
    )
    db_session.query(Credential).filter(Credential.id == credential_id).delete(
        synchronize_session="fetch"
    )
    db_session.commit()
