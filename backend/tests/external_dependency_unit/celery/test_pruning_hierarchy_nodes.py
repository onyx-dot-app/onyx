"""
External dependency unit tests for pruning hierarchy node extraction and DB persistence.

Verifies that:
1. extract_ids_from_runnable_connector correctly separates hierarchy nodes from doc IDs
2. Extracted hierarchy nodes are correctly upserted to Postgres via upsert_hierarchy_nodes_batch
3. Upserting is idempotent (running twice doesn't duplicate nodes)
4. Document-to-hierarchy-node linkage is updated during pruning
5. link_hierarchy_nodes_to_documents links nodes that are also documents

Uses a mock SlimConnectorWithPermSync that yields known hierarchy nodes and slim documents,
combined with a real PostgreSQL database for verifying persistence.
"""

from collections.abc import Iterator
from typing import Any

from sqlalchemy.orm import Session

from onyx.access.models import ExternalAccess
from onyx.background.celery.celery_utils import extract_ids_from_runnable_connector
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateSlimDocumentOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import ensure_source_node_exists
from onyx.db.hierarchy import get_all_hierarchy_nodes_for_source
from onyx.db.hierarchy import get_hierarchy_node_by_raw_id
from onyx.db.hierarchy import link_hierarchy_nodes_to_documents
from onyx.db.hierarchy import update_document_parent_hierarchy_nodes
from onyx.db.hierarchy import upsert_hierarchy_nodes_batch
from onyx.db.models import Document as DbDocument
from onyx.db.models import HierarchyNode as DBHierarchyNode
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.kg.models import KGStage

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_SOURCE = DocumentSource.SLACK

CHANNEL_A_ID = "C_GENERAL"
CHANNEL_A_NAME = "#general"
CHANNEL_B_ID = "C_RANDOM"
CHANNEL_B_NAME = "#random"
CHANNEL_C_ID = "C_ENGINEERING"
CHANNEL_C_NAME = "#engineering"

SLIM_DOC_IDS = ["msg-001", "msg-002", "msg-003"]


# ---------------------------------------------------------------------------
# Mock connector
# ---------------------------------------------------------------------------


def _make_hierarchy_nodes() -> list[PydanticHierarchyNode]:
    """Build a known set of hierarchy nodes resembling Slack channels."""
    return [
        PydanticHierarchyNode(
            raw_node_id=CHANNEL_A_ID,
            raw_parent_id=None,
            display_name=CHANNEL_A_NAME,
            link="https://slack.example.com/channels/general",
            node_type=HierarchyNodeType.CHANNEL,
            external_access=ExternalAccess(
                external_user_emails={"alice@example.com", "bob@example.com"},
                external_user_group_ids=set(),
                is_public=False,
            ),
        ),
        PydanticHierarchyNode(
            raw_node_id=CHANNEL_B_ID,
            raw_parent_id=None,
            display_name=CHANNEL_B_NAME,
            link="https://slack.example.com/channels/random",
            node_type=HierarchyNodeType.CHANNEL,
        ),
        PydanticHierarchyNode(
            raw_node_id=CHANNEL_C_ID,
            raw_parent_id=None,
            display_name=CHANNEL_C_NAME,
            link="https://slack.example.com/channels/engineering",
            node_type=HierarchyNodeType.CHANNEL,
            external_access=ExternalAccess(
                external_user_emails=set(),
                external_user_group_ids={"eng-team"},
                is_public=True,
            ),
        ),
    ]


DOC_PARENT_MAP = {
    "msg-001": CHANNEL_A_ID,
    "msg-002": CHANNEL_A_ID,
    "msg-003": CHANNEL_B_ID,
}


def _make_slim_docs() -> list[SlimDocument | PydanticHierarchyNode]:
    return [
        SlimDocument(id=doc_id, parent_hierarchy_raw_node_id=DOC_PARENT_MAP.get(doc_id))
        for doc_id in SLIM_DOC_IDS
    ]


class MockSlimConnectorWithPermSync(SlimConnectorWithPermSync):
    """Yields a batch containing interleaved hierarchy nodes and slim docs."""

    def load_credentials(
        self, credentials: dict[str, Any]  # noqa: ARG002
    ) -> dict[str, Any] | None:  # noqa: ARG002
        return None

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,  # noqa: ARG002
    ) -> GenerateSlimDocumentOutput:
        return self._generate()

    def _generate(self) -> Iterator[list[SlimDocument | PydanticHierarchyNode]]:
        # First batch: hierarchy nodes + first slim doc
        batch_1: list[SlimDocument | PydanticHierarchyNode] = [
            *_make_hierarchy_nodes(),
            _make_slim_docs()[0],
        ]
        yield batch_1

        # Second batch: remaining slim docs only (no hierarchy nodes)
        yield _make_slim_docs()[1:]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cleanup_test_data(db_session: Session) -> None:
    """Remove all test hierarchy nodes and documents to isolate tests."""
    for doc_id in SLIM_DOC_IDS:
        db_session.query(DbDocument).filter(DbDocument.id == doc_id).delete()
    db_session.query(DBHierarchyNode).filter(
        DBHierarchyNode.source == TEST_SOURCE
    ).delete()
    db_session.commit()


def _create_test_documents(db_session: Session) -> list[DbDocument]:
    """Insert minimal Document rows for our test doc IDs."""
    docs = []
    for doc_id in SLIM_DOC_IDS:
        doc = DbDocument(
            id=doc_id,
            semantic_id=doc_id,
            kg_stage=KGStage.NOT_STARTED,
        )
        db_session.add(doc)
        docs.append(doc)
    db_session.commit()
    return docs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pruning_extracts_hierarchy_nodes(db_session: Session) -> None:  # noqa: ARG001
    """extract_ids_from_runnable_connector must separate hierarchy node IDs and
    document IDs into the correct buckets of the SlimConnectorExtractionResult."""
    connector = MockSlimConnectorWithPermSync()

    result = extract_ids_from_runnable_connector(connector, callback=None)

    # Doc IDs should include both slim doc IDs and hierarchy node raw_node_ids
    # (hierarchy node IDs are added to doc_ids so they aren't pruned)
    expected_ids = {
        CHANNEL_A_ID,
        CHANNEL_B_ID,
        CHANNEL_C_ID,
        *SLIM_DOC_IDS,
    }
    assert result.raw_id_to_parent.keys() == expected_ids

    # Hierarchy nodes should be the 3 channels
    assert len(result.hierarchy_nodes) == 3
    extracted_raw_ids = {n.raw_node_id for n in result.hierarchy_nodes}
    assert extracted_raw_ids == {CHANNEL_A_ID, CHANNEL_B_ID, CHANNEL_C_ID}


def test_pruning_upserts_hierarchy_nodes_to_db(db_session: Session) -> None:
    """Full flow: extract hierarchy nodes from mock connector, upsert to Postgres,
    then verify the DB state (node count, parent relationships, permissions)."""
    _cleanup_test_data(db_session)

    # Step 1: ensure the SOURCE node exists (mirrors what the pruning task does)
    source_node = ensure_source_node_exists(db_session, TEST_SOURCE, commit=True)

    # Step 2: extract from mock connector
    connector = MockSlimConnectorWithPermSync()
    result = extract_ids_from_runnable_connector(connector, callback=None)
    assert len(result.hierarchy_nodes) == 3

    # Step 3: upsert hierarchy nodes (public connector = False)
    upserted = upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=result.hierarchy_nodes,
        source=TEST_SOURCE,
        commit=True,
        is_connector_public=False,
    )
    assert len(upserted) == 3

    # Step 4: verify DB state
    all_nodes = get_all_hierarchy_nodes_for_source(db_session, TEST_SOURCE)
    # 3 channel nodes + 1 SOURCE node
    assert len(all_nodes) == 4

    # Verify each channel node
    channel_a = get_hierarchy_node_by_raw_id(db_session, CHANNEL_A_ID, TEST_SOURCE)
    assert channel_a is not None
    assert channel_a.display_name == CHANNEL_A_NAME
    assert channel_a.node_type == HierarchyNodeType.CHANNEL
    assert channel_a.link == "https://slack.example.com/channels/general"
    # Parent should be the SOURCE node (raw_parent_id was None)
    assert channel_a.parent_id == source_node.id
    # Permission fields for channel A (private, has user emails)
    assert channel_a.is_public is False
    assert channel_a.external_user_emails is not None
    assert set(channel_a.external_user_emails) == {
        "alice@example.com",
        "bob@example.com",
    }

    channel_b = get_hierarchy_node_by_raw_id(db_session, CHANNEL_B_ID, TEST_SOURCE)
    assert channel_b is not None
    assert channel_b.display_name == CHANNEL_B_NAME
    assert channel_b.parent_id == source_node.id
    # Channel B has no external_access -> defaults to not public, no emails/groups
    assert channel_b.is_public is False
    assert channel_b.external_user_emails is None
    assert channel_b.external_user_group_ids is None

    channel_c = get_hierarchy_node_by_raw_id(db_session, CHANNEL_C_ID, TEST_SOURCE)
    assert channel_c is not None
    assert channel_c.display_name == CHANNEL_C_NAME
    assert channel_c.parent_id == source_node.id
    # Channel C is public and has a group
    assert channel_c.is_public is True
    assert channel_c.external_user_group_ids is not None
    assert set(channel_c.external_user_group_ids) == {"eng-team"}


def test_pruning_upserts_hierarchy_nodes_public_connector(
    db_session: Session,
) -> None:
    """When the connector's access type is PUBLIC, all hierarchy nodes must be
    marked is_public=True regardless of their external_access settings."""
    _cleanup_test_data(db_session)

    ensure_source_node_exists(db_session, TEST_SOURCE, commit=True)

    connector = MockSlimConnectorWithPermSync()
    result = extract_ids_from_runnable_connector(connector, callback=None)

    upserted = upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=result.hierarchy_nodes,
        source=TEST_SOURCE,
        commit=True,
        is_connector_public=True,
    )
    assert len(upserted) == 3

    # Every node should be public
    for node in upserted:
        assert node.is_public is True
        # Public connector forces emails/groups to None
        assert node.external_user_emails is None
        assert node.external_user_group_ids is None


def test_pruning_hierarchy_node_upsert_idempotency(db_session: Session) -> None:
    """Upserting the same hierarchy nodes twice must not create duplicates.
    The second call should update existing rows in place."""
    _cleanup_test_data(db_session)

    ensure_source_node_exists(db_session, TEST_SOURCE, commit=True)

    nodes = _make_hierarchy_nodes()

    # First upsert
    first_result = upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=nodes,
        source=TEST_SOURCE,
        commit=True,
        is_connector_public=False,
    )
    first_ids = {n.id for n in first_result}
    all_after_first = get_all_hierarchy_nodes_for_source(db_session, TEST_SOURCE)
    count_after_first = len(all_after_first)

    # Second upsert with the same nodes
    second_result = upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=nodes,
        source=TEST_SOURCE,
        commit=True,
        is_connector_public=False,
    )
    second_ids = {n.id for n in second_result}
    all_after_second = get_all_hierarchy_nodes_for_source(db_session, TEST_SOURCE)
    count_after_second = len(all_after_second)

    # No new rows should have been created
    assert count_after_first == count_after_second
    # Same DB primary keys should have been returned
    assert first_ids == second_ids


def test_pruning_hierarchy_node_upsert_updates_fields(db_session: Session) -> None:
    """Upserting a hierarchy node with changed fields should update the existing row."""
    _cleanup_test_data(db_session)

    ensure_source_node_exists(db_session, TEST_SOURCE, commit=True)

    original_node = PydanticHierarchyNode(
        raw_node_id=CHANNEL_A_ID,
        raw_parent_id=None,
        display_name=CHANNEL_A_NAME,
        link="https://slack.example.com/channels/general",
        node_type=HierarchyNodeType.CHANNEL,
    )
    upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=[original_node],
        source=TEST_SOURCE,
        commit=True,
        is_connector_public=False,
    )

    # Now upsert again with updated display_name and permissions
    updated_node = PydanticHierarchyNode(
        raw_node_id=CHANNEL_A_ID,
        raw_parent_id=None,
        display_name="#general-renamed",
        link="https://slack.example.com/channels/general-renamed",
        node_type=HierarchyNodeType.CHANNEL,
        external_access=ExternalAccess(
            external_user_emails={"new_user@example.com"},
            external_user_group_ids=set(),
            is_public=True,
        ),
    )
    upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=[updated_node],
        source=TEST_SOURCE,
        commit=True,
        is_connector_public=False,
    )

    db_node = get_hierarchy_node_by_raw_id(db_session, CHANNEL_A_ID, TEST_SOURCE)
    assert db_node is not None
    assert db_node.display_name == "#general-renamed"
    assert db_node.link == "https://slack.example.com/channels/general-renamed"
    assert db_node.is_public is True
    assert db_node.external_user_emails is not None
    assert set(db_node.external_user_emails) == {"new_user@example.com"}


# ---------------------------------------------------------------------------
# Document-to-hierarchy-node linkage tests
# ---------------------------------------------------------------------------


def test_extraction_preserves_parent_hierarchy_raw_node_id(
    db_session: Session,  # noqa: ARG001
) -> None:
    """extract_ids_from_runnable_connector should carry the
    parent_hierarchy_raw_node_id from SlimDocument into the doc_ids dict."""
    connector = MockSlimConnectorWithPermSync()
    result = extract_ids_from_runnable_connector(connector, callback=None)

    for doc_id, expected_parent in DOC_PARENT_MAP.items():
        assert (
            result.raw_id_to_parent[doc_id] == expected_parent
        ), f"doc_ids[{doc_id}] should be {expected_parent}"

    # Hierarchy node entries have None parent (they aren't documents)
    for channel_id in [CHANNEL_A_ID, CHANNEL_B_ID, CHANNEL_C_ID]:
        assert result.raw_id_to_parent[channel_id] is None


def test_update_document_parent_hierarchy_nodes(db_session: Session) -> None:
    """update_document_parent_hierarchy_nodes should set
    Document.parent_hierarchy_node_id for each document in the mapping."""
    _cleanup_test_data(db_session)

    source_node = ensure_source_node_exists(db_session, TEST_SOURCE, commit=True)
    upserted = upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=_make_hierarchy_nodes(),
        source=TEST_SOURCE,
        commit=True,
        is_connector_public=False,
    )
    node_id_by_raw = {n.raw_node_id: n.id for n in upserted}

    # Create documents with no parent set
    docs = _create_test_documents(db_session)
    for doc in docs:
        assert doc.parent_hierarchy_node_id is None

    # Build resolved map (same logic as _resolve_and_update_document_parents)
    resolved: dict[str, int | None] = {}
    for doc_id, raw_parent in DOC_PARENT_MAP.items():
        resolved[doc_id] = node_id_by_raw.get(raw_parent, source_node.id)

    updated = update_document_parent_hierarchy_nodes(
        db_session=db_session,
        doc_parent_map=resolved,
        commit=True,
    )
    assert updated == len(SLIM_DOC_IDS)

    # Verify each document now points to the correct hierarchy node
    db_session.expire_all()
    for doc_id, raw_parent in DOC_PARENT_MAP.items():
        tmp_doc = db_session.get(DbDocument, doc_id)
        assert tmp_doc is not None
        doc = tmp_doc
        expected_node_id = node_id_by_raw[raw_parent]
        assert (
            doc.parent_hierarchy_node_id == expected_node_id
        ), f"Document {doc_id} should point to node for {raw_parent}"


def test_update_document_parent_is_idempotent(db_session: Session) -> None:
    """Running update_document_parent_hierarchy_nodes a second time with the
    same mapping should update zero rows."""
    _cleanup_test_data(db_session)

    ensure_source_node_exists(db_session, TEST_SOURCE, commit=True)
    upserted = upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=_make_hierarchy_nodes(),
        source=TEST_SOURCE,
        commit=True,
        is_connector_public=False,
    )
    node_id_by_raw = {n.raw_node_id: n.id for n in upserted}
    _create_test_documents(db_session)

    resolved: dict[str, int | None] = {
        doc_id: node_id_by_raw[raw_parent]
        for doc_id, raw_parent in DOC_PARENT_MAP.items()
    }

    first_updated = update_document_parent_hierarchy_nodes(
        db_session=db_session,
        doc_parent_map=resolved,
        commit=True,
    )
    assert first_updated == len(SLIM_DOC_IDS)

    second_updated = update_document_parent_hierarchy_nodes(
        db_session=db_session,
        doc_parent_map=resolved,
        commit=True,
    )
    assert second_updated == 0


def test_link_hierarchy_nodes_to_documents_for_confluence(
    db_session: Session,
) -> None:
    """For sources in SOURCES_WITH_HIERARCHY_NODE_DOCUMENTS (e.g. Confluence),
    link_hierarchy_nodes_to_documents should set HierarchyNode.document_id
    when a hierarchy node's raw_node_id matches a document ID."""
    _cleanup_test_data(db_session)
    confluence_source = DocumentSource.CONFLUENCE

    # Clean up any existing Confluence hierarchy nodes
    db_session.query(DBHierarchyNode).filter(
        DBHierarchyNode.source == confluence_source
    ).delete()
    db_session.commit()

    ensure_source_node_exists(db_session, confluence_source, commit=True)

    # Create a hierarchy node whose raw_node_id matches a document ID
    page_node_id = "confluence-page-123"
    nodes = [
        PydanticHierarchyNode(
            raw_node_id=page_node_id,
            raw_parent_id=None,
            display_name="Test Page",
            link="https://wiki.example.com/page/123",
            node_type=HierarchyNodeType.PAGE,
        ),
    ]
    upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=nodes,
        source=confluence_source,
        commit=True,
        is_connector_public=False,
    )

    # Verify the node exists but has no document_id yet
    db_node = get_hierarchy_node_by_raw_id(db_session, page_node_id, confluence_source)
    assert db_node is not None
    assert db_node.document_id is None

    # Create a document with the same ID as the hierarchy node
    doc = DbDocument(
        id=page_node_id,
        semantic_id="Test Page",
        kg_stage=KGStage.NOT_STARTED,
    )
    db_session.add(doc)
    db_session.commit()

    # Link nodes to documents
    linked = link_hierarchy_nodes_to_documents(
        db_session=db_session,
        document_ids=[page_node_id],
        source=confluence_source,
        commit=True,
    )
    assert linked == 1

    # Verify the hierarchy node now has document_id set
    db_session.expire_all()
    db_node = get_hierarchy_node_by_raw_id(db_session, page_node_id, confluence_source)
    assert db_node is not None
    assert db_node.document_id == page_node_id

    # Cleanup
    db_session.query(DbDocument).filter(DbDocument.id == page_node_id).delete()
    db_session.query(DBHierarchyNode).filter(
        DBHierarchyNode.source == confluence_source
    ).delete()
    db_session.commit()


def test_link_hierarchy_nodes_skips_non_hierarchy_sources(
    db_session: Session,
) -> None:
    """link_hierarchy_nodes_to_documents should return 0 for sources that
    don't support hierarchy-node-as-document (e.g. Slack, Google Drive)."""
    linked = link_hierarchy_nodes_to_documents(
        db_session=db_session,
        document_ids=SLIM_DOC_IDS,
        source=TEST_SOURCE,  # Slack — not in SOURCES_WITH_HIERARCHY_NODE_DOCUMENTS
        commit=False,
    )
    assert linked == 0
