"""External dependency unit tests for the file_id cleanup that runs alongside
document deletion across the three deletion paths:

    1. `document_by_cc_pair_cleanup_task` (pruning + connector deletion)
    2. `delete_ingestion_doc` (public ingestion API DELETE)
    3. `delete_all_documents_for_connector_credential_pair` (index swap)

Each path captures attached `Document.file_id`s before the row is removed and
best-effort deletes the underlying files after the DB commit.
"""

from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.shared.tasks import document_by_cc_pair_cleanup_task
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.document import delete_all_documents_for_connector_credential_pair
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare
from onyx.server.onyx_api.ingestion import delete_ingestion_doc
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import get_doc_row
from tests.external_dependency_unit.indexing_helpers import get_filerecord
from tests.external_dependency_unit.indexing_helpers import make_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_doc
from tests.external_dependency_unit.indexing_helpers import stage_file

# ---------------------------------------------------------------------------
# Helpers (file-local)
# ---------------------------------------------------------------------------


def _index_doc(
    db_session: Session,
    doc: Document,
    attempt_metadata: IndexAttemptMetadata,
) -> None:
    """Run the doc through the upsert pipeline so the row + cc_pair mapping
    exist (so deletion paths have something to find)."""
    index_doc_batch_prepare(
        documents=[doc],
        index_attempt_metadata=attempt_metadata,
        db_session=db_session,
        ignore_time_skip=True,
    )
    db_session.commit()


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
def second_cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    """A second cc_pair, used to test the count > 1 branch."""
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


class TestDeleteAllDocumentsForCcPair:
    """Path 3: bulk delete during index swap (`INSTANT` switchover)."""

    def test_cleans_up_files_for_all_docs(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        file_id_a = stage_file(content=b"a")
        file_id_b = stage_file(content=b"b")
        doc_a = make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id_a)
        doc_b = make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id_b)

        _index_doc(db_session, doc_a, attempt_metadata)
        _index_doc(db_session, doc_b, attempt_metadata)

        assert get_filerecord(db_session, file_id_a) is not None
        assert get_filerecord(db_session, file_id_b) is not None

        delete_all_documents_for_connector_credential_pair(
            db_session=db_session,
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
        )

        assert get_doc_row(db_session, doc_a.id) is None
        assert get_doc_row(db_session, doc_b.id) is None
        assert get_filerecord(db_session, file_id_a) is None
        assert get_filerecord(db_session, file_id_b) is None

    def test_handles_mixed_docs_with_and_without_file_ids(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        attempt_metadata: IndexAttemptMetadata,
    ) -> None:
        """Docs without file_id should be cleanly removed — no errors,
        no spurious file_store calls."""
        file_id = stage_file()
        doc_with = make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id)
        doc_without = make_doc(f"doc-{uuid4().hex[:8]}", file_id=None)

        _index_doc(db_session, doc_with, attempt_metadata)
        _index_doc(db_session, doc_without, attempt_metadata)

        delete_all_documents_for_connector_credential_pair(
            db_session=db_session,
            connector_id=cc_pair.connector_id,
            credential_id=cc_pair.credential_id,
        )

        assert get_doc_row(db_session, doc_with.id) is None
        assert get_doc_row(db_session, doc_without.id) is None
        assert get_filerecord(db_session, file_id) is None


class TestDeleteIngestionDoc:
    """Path 2: public ingestion API DELETE endpoint."""

    def test_cleans_up_file_for_ingestion_api_doc(
        self,
        db_session: Session,
        attempt_metadata: IndexAttemptMetadata,
        tenant_context: None,  # noqa: ARG002
        initialize_file_store: None,  # noqa: ARG002
    ) -> None:
        file_id = stage_file()
        doc = make_doc(
            f"doc-{uuid4().hex[:8]}",
            file_id=file_id,
            from_ingestion_api=True,
        )

        _index_doc(db_session, doc, attempt_metadata)
        assert get_filerecord(db_session, file_id) is not None

        # Patch out Vespa — we're testing the file cleanup, not the document
        # index integration.
        with patch(
            "onyx.server.onyx_api.ingestion.get_all_document_indices",
            return_value=[],
        ):
            delete_ingestion_doc(
                document_id=doc.id,
                _=MagicMock(),  # auth dep — not used by the function body
                db_session=db_session,
            )

        assert get_doc_row(db_session, doc.id) is None
        assert get_filerecord(db_session, file_id) is None


class TestDocumentByCcPairCleanupTask:
    """Path 1: per-doc cleanup task fired by pruning / connector deletion."""

    def test_count_1_branch_cleans_up_file(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        attempt_metadata: IndexAttemptMetadata,
        full_deployment_setup: None,  # noqa: ARG002
    ) -> None:
        """When the doc has exactly one cc_pair reference, the full delete
        path runs and the attached file is reaped."""
        file_id = stage_file()
        doc = make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id)
        _index_doc(db_session, doc, attempt_metadata)

        assert get_filerecord(db_session, file_id) is not None

        # Patch out Vespa interaction — no chunks were ever written, and we're
        # not testing the document index here.
        with patch(
            "onyx.background.celery.tasks.shared.tasks.get_all_document_indices",
            return_value=[],
        ):
            result = document_by_cc_pair_cleanup_task.apply(
                args=(
                    doc.id,
                    cc_pair.connector_id,
                    cc_pair.credential_id,
                    TEST_TENANT_ID,
                ),
            )

        assert result.successful(), result.traceback
        assert get_doc_row(db_session, doc.id) is None
        assert get_filerecord(db_session, file_id) is None

    def test_count_gt_1_branch_preserves_file(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        second_cc_pair: ConnectorCredentialPair,
        attempt_metadata: IndexAttemptMetadata,
        full_deployment_setup: None,  # noqa: ARG002
    ) -> None:
        """When the doc is referenced by another cc_pair, only the mapping
        for the detaching cc_pair is removed. The file MUST stay because
        the doc and its file are still owned by the remaining cc_pair."""
        file_id = stage_file()
        doc = make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_id)
        _index_doc(db_session, doc, attempt_metadata)

        # Attach the same doc to a second cc_pair so refcount becomes 2.
        upsert_document_by_connector_credential_pair(
            db_session,
            second_cc_pair.connector_id,
            second_cc_pair.credential_id,
            [doc.id],
        )
        db_session.commit()

        with patch(
            "onyx.background.celery.tasks.shared.tasks.get_all_document_indices",
            return_value=[],
        ):
            result = document_by_cc_pair_cleanup_task.apply(
                args=(
                    doc.id,
                    cc_pair.connector_id,
                    cc_pair.credential_id,
                    TEST_TENANT_ID,
                ),
            )

        assert result.successful(), result.traceback
        # Document row still exists (other cc_pair owns it).
        assert get_doc_row(db_session, doc.id) is not None
        # File MUST still exist.
        record = get_filerecord(db_session, file_id)
        assert record is not None
