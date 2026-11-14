"""A document whose parent node is not stored yet points at a STUB, not at
the source root. The STUB becomes the real node when the parent arrives, so
the document keeps the right parent."""

import threading
import time
from collections.abc import Generator, Iterator
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.db import hierarchy as hierarchy_module
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import (
    ensure_source_node_exists,
    get_hierarchy_node_by_raw_id,
    persist_hierarchy_nodes_for_cc_pair,
    remove_unfilled_stub_hierarchy_nodes_for_cc_pair,
    upsert_hierarchy_node_cc_pair_entries,
)
from onyx.db.models import (
    ConnectorCredentialPair,
    Document,
    HierarchyNode,
    HierarchyNodeByConnectorCredentialPair,
)
from onyx.redis.redis_hierarchy import (
    evict_hierarchy_nodes_from_cache,
    get_node_id_from_raw_id,
    resolve_parent_node_ids,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.tenant_redis_client import TenantRedisClient
from tests.external_dependency_unit.indexing_helpers import (
    cleanup_cc_pair,
    make_cc_pair,
    seed_cc_pair_documents,
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


def test_a_successful_attempt_moves_what_is_under_an_unfilled_stub_to_the_root(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    """A parent that never arrives: after the cleanup its document and its
    child node are under the source root, and the STUB is gone. A STUB that
    its parent filled keeps its children."""
    redis_client = get_redis_client()
    tag = uuid4().hex[:8]
    never_id = f"never_{tag}"
    filled_id = f"filled_{tag}"
    child_id = f"child_{tag}"
    raw_ids = [never_id, filled_id, child_id]
    source_node = ensure_source_node_exists(db_session, _SOURCE)
    doc_ids = seed_cc_pair_documents(db_session, pair, 2, prefix=f"stub-{tag}-")
    try:
        resolved = resolve_parent_node_ids(
            redis_client=redis_client,
            db_session=db_session,
            source=_SOURCE,
            source_node_id=source_node.id,
            raw_parent_ids=[never_id, filled_id],
            connector_id=pair.connector_id,
            credential_id=pair.credential_id,
        )
        # A folder that names the missing parent, and the parent that arrives.
        persist_hierarchy_nodes_for_cc_pair(
            db_session=db_session,
            nodes=[
                PydanticHierarchyNode(
                    raw_node_id=child_id,
                    raw_parent_id=never_id,
                    display_name="Child folder",
                    node_type=HierarchyNodeType.FOLDER,
                ),
                PydanticHierarchyNode(
                    raw_node_id=filled_id,
                    raw_parent_id=None,
                    display_name="Arrived",
                    node_type=HierarchyNodeType.FOLDER,
                ),
            ],
            source=_SOURCE,
            connector_id=pair.connector_id,
            credential_id=pair.credential_id,
        )
        under_never, under_filled = doc_ids
        db_session.execute(
            update(Document)
            .where(Document.id == under_never)
            .values(parent_hierarchy_node_id=resolved[never_id])
        )
        db_session.execute(
            update(Document)
            .where(Document.id == under_filled)
            .values(parent_hierarchy_node_id=resolved[filled_id])
        )
        db_session.commit()

        removed = remove_unfilled_stub_hierarchy_nodes_for_cc_pair(
            db_session, _SOURCE, pair.connector_id, pair.credential_id
        )

        assert removed == [never_id]
        db_session.expire_all()
        assert get_hierarchy_node_by_raw_id(db_session, never_id, _SOURCE) is None
        child = get_hierarchy_node_by_raw_id(db_session, child_id, _SOURCE)
        assert child is not None
        assert child.parent_id == source_node.id
        parents = {
            row[0]: row[1]
            for row in db_session.execute(
                select(Document.id, Document.parent_hierarchy_node_id).where(
                    Document.id.in_(doc_ids)
                )
            )
        }
        assert parents == {
            under_never: source_node.id,
            under_filled: resolved[filled_id],
        }
        filled = get_hierarchy_node_by_raw_id(db_session, filled_id, _SOURCE)
        assert filled is not None
        assert filled.node_type == HierarchyNodeType.FOLDER
        # A second run finds nothing to do.
        assert (
            remove_unfilled_stub_hierarchy_nodes_for_cc_pair(
                db_session, _SOURCE, pair.connector_id, pair.credential_id
            )
            == []
        )
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


@pytest.mark.parametrize("from_cache", [False, True])
def test_a_stub_that_another_cc_pair_links_to_stays(
    db_session: Session, pair: ConnectorCredentialPair, from_cache: bool
) -> None:
    """The other pair's attempt can still fill it. The other pair links to it
    also when it finds the STUB in the cache."""
    redis_client = get_redis_client()
    raw_id = f"shared_{uuid4().hex[:8]}"
    other = make_cc_pair(db_session, source=_SOURCE)
    source_node = ensure_source_node_exists(db_session, _SOURCE)
    try:
        for cc_pair in (pair, other):
            resolve_parent_node_ids(
                redis_client=redis_client,
                db_session=db_session,
                source=_SOURCE,
                source_node_id=source_node.id,
                raw_parent_ids=[raw_id],
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
            )
            if not from_cache:
                evict_hierarchy_nodes_from_cache(redis_client, _SOURCE, [raw_id])

        assert (
            remove_unfilled_stub_hierarchy_nodes_for_cc_pair(
                db_session, _SOURCE, pair.connector_id, pair.credential_id
            )
            == []
        )
        assert get_hierarchy_node_by_raw_id(db_session, raw_id, _SOURCE) is not None
    finally:
        evict_hierarchy_nodes_from_cache(redis_client, _SOURCE, [raw_id])
        db_session.rollback()
        db_session.execute(
            delete(HierarchyNode).where(
                HierarchyNode.source == _SOURCE, HierarchyNode.raw_node_id == raw_id
            )
        )
        db_session.commit()
        cleanup_cc_pair(db_session, other)


def test_cleanup_keeps_the_children_of_a_stub_filled_after_the_selection(
    db_session: Session,
    pair: ConnectorCredentialPair,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent attempt fills a STUB after the cleanup selected it. The
    cleanup checks each batch again under a lock, so the filled folder keeps
    its documents."""
    redis_client = get_redis_client()
    tag = uuid4().hex[:8]
    first_id = f"first_{tag}"
    second_id = f"second_{tag}"
    raw_ids = [first_id, second_id]
    source_node = ensure_source_node_exists(db_session, _SOURCE)
    doc_ids = seed_cc_pair_documents(db_session, pair, 2, prefix=f"race-{tag}-")
    batch_generator = hierarchy_module.batch_generator

    def fill_second_after_first_batch(
        items: list[int], size: int
    ) -> Iterator[list[int]]:
        for index, batch in enumerate(batch_generator(items, size)):
            if index == 1:
                with get_session_with_current_tenant() as other_session:
                    persist_hierarchy_nodes_for_cc_pair(
                        db_session=other_session,
                        nodes=[
                            PydanticHierarchyNode(
                                raw_node_id=second_id,
                                raw_parent_id=None,
                                display_name="Arrived late",
                                node_type=HierarchyNodeType.FOLDER,
                            )
                        ],
                        source=_SOURCE,
                        connector_id=pair.connector_id,
                        credential_id=pair.credential_id,
                    )
            yield batch

    try:
        resolved = resolve_parent_node_ids(
            redis_client=redis_client,
            db_session=db_session,
            source=_SOURCE,
            source_node_id=source_node.id,
            raw_parent_ids=raw_ids,
            connector_id=pair.connector_id,
            credential_id=pair.credential_id,
        )
        for doc_id, raw_id in zip(doc_ids, raw_ids, strict=True):
            db_session.execute(
                update(Document)
                .where(Document.id == doc_id)
                .values(parent_hierarchy_node_id=resolved[raw_id])
            )
        db_session.commit()
        monkeypatch.setattr(hierarchy_module, "_STUB_CLEANUP_BATCH_SIZE", 1)
        monkeypatch.setattr(
            hierarchy_module, "batch_generator", fill_second_after_first_batch
        )

        removed = remove_unfilled_stub_hierarchy_nodes_for_cc_pair(
            db_session, _SOURCE, pair.connector_id, pair.credential_id
        )

        assert removed == [first_id]
        db_session.expire_all()
        parents = {
            row[0]: row[1]
            for row in db_session.execute(
                select(Document.id, Document.parent_hierarchy_node_id).where(
                    Document.id.in_(doc_ids)
                )
            )
        }
        assert parents == {
            doc_ids[0]: source_node.id,
            doc_ids[1]: resolved[second_id],
        }
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


def test_a_cached_stub_that_a_cleanup_removed_is_made_again(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    """The cache can still map a raw id to a STUB that a cleanup removed. The
    document then gets a new STUB, not an id that no longer exists."""
    redis_client = get_redis_client()
    raw_id = f"removed_{uuid4().hex[:8]}"
    source_node = ensure_source_node_exists(db_session, _SOURCE)

    def resolve() -> int:
        return resolve_parent_node_ids(
            redis_client=redis_client,
            db_session=db_session,
            source=_SOURCE,
            source_node_id=source_node.id,
            raw_parent_ids=[raw_id],
            connector_id=pair.connector_id,
            credential_id=pair.credential_id,
        )[raw_id]

    try:
        first = resolve()
        assert remove_unfilled_stub_hierarchy_nodes_for_cc_pair(
            db_session, _SOURCE, pair.connector_id, pair.credential_id
        ) == [raw_id]
        assert get_node_id_from_raw_id(redis_client, _SOURCE, raw_id) == (first, True)

        second = resolve()

        assert second != first
        db_session.expire_all()
        stub = get_hierarchy_node_by_raw_id(db_session, raw_id, _SOURCE)
        assert stub is not None
        assert stub.id == second
    finally:
        evict_hierarchy_nodes_from_cache(redis_client, _SOURCE, [raw_id])
        db_session.rollback()
        db_session.execute(
            delete(HierarchyNode).where(
                HierarchyNode.source == _SOURCE, HierarchyNode.raw_node_id == raw_id
            )
        )
        db_session.commit()


def _remove_stub(
    db_session: Session, redis_client: TenantRedisClient, raw_id: str
) -> None:
    evict_hierarchy_nodes_from_cache(redis_client, _SOURCE, [raw_id])
    db_session.rollback()
    db_session.execute(
        delete(HierarchyNode).where(
            HierarchyNode.source == _SOURCE, HierarchyNode.raw_node_id == raw_id
        )
    )
    db_session.commit()


def test_a_shared_stub_goes_when_each_pair_that_links_it_succeeded(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    """Two pairs wait for the same parent. The first success keeps the STUB,
    because the other pair can still fill it. The second success removes it
    and moves the documents of the two pairs to the root."""
    redis_client = get_redis_client()
    tag = uuid4().hex[:8]
    raw_id = f"shared_{tag}"
    other = make_cc_pair(db_session, source=_SOURCE)
    source_node = ensure_source_node_exists(db_session, _SOURCE)
    doc_ids = seed_cc_pair_documents(db_session, pair, 1, prefix=f"shared-{tag}-")
    try:
        for cc_pair in (pair, other):
            resolved = resolve_parent_node_ids(
                redis_client=redis_client,
                db_session=db_session,
                source=_SOURCE,
                source_node_id=source_node.id,
                raw_parent_ids=[raw_id],
                connector_id=cc_pair.connector_id,
                credential_id=cc_pair.credential_id,
            )
        db_session.execute(
            update(Document)
            .where(Document.id.in_(doc_ids))
            .values(parent_hierarchy_node_id=resolved[raw_id])
        )
        db_session.commit()

        first = remove_unfilled_stub_hierarchy_nodes_for_cc_pair(
            db_session, _SOURCE, pair.connector_id, pair.credential_id
        )
        assert first == []
        assert get_hierarchy_node_by_raw_id(db_session, raw_id, _SOURCE) is not None

        second = remove_unfilled_stub_hierarchy_nodes_for_cc_pair(
            db_session, _SOURCE, other.connector_id, other.credential_id
        )
        assert second == [raw_id]
        db_session.expire_all()
        assert get_hierarchy_node_by_raw_id(db_session, raw_id, _SOURCE) is None
        parents = set(
            db_session.execute(
                select(Document.parent_hierarchy_node_id).where(
                    Document.id.in_(doc_ids)
                )
            ).scalars()
        )
        assert parents == {source_node.id}
    finally:
        _remove_stub(db_session, redis_client, raw_id)
        cleanup_cc_pair(db_session, other)


def test_cleanup_sees_a_link_that_commits_while_it_waits_for_the_lock(
    db_session: Session, pair: ConnectorCredentialPair
) -> None:
    """Another pair links the STUB and holds its lock. The cleanup waits. When
    the link commits, the cleanup must see it and keep the STUB: a check
    from before the wait would delete the STUB and the other pair's link."""
    redis_client = get_redis_client()
    raw_id = f"waited_{uuid4().hex[:8]}"
    other = make_cc_pair(db_session, source=_SOURCE)
    source_node = ensure_source_node_exists(db_session, _SOURCE)
    removed: list[list[str]] = []
    try:
        resolve_parent_node_ids(
            redis_client=redis_client,
            db_session=db_session,
            source=_SOURCE,
            source_node_id=source_node.id,
            raw_parent_ids=[raw_id],
            connector_id=pair.connector_id,
            credential_id=pair.credential_id,
        )
        stub = get_hierarchy_node_by_raw_id(db_session, raw_id, _SOURCE)
        assert stub is not None
        stub_id = stub.id
        pair_ids = (pair.connector_id, pair.credential_id)
        db_session.commit()

        def cleanup() -> None:
            with get_session_with_current_tenant() as cleanup_session:
                removed.append(
                    remove_unfilled_stub_hierarchy_nodes_for_cc_pair(
                        cleanup_session, _SOURCE, *pair_ids
                    )
                )

        with get_session_with_current_tenant() as linker:
            # As link_cached_stub_nodes_for_cc_pair does, before its commit.
            linker.execute(
                select(HierarchyNode.id)
                .where(HierarchyNode.id == stub_id)
                .with_for_update(key_share=True)
            )
            upsert_hierarchy_node_cc_pair_entries(
                db_session=linker,
                hierarchy_node_ids=[stub_id],
                connector_id=other.connector_id,
                credential_id=other.credential_id,
                commit=False,
            )
            thread = threading.Thread(target=cleanup)
            thread.start()
            # The cleanup now waits for the lock on the STUB.
            time.sleep(1.0)
            assert not removed
            linker.commit()
        thread.join(timeout=30)

        assert removed == [[]]
        db_session.expire_all()
        assert get_hierarchy_node_by_raw_id(db_session, raw_id, _SOURCE) is not None
        links = db_session.execute(
            select(HierarchyNodeByConnectorCredentialPair.connector_id).where(
                HierarchyNodeByConnectorCredentialPair.hierarchy_node_id == stub_id
            )
        ).scalars()
        assert set(links) == {other.connector_id}
    finally:
        _remove_stub(db_session, redis_client, raw_id)
        cleanup_cc_pair(db_session, other)
