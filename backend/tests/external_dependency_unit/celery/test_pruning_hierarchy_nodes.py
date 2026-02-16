"""
External dependency unit tests for pruning hierarchy node extraction and DB persistence.

Verifies that:
1. extract_ids_from_runnable_connector correctly separates hierarchy nodes from doc IDs
2. Extracted hierarchy nodes are correctly upserted to Postgres via upsert_hierarchy_nodes_batch
3. Upserting is idempotent (running twice doesn't duplicate nodes)

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
from onyx.db.hierarchy import upsert_hierarchy_nodes_batch
from onyx.db.models import HierarchyNode as DBHierarchyNode
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface

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


def _make_slim_docs() -> list[SlimDocument | PydanticHierarchyNode]:
    return [SlimDocument(id=doc_id) for doc_id in SLIM_DOC_IDS]


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


def _cleanup_test_hierarchy_nodes(db_session: Session) -> None:
    """Remove all hierarchy nodes for TEST_SOURCE to isolate tests."""
    db_session.query(DBHierarchyNode).filter(
        DBHierarchyNode.source == TEST_SOURCE
    ).delete()
    db_session.commit()


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
    assert result.doc_ids == expected_ids

    # Hierarchy nodes should be the 3 channels
    assert len(result.hierarchy_nodes) == 3
    extracted_raw_ids = {n.raw_node_id for n in result.hierarchy_nodes}
    assert extracted_raw_ids == {CHANNEL_A_ID, CHANNEL_B_ID, CHANNEL_C_ID}


def test_pruning_upserts_hierarchy_nodes_to_db(db_session: Session) -> None:
    """Full flow: extract hierarchy nodes from mock connector, upsert to Postgres,
    then verify the DB state (node count, parent relationships, permissions)."""
    _cleanup_test_hierarchy_nodes(db_session)

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
    _cleanup_test_hierarchy_nodes(db_session)

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
    _cleanup_test_hierarchy_nodes(db_session)

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
    _cleanup_test_hierarchy_nodes(db_session)

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
