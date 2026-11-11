"""A document whose parent node is not stored yet points at a STUB, not at
the source root. The STUB becomes the real node when the parent arrives, so
the document keeps the right parent."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import (
    ensure_source_node_exists,
    get_hierarchy_node_by_raw_id,
    persist_hierarchy_nodes_for_cc_pair,
)
from onyx.db.models import ConnectorCredentialPair, HierarchyNode
from onyx.redis.redis_hierarchy import (
    evict_hierarchy_nodes_from_cache,
    get_node_id_from_raw_id,
    resolve_parent_node_ids,
)
from onyx.redis.redis_pool import get_redis_client
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
)

_SOURCE = DocumentSource.MOCK_CONNECTOR


@pytest.fixture()
def pair(db_session: Session) -> Generator[ConnectorCredentialPair, None, None]:
    ensure_source_node_exists(db_session, _SOURCE)
    pair = make_cc_pair(db_session, source=_SOURCE)
    yield pair
    cleanup_cc_pair(db_session, pair)


def test_document_parent_gets_a_stub_that_the_parent_fills(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    redis_client = get_redis_client()
    tag = uuid4().hex[:8]
    known_id = f"known_{tag}"
    missing_id = f"missing_{tag}"
    raw_ids = [known_id, missing_id]
    try:
        persist_hierarchy_nodes_for_cc_pair(
            db_session=db_session,
            nodes=[
                PydanticHierarchyNode(
                    raw_node_id=known_id,
                    raw_parent_id=None,
                    display_name="Known",
                    node_type=HierarchyNodeType.FOLDER,
                )
            ],
            source=_SOURCE,
            connector_id=pair.connector_id,
            credential_id=pair.credential_id,
        )
        source_node = ensure_source_node_exists(db_session, _SOURCE)
        known = get_hierarchy_node_by_raw_id(db_session, known_id, _SOURCE)
        assert known is not None

        resolved = resolve_parent_node_ids(
            redis_client=redis_client,
            db_session=db_session,
            source=_SOURCE,
            source_node_id=source_node.id,
            raw_parent_ids=[known_id, missing_id, missing_id],
            connector_id=pair.connector_id,
            credential_id=pair.credential_id,
        )

        stub = get_hierarchy_node_by_raw_id(db_session, missing_id, _SOURCE)
        assert stub is not None
        assert stub.node_type == HierarchyNodeType.STUB
        assert resolved == {known_id: known.id, missing_id: stub.id}
        # The next batch finds the STUB in the cache.
        assert get_node_id_from_raw_id(redis_client, _SOURCE, missing_id) == (
            stub.id,
            True,
        )

        # The parent arrives: the STUB becomes the real node, same id.
        persist_hierarchy_nodes_for_cc_pair(
            db_session=db_session,
            nodes=[
                PydanticHierarchyNode(
                    raw_node_id=missing_id,
                    raw_parent_id=known_id,
                    display_name="Parent",
                    node_type=HierarchyNodeType.FOLDER,
                )
            ],
            source=_SOURCE,
            connector_id=pair.connector_id,
            credential_id=pair.credential_id,
        )
        db_session.expire_all()
        filled = get_hierarchy_node_by_raw_id(db_session, missing_id, _SOURCE)
        assert filled is not None
        assert filled.id == stub.id
        assert filled.node_type == HierarchyNodeType.FOLDER
        assert filled.parent_id == known.id
    finally:
        evict_hierarchy_nodes_from_cache(redis_client, _SOURCE, raw_ids)
        db_session.rollback()
        db_session.execute(
            delete(HierarchyNode).where(
                HierarchyNode.source == _SOURCE,
                HierarchyNode.raw_node_id.in_(raw_ids),
            )
        )
        db_session.commit()
