"""A prune deletes nothing when the listing reports an entity it could not
list. A short or empty listing with no failure still prunes: the user may
really have deleted that data."""

from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any, ClassVar

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.pruning import tasks as pruning_tasks
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    CheckpointedConnector,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import (
    ConnectorCheckpoint,
    ConnectorFailure,
    Document,
    EntityFailure,
    SlimDocument,
    TextSection,
)
from onyx.db.enums import SyncStatus, SyncType
from onyx.db.models import ConnectorCredentialPair, SyncRecord
from onyx.db.sync_record import fetch_latest_sync_record, insert_sync_record
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_prune import (
    RedisConnectorPrune,
    RedisConnectorPrunePayload,
)
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    seed_cc_pair_documents,
)

_PRUNE_TASK_ID = "prune-incomplete-listing-task"
_PREFIX = "prune-incomplete-"


class _SlimListing(SlimConnector):
    listed_ids: ClassVar[list[str]] = []

    def load_credentials(self, credentials: dict[str, Any]) -> None:  # noqa: ARG002
        return None

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        yield [SlimDocument(id=doc_id) for doc_id in self.listed_ids]


class _ListingWithFailedEntity(CheckpointedConnector[ConnectorCheckpoint]):
    """Lists one document, then reports a space it could not list."""

    listed_id: ClassVar[str] = ""

    def load_credentials(self, credentials: dict[str, Any]) -> None:  # noqa: ARG002
        return None

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: ConnectorCheckpoint,  # noqa: ARG002
    ) -> CheckpointOutput[ConnectorCheckpoint]:
        yield Document(
            id=self.listed_id,
            source=DocumentSource.MOCK_CONNECTOR,
            sections=[TextSection(text="listed")],
            semantic_identifier=self.listed_id,
            metadata={},
        )
        yield ConnectorFailure(
            failed_entity=EntityFailure(entity_id="unlisted-space"),
            failure_message="the source refused the space listing",
        )
        return ConnectorCheckpoint(has_more=False)

    def build_dummy_checkpoint(self) -> ConnectorCheckpoint:
        return ConnectorCheckpoint(has_more=True)

    def validate_checkpoint_json(self, checkpoint_json: str) -> ConnectorCheckpoint:
        return ConnectorCheckpoint.model_validate_json(checkpoint_json)


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[ConnectorCredentialPair, None, None]:
    pair = make_cc_pair(db_session)
    yield pair
    RedisConnector(get_current_tenant_id(), pair.id).prune.reset()
    db_session.rollback()
    db_session.execute(delete(SyncRecord).where(SyncRecord.entity_id == pair.id))
    db_session.commit()
    cleanup_cc_pair(db_session, pair)


@pytest.fixture
def pruned_ids(monkeypatch: pytest.MonkeyPatch) -> list[set[str]]:
    """The id sets the prune queued for deletion."""
    calls: list[set[str]] = []

    def _record(
        _self: RedisConnectorPrune,
        documents_to_prune: set[str],
        *_args: Any,
    ) -> int:
        calls.append(documents_to_prune)
        return len(documents_to_prune)

    monkeypatch.setattr(RedisConnectorPrune, "generate_tasks", _record)
    return calls


def _run_prune(
    db_session: Session,
    pair: ConnectorCredentialPair,
    connector: object,
    monkeypatch: pytest.MonkeyPatch,
) -> bool:
    monkeypatch.setattr(
        pruning_tasks, "instantiate_connector", lambda *_args, **_kwargs: connector
    )
    insert_sync_record(db_session, pair.id, SyncType.PRUNING)
    RedisConnector(get_current_tenant_id(), pair.id).prune.set_fence(
        RedisConnectorPrunePayload(
            id="prune-incomplete-listing",
            submitted=datetime.now(timezone.utc),
            started=None,
            celery_task_id=_PRUNE_TASK_ID,
        )
    )
    result = pruning_tasks.connector_pruning_generator_task.apply(
        kwargs={
            "cc_pair_id": pair.id,
            "connector_id": pair.connector_id,
            "credential_id": pair.credential_id,
            "tenant_id": get_current_tenant_id(),
        },
        task_id=_PRUNE_TASK_ID,
    )
    return result.successful()


def _assert_skipped(
    db_session: Session, pair: ConnectorCredentialPair, reason: str
) -> None:
    db_session.expire_all()
    record = fetch_latest_sync_record(db_session, pair.id, SyncType.PRUNING)
    assert record is not None
    assert record.sync_status == SyncStatus.FAILED
    assert record.error_message is not None
    assert "nothing deleted" in record.error_message
    assert reason in record.error_message
    assert not RedisConnector(get_current_tenant_id(), pair.id).prune.fenced


def test_failed_entity_deletes_nothing(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
    pruned_ids: list[set[str]],
) -> None:
    doc_ids = seed_cc_pair_documents(
        db_session, cc_pair, 3, prefix=_PREFIX, unique=True
    )
    monkeypatch.setattr(_ListingWithFailedEntity, "listed_id", doc_ids[0])

    assert not _run_prune(db_session, cc_pair, _ListingWithFailedEntity(), monkeypatch)

    assert pruned_ids == []
    _assert_skipped(db_session, cc_pair, "unlisted-space")


def test_short_listing_still_prunes(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
    pruned_ids: list[set[str]],
) -> None:
    doc_ids = seed_cc_pair_documents(
        db_session, cc_pair, 3, prefix=_PREFIX, unique=True
    )
    monkeypatch.setattr(_SlimListing, "listed_ids", doc_ids[:1])

    assert _run_prune(db_session, cc_pair, _SlimListing(), monkeypatch)

    assert pruned_ids == [set(doc_ids[1:])]


def test_empty_listing_prunes_everything(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
    pruned_ids: list[set[str]],
) -> None:
    doc_ids = seed_cc_pair_documents(
        db_session, cc_pair, 3, prefix=_PREFIX, unique=True
    )
    monkeypatch.setattr(_SlimListing, "listed_ids", [])

    assert _run_prune(db_session, cc_pair, _SlimListing(), monkeypatch)

    assert pruned_ids == [set(doc_ids)]
