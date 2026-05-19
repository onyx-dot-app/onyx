"""External dependency unit tests for `document_by_cc_pair_bulk_cleanup_task`.

The bulk task is the unit of work for connector deletion / pruning after the
1.7M-task pgbouncer-saturation incident on 2026-05-18. It processes a whole
batch of documents in three phases:

    Phase 1 — read DB state, bucket into delete / update / skip.
    Phase 2 — document-index I/O without a DB session held.
    Phase 3 — write back in a fresh transaction.

Tests below cover each bucket separately, the mixed case, the empty-input
short-circuit, and the reconciliation paths fired by max-retries and
SoftTimeLimitExceeded.
"""

from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from unittest.mock import patch
from uuid import uuid4

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.shared.tasks import (
    document_by_cc_pair_bulk_cleanup_task,
)
from onyx.connectors.models import Document
from onyx.connectors.models import IndexAttemptMetadata
from onyx.db.document import get_document_connector_count
from onyx.db.document import upsert_document_by_connector_credential_pair
from onyx.db.models import ConnectorCredentialPair
from onyx.indexing.indexing_pipeline import index_doc_batch_prepare
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import get_doc_row
from tests.external_dependency_unit.indexing_helpers import get_filerecord
from tests.external_dependency_unit.indexing_helpers import make_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_doc
from tests.external_dependency_unit.indexing_helpers import stage_file

_TASK_MODULE = "onyx.background.celery.tasks.shared.tasks"


def _index_docs(
    db_session: Session,
    docs: list[Document],
    attempt_metadata: IndexAttemptMetadata,
) -> None:
    """Push every doc through the upsert pipeline so the row + cc_pair
    mapping exist for the cleanup task to find."""
    index_doc_batch_prepare(
        documents=docs,
        index_attempt_metadata=attempt_metadata,
        db_session=db_session,
        ignore_time_skip=True,
    )
    db_session.commit()


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


@pytest.fixture
def second_attempt_metadata(
    second_cc_pair: ConnectorCredentialPair,
) -> IndexAttemptMetadata:
    return IndexAttemptMetadata(
        connector_id=second_cc_pair.connector_id,
        credential_id=second_cc_pair.credential_id,
        attempt_id=None,
        request_id="test-request-2",
    )


class TestBulkCleanupTaskDeleteBucket:
    """All docs in the batch have count == 1 → fully deleted from PG and the
    attached files are reaped."""

    def test_all_delete_batch_removes_docs_and_files(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        attempt_metadata: IndexAttemptMetadata,
        full_deployment_setup: None,  # noqa: ARG002
    ) -> None:
        file_ids = [stage_file(content=f"doc-{i}".encode()) for i in range(5)]
        docs = [
            make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_ids[i]) for i in range(5)
        ]
        _index_docs(db_session, docs, attempt_metadata)

        for file_id in file_ids:
            assert get_filerecord(db_session, file_id) is not None

        with patch(
            f"{_TASK_MODULE}.get_all_document_indices",
            return_value=[],
        ):
            result = document_by_cc_pair_bulk_cleanup_task.apply(
                kwargs=dict(
                    document_ids=[doc.id for doc in docs],
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                    tenant_id=TEST_TENANT_ID,
                ),
            )

        assert result.successful(), result.traceback
        assert result.result is True
        for doc in docs:
            assert get_doc_row(db_session, doc.id) is None
        for file_id in file_ids:
            assert get_filerecord(db_session, file_id) is None


class TestBulkCleanupTaskUpdateBucket:
    """All docs in the batch have count > 1 → only the detaching cc_pair link
    is removed; doc rows and files survive."""

    def test_all_update_batch_preserves_docs_and_files(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        second_cc_pair: ConnectorCredentialPair,
        attempt_metadata: IndexAttemptMetadata,
        full_deployment_setup: None,  # noqa: ARG002
    ) -> None:
        file_ids = [stage_file(content=f"shared-{i}".encode()) for i in range(4)]
        docs = [
            make_doc(f"doc-{uuid4().hex[:8]}", file_id=file_ids[i]) for i in range(4)
        ]
        _index_docs(db_session, docs, attempt_metadata)

        # Attach every doc to a second cc_pair so refcount becomes 2.
        upsert_document_by_connector_credential_pair(
            db_session,
            second_cc_pair.connector_id,
            second_cc_pair.credential_id,
            [doc.id for doc in docs],
        )
        db_session.commit()

        # Pre-stamp last_synced to an old value so we can check the bulk
        # mark_documents_as_synced ran.
        for doc in docs:
            row = get_doc_row(db_session, doc.id)
            assert row is not None
            row.last_synced = datetime(2000, 1, 1, tzinfo=timezone.utc)
        db_session.commit()

        with patch(
            f"{_TASK_MODULE}.get_all_document_indices",
            return_value=[],
        ):
            result = document_by_cc_pair_bulk_cleanup_task.apply(
                kwargs=dict(
                    document_ids=[doc.id for doc in docs],
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                    tenant_id=TEST_TENANT_ID,
                ),
            )

        assert result.successful(), result.traceback

        for doc in docs:
            # Doc row still exists — other cc_pair owns it.
            row = get_doc_row(db_session, doc.id)
            assert row is not None
            # last_synced was stamped by the bulk helper.
            assert row.last_synced is not None
            assert row.last_synced > datetime(2020, 1, 1, tzinfo=timezone.utc)
            # File still exists.
            assert doc.file_id is not None
            assert get_filerecord(db_session, doc.file_id) is not None
            # cc_pair link from the detaching pair is gone; refcount is now 1.
            assert get_document_connector_count(db_session, doc.id) == 1


class TestBulkCleanupTaskMixedBatch:
    """Mixed bucket — every code path runs in one invocation."""

    def test_mixed_batch_routes_each_doc_correctly(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        second_cc_pair: ConnectorCredentialPair,
        attempt_metadata: IndexAttemptMetadata,
        full_deployment_setup: None,  # noqa: ARG002
    ) -> None:
        # 3 delete-bucket docs (only on cc_pair).
        delete_file_ids = [stage_file(content=f"del-{i}".encode()) for i in range(3)]
        delete_docs = [
            make_doc(f"del-{uuid4().hex[:8]}", file_id=delete_file_ids[i])
            for i in range(3)
        ]
        _index_docs(db_session, delete_docs, attempt_metadata)

        # 3 update-bucket docs (on cc_pair AND second_cc_pair).
        update_file_ids = [stage_file(content=f"upd-{i}".encode()) for i in range(3)]
        update_docs = [
            make_doc(f"upd-{uuid4().hex[:8]}", file_id=update_file_ids[i])
            for i in range(3)
        ]
        _index_docs(db_session, update_docs, attempt_metadata)
        upsert_document_by_connector_credential_pair(
            db_session,
            second_cc_pair.connector_id,
            second_cc_pair.credential_id,
            [doc.id for doc in update_docs],
        )
        db_session.commit()

        # 2 skip-bucket doc IDs that never had any cc_pair attachment.
        # Just IDs that don't appear in DocumentByConnectorCredentialPair.
        skip_doc_ids = [f"missing-{uuid4().hex[:8]}" for _ in range(2)]

        all_doc_ids = (
            [doc.id for doc in delete_docs]
            + [doc.id for doc in update_docs]
            + skip_doc_ids
        )

        with patch(
            f"{_TASK_MODULE}.get_all_document_indices",
            return_value=[],
        ):
            result = document_by_cc_pair_bulk_cleanup_task.apply(
                kwargs=dict(
                    document_ids=all_doc_ids,
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                    tenant_id=TEST_TENANT_ID,
                ),
            )

        assert result.successful(), result.traceback

        # Delete bucket: gone.
        for doc in delete_docs:
            assert get_doc_row(db_session, doc.id) is None
        for file_id in delete_file_ids:
            assert get_filerecord(db_session, file_id) is None

        # Update bucket: rows + files survive; refcount on cc_pair link drops
        # to 1.
        for doc in update_docs:
            assert get_doc_row(db_session, doc.id) is not None
            assert doc.file_id is not None
            assert get_filerecord(db_session, doc.file_id) is not None
            assert get_document_connector_count(db_session, doc.id) == 1

        # Skip bucket: no errors raised on missing-from-pg doc IDs.


class TestBulkCleanupTaskEmptyBatch:
    """Empty input short-circuits without raising."""

    def test_empty_document_ids_returns_true_without_side_effects(
        self,
        cc_pair: ConnectorCredentialPair,
        full_deployment_setup: None,  # noqa: ARG002
    ) -> None:
        # No patch on get_all_document_indices needed — the empty path returns
        # before ever touching it.
        result = document_by_cc_pair_bulk_cleanup_task.apply(
            kwargs=dict(
                document_ids=[],
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
                tenant_id=TEST_TENANT_ID,
            ),
        )

        assert result.successful(), result.traceback
        assert result.result is True


class TestBulkCleanupTaskReconciliation:
    """Failure-path tests: max retries and SoftTimeLimitExceeded both bulk-mark
    every doc in the batch as modified and detach the cc_pair, so the stale-doc
    reconciler can catch up out-of-band."""

    def test_soft_time_limit_marks_batch_for_reconciliation(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        attempt_metadata: IndexAttemptMetadata,
        full_deployment_setup: None,  # noqa: ARG002
    ) -> None:
        docs = [make_doc(f"stl-{uuid4().hex[:8]}") for _ in range(4)]
        _index_docs(db_session, docs, attempt_metadata)

        # Stamp last_modified to an old value so we can detect a re-stamp.
        for doc in docs:
            row = get_doc_row(db_session, doc.id)
            assert row is not None
            row.last_modified = datetime(2000, 1, 1, tzinfo=timezone.utc)
        db_session.commit()

        # Force SoftTimeLimitExceeded at the document-index acquisition point.
        with patch(
            f"{_TASK_MODULE}.get_all_document_indices",
            side_effect=SoftTimeLimitExceeded(),
        ):
            result = document_by_cc_pair_bulk_cleanup_task.apply(
                kwargs=dict(
                    document_ids=[doc.id for doc in docs],
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                    tenant_id=TEST_TENANT_ID,
                ),
            )

        assert result.successful(), result.traceback
        # Task returns False on non-SUCCEEDED completion status.
        assert result.result is False

        # Every doc still exists (no destructive action taken on STL) but the
        # cc_pair link is gone and last_modified was bumped, so the
        # reconciler picks it up.
        for doc in docs:
            row = get_doc_row(db_session, doc.id)
            assert row is not None
            assert row.last_modified is not None
            assert row.last_modified > datetime(2020, 1, 1, tzinfo=timezone.utc)
            assert get_document_connector_count(db_session, doc.id) == 0

    def test_max_retries_marks_batch_for_reconciliation(
        self,
        db_session: Session,
        cc_pair: ConnectorCredentialPair,
        attempt_metadata: IndexAttemptMetadata,
        full_deployment_setup: None,  # noqa: ARG002
    ) -> None:
        docs = [make_doc(f"retry-{uuid4().hex[:8]}") for _ in range(4)]
        _index_docs(db_session, docs, attempt_metadata)

        for doc in docs:
            row = get_doc_row(db_session, doc.id)
            assert row is not None
            row.last_modified = datetime(2000, 1, 1, tzinfo=timezone.utc)
        db_session.commit()

        # Force a generic Exception with the retry counter pre-set to the
        # max so the task takes the reconciliation branch instead of
        # scheduling another retry. `Task.apply(retries=...)` populates
        # `self.request.retries` directly.
        with patch(
            f"{_TASK_MODULE}.get_all_document_indices",
            side_effect=RuntimeError("simulated index failure"),
        ):
            result = document_by_cc_pair_bulk_cleanup_task.apply(
                kwargs=dict(
                    document_ids=[doc.id for doc in docs],
                    connector_id=cc_pair.connector_id,
                    credential_id=cc_pair.credential_id,
                    tenant_id=TEST_TENANT_ID,
                ),
                retries=3,  # >= DOCUMENT_BY_CC_PAIR_CLEANUP_MAX_RETRIES
            )

        assert result.successful(), result.traceback
        assert result.result is False

        for doc in docs:
            row = get_doc_row(db_session, doc.id)
            assert row is not None
            assert row.last_modified is not None
            assert row.last_modified > datetime(2020, 1, 1, tzinfo=timezone.utc)
            assert get_document_connector_count(db_session, doc.id) == 0
