"""External dependency unit tests for the per-cc-pair processor.

The processor `process_targets_for_cc_pair` owns the path between
target rows and the indexing pipeline: instantiate connector → check
Resolver capability → convert targets to ConnectorFailure inputs →
stream Documents → run pipeline once per (cc_pair × search_settings)
synthetic IndexAttempt.

`instantiate_connector` and the pipeline call are mocked here so the
test stays focused on the processor's own decisions (capability gate,
ConnectorFailure rehydration, landed/failed bucketing). The full
end-to-end path lands when the integration test suite covers a real
Drive connector reindex run.
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.indexing.run_targeted_reindex import process_targets_for_cc_pair
from onyx.connectors.interfaces import Resolver
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import DocumentSource
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import TextSection
from onyx.db.enums import IndexingStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError
from onyx.db.models import TargetedReindexJob
from onyx.db.models import TargetedReindexJobTarget
from onyx.db.search_settings import get_current_search_settings
from onyx.db.targeted_reindex import create_targeted_reindex_job
from onyx.db.targeted_reindex import resolve_error_ids_to_targets
from onyx.db.targeted_reindex import targets_to_connector_failures
from onyx.db.targeted_reindex import TargetSpec
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    try:
        yield pair
    finally:
        db_session.query(TargetedReindexJobTarget).delete(synchronize_session="fetch")
        db_session.query(IndexAttemptError).delete(synchronize_session="fetch")
        db_session.query(IndexAttempt).filter(
            IndexAttempt.connector_credential_pair_id == pair.id
        ).delete(synchronize_session="fetch")
        db_session.query(TargetedReindexJob).delete(synchronize_session="fetch")
        db_session.commit()
        cleanup_cc_pair(db_session, pair)


def _doc(doc_id: str) -> Document:
    return Document(
        id=doc_id,
        sections=[TextSection(text="content for %s" % doc_id, link=None)],
        source=DocumentSource.NOT_APPLICABLE,
        semantic_identifier=doc_id,
        metadata={},
    )


class _StubResolver(Resolver):
    """Minimal Resolver used in tests. Yields whatever the test setup hands it."""

    def __init__(self, yields: list[Document | ConnectorFailure]) -> None:
        self._yields = yields

    def reindex(
        self,
        errors: list[ConnectorFailure],
        include_permissions: bool = False,
    ) -> Generator[Document | ConnectorFailure | HierarchyNode, None, None]:
        del errors, include_permissions
        yield from self._yields

    # Required by BaseConnector but not exercised by the processor.
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        del credentials
        return None

    def validate_connector_settings(self) -> None:
        return None


class _StubBaseConnector:
    """Stand-in for a connector that does NOT implement Resolver, used to
    test the unsupported-source short-circuit."""

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        del credentials
        return None


def _job_with_targets(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,  # noqa: ARG001  # documents test wiring
    targets: list[TargetSpec],
) -> tuple[list[TargetedReindexJobTarget], list[IndexAttempt]]:
    result = create_targeted_reindex_job(
        db_session=db_session, requested_by_user_id=None, targets=targets
    )
    target_rows = (
        db_session.query(TargetedReindexJobTarget)
        .filter(
            TargetedReindexJobTarget.targeted_reindex_job_id
            == result.targeted_reindex_job_id
        )
        .all()
    )
    attempts = (
        db_session.query(IndexAttempt)
        .filter(IndexAttempt.targeted_reindex_job_id == result.targeted_reindex_job_id)
        .all()
    )
    return target_rows, attempts


def test_unsupported_connector_marks_all_targets_failed(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    target_rows, attempts = _job_with_targets(
        db_session,
        cc_pair,
        [
            TargetSpec(cc_pair_id=cc_pair.id, document_id="d1"),
            TargetSpec(cc_pair_id=cc_pair.id, document_id="d2"),
        ],
    )

    with patch(
        "onyx.background.indexing.run_targeted_reindex.instantiate_connector",
        return_value=_StubBaseConnector(),
    ):
        result = process_targets_for_cc_pair(
            cc_pair_id=cc_pair.id,
            targets=target_rows,
            attempts=attempts,
            tenant_id=TEST_TENANT_ID,
            db_session=db_session,
        )

    assert result.unsupported is True
    assert result.landed_doc_ids == set()
    assert result.failed_doc_ids == {"d1", "d2"}


def test_resolver_yields_all_docs_lands_them_all(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    target_rows, attempts = _job_with_targets(
        db_session,
        cc_pair,
        [
            TargetSpec(cc_pair_id=cc_pair.id, document_id="d1"),
            TargetSpec(cc_pair_id=cc_pair.id, document_id="d2"),
        ],
    )
    stub = _StubResolver(yields=[_doc("d1"), _doc("d2")])

    fake_pipeline_result = MagicMock(failures=[])

    with (
        patch(
            "onyx.background.indexing.run_targeted_reindex.instantiate_connector",
            return_value=stub,
        ),
        patch(
            "onyx.background.indexing.run_targeted_reindex.run_indexing_pipeline",
            return_value=fake_pipeline_result,
        ),
    ):
        result = process_targets_for_cc_pair(
            cc_pair_id=cc_pair.id,
            targets=target_rows,
            attempts=attempts,
            tenant_id=TEST_TENANT_ID,
            db_session=db_session,
        )

    assert result.unsupported is False
    assert result.landed_doc_ids == {"d1", "d2"}
    assert result.failed_doc_ids == set()


def test_connector_failure_yields_route_to_failed_doc_ids(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    target_rows, attempts = _job_with_targets(
        db_session,
        cc_pair,
        [
            TargetSpec(cc_pair_id=cc_pair.id, document_id="d1"),
            TargetSpec(cc_pair_id=cc_pair.id, document_id="d2"),
        ],
    )
    stub = _StubResolver(
        yields=[
            _doc("d1"),
            ConnectorFailure(
                failed_document=DocumentFailure(document_id="d2"),
                failure_message="still 403",
            ),
        ],
    )
    fake_pipeline_result = MagicMock(failures=[])

    with (
        patch(
            "onyx.background.indexing.run_targeted_reindex.instantiate_connector",
            return_value=stub,
        ),
        patch(
            "onyx.background.indexing.run_targeted_reindex.run_indexing_pipeline",
            return_value=fake_pipeline_result,
        ),
    ):
        result = process_targets_for_cc_pair(
            cc_pair_id=cc_pair.id,
            targets=target_rows,
            attempts=attempts,
            tenant_id=TEST_TENANT_ID,
            db_session=db_session,
        )

    assert result.landed_doc_ids == {"d1"}
    assert result.failed_doc_ids == {"d2"}


def test_doc_never_yielded_is_marked_failed(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    """If the connector silently drops a doc (yields neither Document
    nor ConnectorFailure for it), the processor must still treat it as
    failed so still_failing_count reflects reality."""
    target_rows, attempts = _job_with_targets(
        db_session,
        cc_pair,
        [
            TargetSpec(cc_pair_id=cc_pair.id, document_id="d1"),
            TargetSpec(cc_pair_id=cc_pair.id, document_id="d2"),
        ],
    )
    # Stub yields only d1.
    stub = _StubResolver(yields=[_doc("d1")])
    fake_pipeline_result = MagicMock(failures=[])

    with (
        patch(
            "onyx.background.indexing.run_targeted_reindex.instantiate_connector",
            return_value=stub,
        ),
        patch(
            "onyx.background.indexing.run_targeted_reindex.run_indexing_pipeline",
            return_value=fake_pipeline_result,
        ),
    ):
        result = process_targets_for_cc_pair(
            cc_pair_id=cc_pair.id,
            targets=target_rows,
            attempts=attempts,
            tenant_id=TEST_TENANT_ID,
            db_session=db_session,
        )

    assert result.landed_doc_ids == {"d1"}
    assert result.failed_doc_ids == {"d2"}


def test_targets_to_connector_failures_rehydrates_error_context(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> None:
    settings = get_current_search_settings(db_session)
    parent = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=settings.id,
        from_beginning=False,
        status=IndexingStatus.FAILED,
    )
    db_session.add(parent)
    db_session.commit()
    db_session.refresh(parent)

    err = IndexAttemptError(
        index_attempt_id=parent.id,
        connector_credential_pair_id=cc_pair.id,
        document_id="from-error",
        document_link="https://example/x",
        failure_message="403 forbidden",
        is_resolved=False,
    )
    db_session.add(err)
    db_session.commit()
    db_session.refresh(err)

    derived, _ = resolve_error_ids_to_targets(db_session, [err.id])
    arbitrary = [TargetSpec(cc_pair_id=cc_pair.id, document_id="arbitrary")]
    target_rows, _ = _job_with_targets(db_session, cc_pair, [*derived, *arbitrary])

    failures = targets_to_connector_failures(target_rows, db_session)

    by_doc = {
        f.failed_document.document_id: f
        for f in failures
        if f.failed_document is not None
    }
    # Failure-derived target carries the original error's link + message.
    rehydrated = by_doc["from-error"]
    assert rehydrated.failure_message == "403 forbidden"
    assert (
        rehydrated.failed_document is not None
        and rehydrated.failed_document.document_link == "https://example/x"
    )
    # Arbitrary target gets a synthesized message; no link.
    synth = by_doc["arbitrary"]
    assert "Targeted reindex requested by admin" in synth.failure_message
    assert (
        synth.failed_document is not None
        and synth.failed_document.document_link is None
    )
