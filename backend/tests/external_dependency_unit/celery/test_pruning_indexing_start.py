"""A prune of a pair with an indexing start lists only the documents from that
start, and keeps the hierarchy entries that such a listing can omit."""

from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.pruning import tasks as pruning_tasks
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    GenerateSlimDocumentOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
)
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus, HierarchyNodeType
from onyx.db.hierarchy import (
    upsert_hierarchy_node_cc_pair_entries,
    upsert_hierarchy_nodes_batch,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    HierarchyNodeByConnectorCredentialPair,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_prune import RedisConnectorPrunePayload
from shared_configs.contextvars import get_current_tenant_id

_SOURCE = DocumentSource.CONFLUENCE
_FOLDER_RAW_ID = "prune-indexing-start-folder"
# Stored naive, as the connector table stores it.
_INDEXING_START = datetime(2025, 1, 1)


class _DatedSlimConnector(SlimConnector):
    slim_listing_honors_indexing_start = True

    def __init__(self) -> None:
        self.starts: list[SecondsSinceUnixEpoch | None] = []

    def load_credentials(self, credentials: dict[str, Any]) -> None:  # noqa: ARG002
        return None

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        self.starts.append(start)
        yield []


@pytest.fixture
def cc_pair(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    request: pytest.FixtureRequest,
) -> Generator[ConnectorCredentialPair, None, None]:
    connector = Connector(
        name="Prune indexing start",
        source=_SOURCE,
        input_type=InputType.POLL,
        connector_specific_config={},
        indexing_start=request.param,
    )
    credential = Credential(source=_SOURCE, credential_json={}, admin_public=True)
    db_session.add_all([connector, credential])
    db_session.flush()
    pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name="Prune indexing start",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(pair)
    db_session.commit()

    folder = upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=[
            PydanticHierarchyNode(
                raw_node_id=_FOLDER_RAW_ID,
                raw_parent_id=None,
                display_name="Folder",
                node_type=HierarchyNodeType.FOLDER,
            )
        ],
        source=_SOURCE,
        commit=True,
        is_connector_public=True,
    )
    upsert_hierarchy_node_cc_pair_entries(
        db_session=db_session,
        hierarchy_node_ids=[node.id for node in folder],
        connector_id=connector.id,
        credential_id=credential.id,
        commit=True,
    )

    yield pair

    db_session.query(HierarchyNodeByConnectorCredentialPair).filter(
        HierarchyNodeByConnectorCredentialPair.connector_id == connector.id
    ).delete()
    db_session.delete(pair)
    db_session.flush()
    db_session.delete(connector)
    db_session.delete(credential)
    db_session.commit()


def _run_prune(
    cc_pair: ConnectorCredentialPair, monkeypatch: pytest.MonkeyPatch
) -> _DatedSlimConnector:
    connector = _DatedSlimConnector()
    monkeypatch.setattr(
        pruning_tasks, "instantiate_connector", lambda *_args, **_kwargs: connector
    )
    tenant_id = get_current_tenant_id()
    redis_connector = RedisConnector(tenant_id, cc_pair.id)
    redis_connector.prune.set_fence(
        RedisConnectorPrunePayload(
            id="prune-indexing-start",
            submitted=datetime.now(timezone.utc),
            started=None,
            celery_task_id="prune-indexing-start-task",
        )
    )
    try:
        result = pruning_tasks.connector_pruning_generator_task.apply(
            kwargs={
                "cc_pair_id": cc_pair.id,
                "connector_id": cc_pair.connector_id,
                "credential_id": cc_pair.credential_id,
                "tenant_id": tenant_id,
            }
        )
        assert result.successful(), result.traceback
    finally:
        redis_connector.prune.reset()
    return connector


def _hierarchy_entry_count(db_session: Session, pair: ConnectorCredentialPair) -> int:
    db_session.expire_all()
    return (
        db_session.query(HierarchyNodeByConnectorCredentialPair)
        .filter(
            HierarchyNodeByConnectorCredentialPair.connector_id == pair.connector_id,
            HierarchyNodeByConnectorCredentialPair.credential_id == pair.credential_id,
        )
        .count()
    )


@pytest.mark.parametrize("cc_pair", [_INDEXING_START], indirect=True)
def test_prune_lists_from_the_indexing_start(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _run_prune(cc_pair, monkeypatch)

    # The same conversion as the indexing run.
    assert connector.starts == [_INDEXING_START.timestamp()]
    # The listing can omit live nodes, so the pair keeps its entries.
    assert _hierarchy_entry_count(db_session, cc_pair) == 1


@pytest.mark.parametrize("cc_pair", [None], indirect=True)
def test_prune_without_an_indexing_start_lists_everything(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _run_prune(cc_pair, monkeypatch)

    assert connector.starts == [None]
    # A full listing names every live node, so the unlisted entry goes.
    assert _hierarchy_entry_count(db_session, cc_pair) == 0
