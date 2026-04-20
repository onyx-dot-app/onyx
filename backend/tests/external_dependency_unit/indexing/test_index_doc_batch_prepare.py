"""External dependency unit tests for `index_doc_batch_prepare`.

Validates the file_id lifecycle that runs alongside the document upsert:

    * `document.file_id` is written on insert AND on conflict (upsert path)
    * Newly-staged files get promoted from INDEXING_STAGING -> CONNECTOR
    * Replaced files are deleted from both `file_record` and S3
    * No-op when the file_id is unchanged

Uses real PostgreSQL + real S3/MinIO via the file store.
"""

from collections.abc import Generator
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
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
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(doc_id: str, file_id: str | None = None) -> Document:
    """Minimal Document for indexing-pipeline tests. MOCK_CONNECTOR avoids
    triggering the hierarchy-node linking branch (NOTION/CONFLUENCE only)."""
    return Document(
        id=doc_id,
        source=DocumentSource.MOCK_CONNECTOR,
        semantic_identifier=f"semantic-{doc_id}",
        sections=[TextSection(text="content", link=None)],
        metadata={},
        file_id=file_id,
    )


def _stage_file(content: bytes = b"raw bytes") -> str:
    """Write bytes to the file store as INDEXING_STAGING and return the file_id.

    Mirrors what the connector raw_file_callback would do during fetch.
    """
    return get_default_file_store().save_file(
        content=BytesIO(content),
        display_name=None,
        file_origin=FileOrigin.INDEXING_STAGING,
        file_type="application/octet-stream",
        file_metadata={"test": True},
    )


def _get_doc_row(db_session: Session, doc_id: str) -> DBDocument | None:
    """Reload the document row fresh from DB so we see post-upsert state."""
    db_session.expire_all()
    return db_session.query(DBDocument).filter(DBDocument.id == doc_id).one_or_none()


def _get_filerecord(db_session: Session, file_id: str) -> FileRecord | None:
    db_session.expire_all()
    return get_filerecord_by_file_id_optional(file_id=file_id, db_session=db_session)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    """Create a connector + credential + cc_pair backing the index attempt.

    Teardown sweeps everything the test created under this cc_pair: the
    `document_by_connector_credential_pair` join rows, the `Document` rows
    they point at, the `FileRecord` + blob for each doc's `file_id`, and
    finally the cc_pair / connector / credential themselves. Without this,
    every run would leave orphan rows in the dev DB and orphan blobs in
    MinIO.
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

    connector_id = pair.connector_id
    credential_id = pair.credential_id

    try:
        yield pair
    finally:
        db_session.expire_all()

        # Collect every doc indexed under this cc_pair so we can delete its
        # file_record + blob before dropping the Document row itself.
        doc_ids: list[str] = [
            row[0]
            for row in db_session.query(DocumentByConnectorCredentialPair.id)
            .filter(
                DocumentByConnectorCredentialPair.connector_id == connector_id,
                DocumentByConnectorCredentialPair.credential_id == credential_id,
            )
            .all()
        ]
        file_ids: list[str] = [
            row[0]
            for row in db_session.query(DBDocument.file_id)
            .filter(DBDocument.id.in_(doc_ids), DBDocument.file_id.isnot(None))
            .all()
        ]

        file_store = get_default_file_store()
        for fid in file_ids:
            try:
                file_store.delete_file(fid, error_on_missing=False)
            except Exception:
                pass

        if doc_ids:
            db_session.query(DocumentByConnectorCredentialPair).filter(
                DocumentByConnectorCredentialPair.id.in_(doc_ids)
            ).delete(synchronize_session="fetch")
            db_session.query(DBDocument).filter(DBDocument.id.in_(doc_ids)).delete(
                synchronize_session="fetch"
            )

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


@pytest.fixture
def attempt_metadata(cc_pair: ConnectorCredentialPair) -> IndexAttemptMetadata:
    return IndexAttemptMetadata(
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        attempt_id=None,
        request_id="test-request",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNewDocuments:
    """First-time inserts — no previous file_id to reconcile against."""

    def test_new_doc_without_file_id(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        doc = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=None)

        index_doc_batch_prepare(
            documents=[doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        row = _get_doc_row(db_session, doc.id)
        assert row is not None
        assert row.file_id is None

    def test_new_doc_with_staged_file_id_promotes_to_connector(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        file_id = _stage_file()
        doc = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id)

        index_doc_batch_prepare(
            documents=[doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        row = _get_doc_row(db_session, doc.id)
        assert row is not None and row.file_id == file_id

        record = _get_filerecord(db_session, file_id)
        assert record is not None
        assert record.file_origin == FileOrigin.CONNECTOR


class TestExistingDocuments:
    """Re-index path — a `document` row already exists with some file_id."""

    def test_unchanged_file_id_is_noop(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        file_id = _stage_file()
        doc = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id)

        # First pass: inserts the row + promotes the file.
        index_doc_batch_prepare(
            documents=[doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        # Second pass with the same file_id — should not delete or re-promote.
        index_doc_batch_prepare(
            documents=[doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        record = _get_filerecord(db_session, file_id)
        assert record is not None
        assert record.file_origin == FileOrigin.CONNECTOR

        row = _get_doc_row(db_session, doc.id)
        assert row is not None and row.file_id == file_id

    def test_swapping_file_id_promotes_new_and_deletes_old(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        old_file_id = _stage_file(content=b"old bytes")
        doc = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=old_file_id)

        index_doc_batch_prepare(
            documents=[doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        # Re-fetch produces a new staged file_id for the same doc.
        new_file_id = _stage_file(content=b"new bytes")
        doc_v2 = _make_doc(doc.id, file_id=new_file_id)

        index_doc_batch_prepare(
            documents=[doc_v2],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        row = _get_doc_row(db_session, doc.id)
        assert row is not None and row.file_id == new_file_id

        new_record = _get_filerecord(db_session, new_file_id)
        assert new_record is not None
        assert new_record.file_origin == FileOrigin.CONNECTOR

        # Old file_record + S3 object are gone.
        assert _get_filerecord(db_session, old_file_id) is None

    def test_clearing_file_id_deletes_old_and_nulls_column(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        old_file_id = _stage_file()
        doc = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=old_file_id)

        index_doc_batch_prepare(
            documents=[doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        # Connector opts out on next run — yields the doc without a file_id.
        doc_v2 = _make_doc(doc.id, file_id=None)

        index_doc_batch_prepare(
            documents=[doc_v2],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        row = _get_doc_row(db_session, doc.id)
        assert row is not None and row.file_id is None
        assert _get_filerecord(db_session, old_file_id) is None


class TestBatchHandling:
    """Mixed batches — multiple docs at different lifecycle states in one call."""

    def test_mixed_batch_each_doc_handled_independently(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        # Pre-seed an existing doc with a file_id we'll swap.
        existing_old_id = _stage_file(content=b"existing-old")
        existing_doc = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=existing_old_id)
        index_doc_batch_prepare(
            documents=[existing_doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        # Now: swap the existing one, add a brand-new doc with file_id, and a
        # brand-new doc without file_id.
        swap_new_id = _stage_file(content=b"existing-new")
        new_with_file_id = _stage_file(content=b"new-with-file")
        existing_v2 = _make_doc(existing_doc.id, file_id=swap_new_id)
        new_with = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=new_with_file_id)
        new_without = _make_doc(f"doc-{uuid4().hex[:8]}", file_id=None)

        index_doc_batch_prepare(
            documents=[existing_v2, new_with, new_without],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        # Existing doc was swapped: old file gone, new file promoted.
        existing_row = _get_doc_row(db_session, existing_doc.id)
        assert existing_row is not None and existing_row.file_id == swap_new_id
        assert _get_filerecord(db_session, existing_old_id) is None
        swap_record = _get_filerecord(db_session, swap_new_id)
        assert swap_record is not None
        assert swap_record.file_origin == FileOrigin.CONNECTOR

        # New doc with file_id: row exists, file promoted.
        new_with_row = _get_doc_row(db_session, new_with.id)
        assert new_with_row is not None and new_with_row.file_id == new_with_file_id
        new_with_record = _get_filerecord(db_session, new_with_file_id)
        assert new_with_record is not None
        assert new_with_record.file_origin == FileOrigin.CONNECTOR

        # New doc without file_id: row exists, no file_record involvement.
        new_without_row = _get_doc_row(db_session, new_without.id)
        assert new_without_row is not None and new_without_row.file_id is None
