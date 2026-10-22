"""A prune of a pair with an indexing start lists only the documents from that
start. Stale hierarchy entry removal still runs: a node stays linked to the
pair if the listing yielded it or if it is an ancestor of a kept document."""

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
from onyx.connectors.models import InputType, SlimDocument
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus, HierarchyNodeType
from onyx.db.hierarchy import (
    get_hierarchy_node_by_raw_id,
    upsert_hierarchy_node_cc_pair_entries,
    upsert_hierarchy_nodes_batch,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    Document,
    HierarchyNode,
    HierarchyNodeByConnectorCredentialPair,
)
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.kg.models import KGStage
from onyx.redis.redis_connector import RedisConnector
from onyx.redis.redis_connector_prune import RedisConnectorPrunePayload
from onyx.redis.redis_hierarchy import evict_hierarchy_nodes_from_cache
from onyx.redis.redis_pool import get_redis_client
from shared_configs.contextvars import get_current_tenant_id

_SOURCE = DocumentSource.CONFLUENCE
_PREFIX = "prune-indexing-start-"
# Linked to the pair before the prune. The listing yields none of them.
_SPACE = f"{_PREFIX}space"
# An unchanged parent page. A document updated after the start lies under it.
_PARENT_PAGE = f"{_PREFIX}parent-page"
# Live at the source, but holds no document updated after the start.
_IDLE_FOLDER = f"{_PREFIX}idle-folder"
# Deleted at the source. The kept document was in it before.
_GONE_FOLDER = f"{_PREFIX}gone-folder"
# The parent of the node that the listing yields.
_OTHER_SPACE = f"{_PREFIX}other-space"
_LINKED_PARENTS = {
    _SPACE: None,
    _PARENT_PAGE: _SPACE,
    _IDLE_FOLDER: _SPACE,
    _GONE_FOLDER: _SPACE,
    _OTHER_SPACE: None,
}
# Yielded by the listing.
_NEW_FOLDER = f"{_PREFIX}new-folder"
# Listed by the dated listing, under _PARENT_PAGE.
_KEPT_DOC = f"{_PREFIX}kept-doc"
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
        yield [
            PydanticHierarchyNode(
                raw_node_id=_NEW_FOLDER,
                raw_parent_id=_OTHER_SPACE,
                display_name="New folder",
                node_type=HierarchyNodeType.FOLDER,
            ),
            SlimDocument(id=_KEPT_DOC, parent_hierarchy_raw_node_id=_PARENT_PAGE),
        ]


def _node_id(db_session: Session, raw_id: str) -> int:
    node = get_hierarchy_node_by_raw_id(db_session, raw_id, _SOURCE)
    if node is None:
        raise RuntimeError(f"hierarchy node {raw_id} not found")
    return node.id


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

    nodes = upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=[
            PydanticHierarchyNode(
                raw_node_id=raw_id,
                raw_parent_id=raw_parent_id,
                display_name=raw_id,
                node_type=HierarchyNodeType.FOLDER,
            )
            for raw_id, raw_parent_id in _LINKED_PARENTS.items()
        ],
        source=_SOURCE,
        commit=True,
        is_connector_public=True,
    )
    upsert_hierarchy_node_cc_pair_entries(
        db_session=db_session,
        hierarchy_node_ids=[node.id for node in nodes],
        connector_id=connector.id,
        credential_id=credential.id,
        commit=True,
    )
    # The stored parent is out of date: the document moved out of the folder
    # before the folder was deleted.
    db_session.add(
        Document(
            id=_KEPT_DOC,
            semantic_id=_KEPT_DOC,
            kg_stage=KGStage.NOT_STARTED,
            parent_hierarchy_node_id=_node_id(db_session, _GONE_FOLDER),
        )
    )
    db_session.commit()

    yield pair

    db_session.query(HierarchyNodeByConnectorCredentialPair).filter(
        HierarchyNodeByConnectorCredentialPair.connector_id == connector.id
    ).delete()
    db_session.query(Document).filter(Document.id == _KEPT_DOC).delete()
    db_session.query(HierarchyNode).filter(
        HierarchyNode.source == _SOURCE,
        HierarchyNode.raw_node_id.startswith(_PREFIX),
    ).delete(synchronize_session=False)
    db_session.delete(pair)
    db_session.flush()
    db_session.delete(connector)
    db_session.delete(credential)
    db_session.commit()
    evict_hierarchy_nodes_from_cache(
        get_redis_client(tenant_id=get_current_tenant_id()),
        _SOURCE,
        [*_LINKED_PARENTS, _NEW_FOLDER],
    )


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


def _linked_raw_ids(db_session: Session, pair: ConnectorCredentialPair) -> set[str]:
    db_session.expire_all()
    rows = (
        db_session.query(HierarchyNode.raw_node_id)
        .join(
            HierarchyNodeByConnectorCredentialPair,
            HierarchyNodeByConnectorCredentialPair.hierarchy_node_id
            == HierarchyNode.id,
        )
        .filter(
            HierarchyNodeByConnectorCredentialPair.connector_id == pair.connector_id,
            HierarchyNodeByConnectorCredentialPair.credential_id == pair.credential_id,
        )
        .all()
    )
    return {row.raw_node_id for row in rows}


@pytest.mark.parametrize("cc_pair", [_INDEXING_START], indirect=True)
def test_dated_prune_keeps_yielded_nodes_and_ancestors_of_kept_documents(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _run_prune(cc_pair, monkeypatch)

    # The same conversion as the indexing run.
    assert connector.starts == [_INDEXING_START.timestamp()]
    # _PARENT_PAGE and _SPACE were not yielded, but the kept document lies
    # under them. _OTHER_SPACE is an ancestor of the yielded node.
    # _IDLE_FOLDER holds no kept document. _GONE_FOLDER is gone from the
    # source, although the kept document's stored parent still names it.
    assert _linked_raw_ids(db_session, cc_pair) == {
        _SPACE,
        _PARENT_PAGE,
        _OTHER_SPACE,
        _NEW_FOLDER,
    }


@pytest.mark.parametrize("cc_pair", [None], indirect=True)
def test_full_prune_keeps_only_yielded_nodes(
    db_session: Session,
    cc_pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connector = _run_prune(cc_pair, monkeypatch)

    assert connector.starts == [None]
    # A full listing yields every live node, so only the yielded one stays.
    assert _linked_raw_ids(db_session, cc_pair) == {_NEW_FOLDER}
