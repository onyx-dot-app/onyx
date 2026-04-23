"""External dependency unit tests for `index_doc_batch_prepare`.

Validates the file_id lifecycle that runs alongside the document upsert:

    * `document.file_id` is written on insert AND on conflict (upsert path)
    * Newly-staged files get promoted from INDEXING_STAGING -> CONNECTOR
    * Replaced files are deleted from both `file_record` and S3
    * No-op when the file_id is unchanged

Uses real PostgreSQL + real S3/MinIO via the file store.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import get_doc_row
from tests.external_dependency_unit.indexing_helpers import get_filerecord
from tests.external_dependency_unit.indexing_helpers import make_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_doc
from tests.external_dependency_unit.indexing_helpers import stage_file

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        cleanup_cc_pair(db_session, pair)


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
        doc = make_doc(f"doc-{uuid4().hex[:8]}", file_id=None)

        index_doc_batch_prepare(
            documents=[doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        row = get_doc_row(db_session, doc.id)
        assert row is not None
        assert row.file_id is None

    def test_new_doc_with_staged_file_id_promotes_to_connector(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        file_id = stage_file()
        doc = make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id)

        index_doc_batch_prepare(
            documents=[doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        row = get_doc_row(db_session, doc.id)
        assert row is not None and row.file_id == file_id

        record = get_filerecord(db_session, file_id)
        assert record is not None
        assert record.file_origin == FileOrigin.CONNECTOR


class TestExistingDocuments:
    """Re-index path — a `document` row already exists with some file_id."""

    def test_unchanged_file_id_is_noop(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        file_id = stage_file()
        doc = make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id)

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

        record = get_filerecord(db_session, file_id)
        assert record is not None
        assert record.file_origin == FileOrigin.CONNECTOR

        row = get_doc_row(db_session, doc.id)
        assert row is not None and row.file_id == file_id

    def test_swapping_file_id_promotes_new_and_deletes_old(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        old_file_id = stage_file(content=b"old bytes")
        doc = make_doc(f"doc-{uuid4().hex[:8]}", file_id=old_file_id)

        index_doc_batch_prepare(
            documents=[doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        # Re-fetch produces a new staged file_id for the same doc.
        new_file_id = stage_file(content=b"new bytes")
        doc_v2 = make_doc(doc.id, file_id=new_file_id)

        index_doc_batch_prepare(
            documents=[doc_v2],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        row = get_doc_row(db_session, doc.id)
        assert row is not None and row.file_id == new_file_id

        new_record = get_filerecord(db_session, new_file_id)
        assert new_record is not None
        assert new_record.file_origin == FileOrigin.CONNECTOR

        # Old file_record + S3 object are gone.
        assert get_filerecord(db_session, old_file_id) is None

    def test_clearing_file_id_deletes_old_and_nulls_column(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        old_file_id = stage_file()
        doc = make_doc(f"doc-{uuid4().hex[:8]}", file_id=old_file_id)

        index_doc_batch_prepare(
            documents=[doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        # Connector opts out on next run — yields the doc without a file_id.
        doc_v2 = make_doc(doc.id, file_id=None)

        index_doc_batch_prepare(
            documents=[doc_v2],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        row = get_doc_row(db_session, doc.id)
        assert row is not None and row.file_id is None
        assert get_filerecord(db_session, old_file_id) is None


class TestBatchHandling:
    """Mixed batches — multiple docs at different lifecycle states in one call."""

    def test_mixed_batch_each_doc_handled_independently(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        # Pre-seed an existing doc with a file_id we'll swap.
        existing_old_id = stage_file(content=b"existing-old")
        existing_doc = make_doc(f"doc-{uuid4().hex[:8]}", file_id=existing_old_id)
        index_doc_batch_prepare(
            documents=[existing_doc],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        # Now: swap the existing one, add a brand-new doc with file_id, and a
        # brand-new doc without file_id.
        swap_new_id = stage_file(content=b"existing-new")
        new_with_file_id = stage_file(content=b"new-with-file")
        existing_v2 = make_doc(existing_doc.id, file_id=swap_new_id)
        new_with = make_doc(f"doc-{uuid4().hex[:8]}", file_id=new_with_file_id)
        new_without = make_doc(f"doc-{uuid4().hex[:8]}", file_id=None)

        index_doc_batch_prepare(
            documents=[existing_v2, new_with, new_without],
            index_attempt_metadata=attempt_metadata,
            db_session=db_session,
            ignore_time_skip=True,
        )
        db_session.commit()

        # Existing doc was swapped: old file gone, new file promoted.
        existing_row = get_doc_row(db_session, existing_doc.id)
        assert existing_row is not None and existing_row.file_id == swap_new_id
        assert get_filerecord(db_session, existing_old_id) is None
        swap_record = get_filerecord(db_session, swap_new_id)
        assert swap_record is not None
        assert swap_record.file_origin == FileOrigin.CONNECTOR

        # New doc with file_id: row exists, file promoted.
        new_with_row = get_doc_row(db_session, new_with.id)
        assert new_with_row is not None and new_with_row.file_id == new_with_file_id
        new_with_record = get_filerecord(db_session, new_with_file_id)
        assert new_with_record is not None
        assert new_with_record.file_origin == FileOrigin.CONNECTOR

        # New doc without file_id: row exists, no file_record involvement.
        new_without_row = get_doc_row(db_session, new_without.id)
        assert new_without_row is not None and new_without_row.file_id is None
