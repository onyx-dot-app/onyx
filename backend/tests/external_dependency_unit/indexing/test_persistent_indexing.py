"""External-dependency-unit tests for PERSISTENT_INDEXING (docfetching side).

Exercises `run_docfetching_entrypoint` against a mock checkpointed connector.
PERSISTENT_INDEXING's docfetching-side contract:

  - It DISABLES the >3-failures-AND->10%-ratio threshold abort, so a flood of
    connector-yielded `ConnectorFailure`s no longer fails the attempt.
  - It does NOT swallow unhandled exceptions raised from the connector
    generator itself — those still mark the attempt FAILED (we can't isolate
    the bad entity and silently advancing risks skipping source data).

Per-batch docprocessing catch-all recovery is exercised separately.

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
from onyx.connectors.models import InputType
from onyx.connectors.models import TextSection
from onyx.db.enums import EmbeddingPrecision
from onyx.db.enums import IndexingStatus
from onyx.db.enums import IndexModelStatus
from onyx.db.index_attempt import get_index_attempt
from onyx.db.index_attempt import get_index_attempt_errors
from onyx.db.models import IndexAttempt
from onyx.db.models import IndexAttemptError
from onyx.db.models import SearchSettings
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE
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
    # `make_cc_pair` defaults the connector's input_type to LOAD_STATE, but our
    # mock implements CheckpointedConnector — which the factory only accepts
    # under POLL. Override before the entrypoint runs.
    cc_pair.connector.input_type = InputType.POLL
    db_session.commit()

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
    # IndexAttemptError FKs index_attempt; drop child rows first.
    db_session.query(IndexAttemptError).filter(
        IndexAttemptError.index_attempt_id == attempt_id
    ).delete(synchronize_session="fetch")
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
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
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


def test_unhandled_exception_persistent_mode_still_marks_failed(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    initialize_file_store: None,  # noqa: ARG001
    register_mock_connector: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with PERSISTENT_INDEXING True, an unhandled exception inside the
    connector generator still marks the attempt FAILED — there's no entity
    context to isolate the failing item, so silently advancing would risk
    skipping source data. Operators must triage by fixing the connector."""
    monkeypatch.setattr(
        "onyx.background.indexing.run_docfetching.PERSISTENT_INDEXING", True
    )

    cc_pair_id, search_settings_id, attempt_id = _seed_attempt(db_session)

    _MOCK_BEHAVIOR["docs"] = [_make_doc(f"doc-{uuid4().hex[:8]}")]
    _MOCK_BEHAVIOR["raise_at_end"] = True
    _MOCK_BEHAVIOR["raise_message"] = "simulated_persistent_mode_kaboom"

    try:
        mock_app = MagicMock()
        with pytest.raises(RuntimeError, match="simulated_persistent_mode_kaboom"):
            run_docfetching_entrypoint(
                app=mock_app,
                index_attempt_id=attempt_id,
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                connector_credential_pair_id=cc_pair_id,
            )

        db_session.expire_all()
        attempt = get_index_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.status == IndexingStatus.FAILED

        # No generic catch-all was triggered; no entity-level failure rows.
        errors = get_index_attempt_errors(attempt_id, db_session)
        assert len(errors) == 0
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
            tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
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
                tenant_id=POSTGRES_DEFAULT_SCHEMA_STANDARD_VALUE,
                connector_credential_pair_id=cc_pair_id,
            )

        db_session.expire_all()
        attempt = get_index_attempt(db_session, attempt_id)
        assert attempt is not None
        assert attempt.status == IndexingStatus.FAILED
    finally:
        _teardown_attempt(db_session, cc_pair_id, search_settings_id, attempt_id)
