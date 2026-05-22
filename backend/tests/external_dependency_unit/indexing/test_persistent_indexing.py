"""External-dependency-unit tests for PERSISTENT_INDEXING.

Exercises `run_docfetching_entrypoint` against a mock connector that either:
  (a) yields docs/failures then raises an unhandled exception, or
  (b) yields more `ConnectorFailure`s than the >3-failures-AND->10%-ratio
      threshold would normally tolerate.

In both cases, with PERSISTENT_INDEXING patched to True, the attempt must
not be marked FAILED; instead a `ConnectorFailure` is recorded against
the attempt and `check_indexing_completion` can later resolve it to
COMPLETED_WITH_ERRORS. With PERSISTENT_INDEXING False (default), the
attempt is marked FAILED as before.

Runs against real Postgres + real file_store; the celery `send_task`
is mocked because docprocessing is a separate pod and not under test.
"""

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.background.indexing.run_docfetching import run_docfetching_entrypoint
from onyx.configs.constants import DocumentSource
from onyx.connectors import factory as connector_factory
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import EntityFailure
from onyx.connectors.models import TextSection
from onyx.db.enums import EmbeddingPrecision
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import get_index_attempt_errors
from onyx.db.models import IndexAttempt
from onyx.db.models import SearchSettings
from tests.external_dependency_unit.constants import TEST_TENANT_ID
from tests.external_dependency_unit.indexing_helpers import cleanup_cc_pair
from tests.external_dependency_unit.indexing_helpers import make_cc_pair

# ---------------------------------------------------------------------------
# Mock checkpointed connector with configurable failure behavior
# ---------------------------------------------------------------------------


class _MockCheckpoint(ConnectorCheckpoint):
    """Minimal checkpoint type for the mock connector."""

    pass


# Module-level config so the connector instance (constructed by the factory
# with empty kwargs) can pick up test-specific behavior.
_MOCK_BEHAVIOR: dict[str, Any] = {
    "docs": [],
    "failures": [],
    "raise_at_end": False,
    "raise_message": "simulated unhandled connector error",
}


def _reset_mock_behavior() -> None:
    _MOCK_BEHAVIOR["docs"] = []
    _MOCK_BEHAVIOR["failures"] = []
    _MOCK_BEHAVIOR["raise_at_end"] = False
    _MOCK_BEHAVIOR["raise_message"] = "simulated unhandled connector error"


class MockCheckpointedConnector(CheckpointedConnector[_MockCheckpoint]):
    """Yields whatever's configured in `_MOCK_BEHAVIOR`, then optionally raises.

    Empty-kwargs construction is required because the production factory
    calls `connector_class(**connector_specific_config)` and the cc_pair
    seeded in the test has an empty config.
    """

    def __init__(self, **_ignored: Any) -> None:
        pass

    def load_credentials(
        self,
        credentials: dict[str, Any],  # noqa: ARG002
    ) -> dict[str, Any] | None:
        return None

    def build_dummy_checkpoint(self) -> _MockCheckpoint:
        return _MockCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> _MockCheckpoint:
        return _MockCheckpoint.model_validate_json(checkpoint_json)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: _MockCheckpoint,  # noqa: ARG002
    ) -> CheckpointOutput[_MockCheckpoint]:
        for doc in _MOCK_BEHAVIOR["docs"]:
            yield doc
        for failure in _MOCK_BEHAVIOR["failures"]:
            yield failure
        if _MOCK_BEHAVIOR["raise_at_end"]:
            raise RuntimeError(_MOCK_BEHAVIOR["raise_message"])
        return _MockCheckpoint(has_more=False)

    def retrieve_all_slim_documents(self) -> GenerateSlimDocumentOutput:
        yield from []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(doc_id: str) -> Document:
    return Document(
        id=doc_id,
        source=DocumentSource.MOCK_CONNECTOR,
        semantic_identifier=f"sem-{doc_id}",
        sections=[TextSection(text="payload", link=f"https://example.com/{doc_id}")],
        metadata={},
    )


def _make_doc_failure(doc_id: str) -> ConnectorFailure:
    return ConnectorFailure(
        failed_document=DocumentFailure(document_id=doc_id),
        failure_message=f"yielded failure for {doc_id}",
    )


def _seed_attempt(db_session: Session) -> tuple[int, int, int]:
    """Create cc_pair + search_settings + index_attempt rows.

    Returns (cc_pair_id, search_settings_id, index_attempt_id)."""
    cc_pair = make_cc_pair(db_session)

    search_settings = SearchSettings(
        model_name="test-model",
        model_dim=768,
        normalize=True,
        query_prefix="",
        passage_prefix="",
        status=IndexModelStatus.PRESENT,
        index_name=f"test_index_{uuid4().hex[:8]}",
        embedding_precision=EmbeddingPrecision.FLOAT,
    )
    db_session.add(search_settings)
    db_session.commit()
    db_session.refresh(search_settings)

    index_attempt = IndexAttempt(
        connector_credential_pair_id=cc_pair.id,
        search_settings_id=search_settings.id,
        from_beginning=False,
        status=IndexingStatus.NOT_STARTED,
        celery_task_id=f"test-task-{uuid4().hex[:8]}",
    )
    db_session.add(index_attempt)
    db_session.commit()
    db_session.refresh(index_attempt)

    return cc_pair.id, search_settings.id, index_attempt.id


def _teardown_attempt(
    db_session: Session, cc_pair_id: int, search_settings_id: int, attempt_id: int
) -> None:
    db_session.query(IndexAttempt).filter(IndexAttempt.id == attempt_id).delete(
        synchronize_session="fetch"
    )
    db_session.query(SearchSettings).filter(
        SearchSettings.id == search_settings_id
    ).delete(synchronize_session="fetch")
    db_session.commit()
    from onyx.db.models import ConnectorCredentialPair

    cc_pair = (
        db_session.query(ConnectorCredentialPair)
        .filter(ConnectorCredentialPair.id == cc_pair_id)
        .one_or_none()
    )
    if cc_pair is not None:
        cleanup_cc_pair(db_session, cc_pair)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def register_mock_connector(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Inject MockCheckpointedConnector into the production factory cache."""
    _reset_mock_behavior()
    monkeypatch.setitem(
        connector_factory._connector_cache,
        DocumentSource.MOCK_CONNECTOR,
        MockCheckpointedConnector,
    )
    try:
        yield
    finally:
        _reset_mock_behavior()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unhandled_exception_default_marks_attempt_failed(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
    register_mock_connector: None,  # noqa: ARG001
) -> None:
    """Baseline: PERSISTENT_INDEXING False (default). An unhandled exception
    inside the connector generator marks the attempt FAILED."""
    cc_pair_id, search_settings_id, attempt_id = _seed_attempt(db_session)

    _MOCK_BEHAVIOR["docs"] = [_make_doc(f"doc-{uuid4().hex[:8]}")]
    _MOCK_BEHAVIOR["raise_at_end"] = True

    try:
        mock_app = MagicMock()
        with pytest.raises(RuntimeError, match="simulated unhandled connector error"):
            run_docfetching_entrypoint(
                app=mock_app,
                index_attempt_id=attempt_id,
                tenant_id=TEST_TENANT_ID,
                connector_credential_pair_id=cc_pair_id,
            )

        db_session.expire_all()
        attempt = get_index_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.status == IndexingStatus.FAILED

        errors = get_index_attempt_errors(attempt_id, db_session)
        # No persistent-mode catch-all recorded — only what the connector
        # itself yielded (none here).
        assert len(errors) == 0
    finally:
        _teardown_attempt(db_session, cc_pair_id, search_settings_id, attempt_id)


def test_unhandled_exception_persistent_mode_records_entity_failure(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
    register_mock_connector: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With PERSISTENT_INDEXING True, an unhandled exception inside the
    connector generator is converted into an EntityFailure and the attempt
    is NOT marked FAILED — it stays IN_PROGRESS for the completion monitor
    to resolve as COMPLETED_WITH_ERRORS once all queued batches finish."""
    # Patch the captured constant at every site that reads it. (See app_configs
    # — the value is captured at import time, so patching os.environ does not
    # affect already-imported modules.)
    monkeypatch.setattr(
        "onyx.background.indexing.run_docfetching.PERSISTENT_INDEXING", True
    )

    cc_pair_id, search_settings_id, attempt_id = _seed_attempt(db_session)

    _MOCK_BEHAVIOR["docs"] = [_make_doc(f"doc-{uuid4().hex[:8]}")]
    _MOCK_BEHAVIOR["raise_at_end"] = True
    _MOCK_BEHAVIOR["raise_message"] = "simulated_persistent_mode_kaboom"

    try:
        mock_app = MagicMock()
        # No raise expected — persistent mode swallows the exception.
        run_docfetching_entrypoint(
            app=mock_app,
            index_attempt_id=attempt_id,
            tenant_id=TEST_TENANT_ID,
            connector_credential_pair_id=cc_pair_id,
        )

        db_session.expire_all()
        attempt = get_index_attempt(db_session, attempt_id)
        assert attempt is not None
        # Attempt is NOT FAILED; completion monitor will resolve it later.
        assert attempt.status != IndexingStatus.FAILED, (
            f"Expected attempt to not be FAILED under PERSISTENT_INDEXING; "
            f"got {attempt.status}"
        )

        # Generic catch-all recorded exactly one EntityFailure.
        errors = get_index_attempt_errors(attempt_id, db_session)
        assert len(errors) == 1
        err = errors[0]
        assert err.entity_id is not None
        assert err.document_id is None
        # entity_id format: docfetching:{source}:cc_pair_{id}:batch_{n}
        assert err.entity_id.startswith(
            f"docfetching:{DocumentSource.MOCK_CONNECTOR.value}:cc_pair_{cc_pair_id}"
        )
        assert "simulated_persistent_mode_kaboom" in (err.failure_message or "")
    finally:
        _teardown_attempt(db_session, cc_pair_id, search_settings_id, attempt_id)


def test_threshold_disabled_in_persistent_mode(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
    register_mock_connector: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With PERSISTENT_INDEXING True, the docfetching `_check_failure_threshold`
    early-returns, so a flood of connector-yielded `ConnectorFailure`s
    never aborts the attempt. Without the flag, the same flood would
    raise from `_check_failure_threshold` and mark the attempt FAILED."""
    monkeypatch.setattr(
        "onyx.background.indexing.run_docfetching.PERSISTENT_INDEXING", True
    )

    cc_pair_id, search_settings_id, attempt_id = _seed_attempt(db_session)

    # 10 yielded failures, no docs — would trip >3-failures-AND->10%-ratio.
    _MOCK_BEHAVIOR["failures"] = [
        _make_doc_failure(f"doc-{i}-{uuid4().hex[:8]}") for i in range(10)
    ]

    try:
        mock_app = MagicMock()
        # No raise expected — threshold guard early-returns.
        run_docfetching_entrypoint(
            app=mock_app,
            index_attempt_id=attempt_id,
            tenant_id=TEST_TENANT_ID,
            connector_credential_pair_id=cc_pair_id,
        )

        db_session.expire_all()
        attempt = get_index_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.status != IndexingStatus.FAILED

        # All 10 failures recorded.
        errors = get_index_attempt_errors(attempt_id, db_session)
        assert len(errors) == 10
        # All are document failures (what the connector yielded).
        for err in errors:
            assert err.document_id is not None
            assert err.entity_id is None
    finally:
        _teardown_attempt(db_session, cc_pair_id, search_settings_id, attempt_id)


def test_threshold_default_aborts_attempt(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
    register_mock_connector: None,  # noqa: ARG001
) -> None:
    """Baseline: PERSISTENT_INDEXING False (default). A flood of
    `ConnectorFailure`s trips the threshold and marks the attempt FAILED."""
    cc_pair_id, search_settings_id, attempt_id = _seed_attempt(db_session)

    _MOCK_BEHAVIOR["failures"] = [
        _make_doc_failure(f"doc-{i}-{uuid4().hex[:8]}") for i in range(10)
    ]

    try:
        mock_app = MagicMock()
        with pytest.raises(Exception):
            run_docfetching_entrypoint(
                app=mock_app,
                index_attempt_id=attempt_id,
                tenant_id=TEST_TENANT_ID,
                connector_credential_pair_id=cc_pair_id,
            )

        db_session.expire_all()
        attempt = get_index_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.status == IndexingStatus.FAILED
    finally:
        _teardown_attempt(db_session, cc_pair_id, search_settings_id, attempt_id)


def test_persistent_mode_uses_entity_failure_when_no_doc_context(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
    register_mock_connector: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the connector raises immediately with no doc context, the
    catch-all records an EntityFailure (not a DocumentFailure) since we
    have no doc id to associate the error with."""
    monkeypatch.setattr(
        "onyx.background.indexing.run_docfetching.PERSISTENT_INDEXING", True
    )

    cc_pair_id, search_settings_id, attempt_id = _seed_attempt(db_session)

    # No docs, no yielded failures, just immediate raise.
    _MOCK_BEHAVIOR["raise_at_end"] = True

    try:
        mock_app = MagicMock()
        run_docfetching_entrypoint(
            app=mock_app,
            index_attempt_id=attempt_id,
            tenant_id=TEST_TENANT_ID,
            connector_credential_pair_id=cc_pair_id,
        )

        db_session.expire_all()
        errors = get_index_attempt_errors(attempt_id, db_session)
        assert len(errors) == 1
        err = errors[0]
        assert isinstance(err.entity_id, str), (
            f"Expected EntityFailure, got document_id={err.document_id}"
        )
        assert err.document_id is None
    finally:
        _teardown_attempt(db_session, cc_pair_id, search_settings_id, attempt_id)


# Suppress unused-import warnings for symbols referenced only by name in
# docstrings / type comments above.
_ = EntityFailure
