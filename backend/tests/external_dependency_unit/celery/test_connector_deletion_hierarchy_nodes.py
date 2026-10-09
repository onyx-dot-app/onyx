"""Connector deletion drops cc_pair join rows, then cleanup_unowned_hierarchy_nodes
deletes nodes no remaining connector owns. SOURCE roots stay; shared nodes stay.
Node persist and ownership links commit together so cleanup cannot delete a live node."""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.connectors.models import InputType
from onyx.db.connector_credential_pair import (
    delete_connector_credential_pair__no_commit,
)
from onyx.db.enums import AccessType, ConnectorCredentialPairStatus, HierarchyNodeType
from onyx.db.hierarchy import (
    cleanup_unowned_hierarchy_nodes,
    ensure_source_node_exists,
    get_all_hierarchy_nodes_for_source,
    get_hierarchy_node_by_raw_id,
    persist_hierarchy_nodes_for_cc_pair,
    upsert_hierarchy_node_cc_pair_entries,
    upsert_hierarchy_nodes_batch,
)
from onyx.db.models import (
    Connector,
    ConnectorCredentialPair,
    Credential,
    HierarchyNodeByConnectorCredentialPair,
)
from onyx.db.models import HierarchyNode as DBHierarchyNode

TEST_SOURCE = DocumentSource.GURU
SHARED_NODE_ID = "shared-folder"
UNIQUE_NODE_ID = "unique-folder"


def _create_cc_pair(db_session: Session) -> ConnectorCredentialPair:
    connector = Connector(
        name=f"Test {TEST_SOURCE.value} Connector {uuid4().hex[:8]}",
        source=TEST_SOURCE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={},
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        source=TEST_SOURCE,
        credential_json={},
        admin_public=True,
    )
    db_session.add(credential)
    db_session.flush()
    db_session.expire(credential)

    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"Test {TEST_SOURCE.value} CC Pair",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
    )
    db_session.add(cc_pair)
    db_session.commit()
    db_session.refresh(cc_pair)
    return cc_pair


def _cleanup_test_data(db_session: Session) -> None:
    test_connector_ids_q = db_session.query(Connector.id).filter(
        Connector.source == TEST_SOURCE,
        Connector.name.like("Test %"),
    )
    db_session.query(HierarchyNodeByConnectorCredentialPair).filter(
        HierarchyNodeByConnectorCredentialPair.connector_id.in_(test_connector_ids_q)
    ).delete(synchronize_session="fetch")
    db_session.query(DBHierarchyNode).filter(
        DBHierarchyNode.source == TEST_SOURCE
    ).delete()
    db_session.flush()

    credential_ids = [
        row[0]
        for row in db_session.query(ConnectorCredentialPair.credential_id)
        .filter(ConnectorCredentialPair.connector_id.in_(test_connector_ids_q))
        .all()
    ]
    db_session.query(ConnectorCredentialPair).filter(
        ConnectorCredentialPair.connector_id.in_(test_connector_ids_q)
    ).delete(synchronize_session="fetch")
    db_session.query(Connector).filter(
        Connector.source == TEST_SOURCE,
        Connector.name.like("Test %"),
    ).delete(synchronize_session="fetch")
    if credential_ids:
        db_session.query(Credential).filter(Credential.id.in_(credential_ids)).delete(
            synchronize_session="fetch"
        )
    db_session.commit()


def _folder_node(raw_node_id: str) -> PydanticHierarchyNode:
    return PydanticHierarchyNode(
        raw_node_id=raw_node_id,
        raw_parent_id=None,
        display_name=raw_node_id,
        node_type=HierarchyNodeType.FOLDER,
    )


def _delete_cc_pair_and_cleanup(
    db_session: Session, cc_pair: ConnectorCredentialPair
) -> tuple[list[str], list[DBHierarchyNode]]:
    """Same order as connector deletion: cc_pair CASCADE, then orphan cleanup."""
    source = cc_pair.connector.source
    delete_connector_credential_pair__no_commit(
        db_session,
        cc_pair.connector_id,
        cc_pair.credential_id,
    )
    db_session.flush()
    return cleanup_unowned_hierarchy_nodes(
        db_session=db_session, source=source, commit=True
    )


def test_deleting_last_connector_of_source_removes_unowned_nodes(
    db_session: Session,
) -> None:
    _cleanup_test_data(db_session)
    source_node = ensure_source_node_exists(db_session, TEST_SOURCE, commit=True)
    cc_pair = _create_cc_pair(db_session)

    upserted = upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=[_folder_node(SHARED_NODE_ID), _folder_node(UNIQUE_NODE_ID)],
        source=TEST_SOURCE,
        commit=True,
        is_connector_public=False,
    )
    upsert_hierarchy_node_cc_pair_entries(
        db_session=db_session,
        hierarchy_node_ids=[n.id for n in upserted],
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        commit=True,
    )

    deleted_raw_ids, _reparented = _delete_cc_pair_and_cleanup(db_session, cc_pair)

    assert set(deleted_raw_ids) == {SHARED_NODE_ID, UNIQUE_NODE_ID}
    remaining = get_all_hierarchy_nodes_for_source(db_session, TEST_SOURCE)
    assert {n.id for n in remaining} == {source_node.id}
    assert get_hierarchy_node_by_raw_id(db_session, SHARED_NODE_ID, TEST_SOURCE) is None
    assert get_hierarchy_node_by_raw_id(db_session, UNIQUE_NODE_ID, TEST_SOURCE) is None

    _cleanup_test_data(db_session)


def test_deleting_connector_keeps_nodes_still_owned_by_another(
    db_session: Session,
) -> None:
    _cleanup_test_data(db_session)
    ensure_source_node_exists(db_session, TEST_SOURCE, commit=True)
    cc_pair_1 = _create_cc_pair(db_session)
    cc_pair_2 = _create_cc_pair(db_session)

    upserted = upsert_hierarchy_nodes_batch(
        db_session=db_session,
        nodes=[_folder_node(SHARED_NODE_ID), _folder_node(UNIQUE_NODE_ID)],
        source=TEST_SOURCE,
        commit=True,
        is_connector_public=False,
    )
    by_raw_id = {n.raw_node_id: n.id for n in upserted}
    upsert_hierarchy_node_cc_pair_entries(
        db_session=db_session,
        hierarchy_node_ids=list(by_raw_id.values()),
        connector_id=cc_pair_1.connector_id,
        credential_id=cc_pair_1.credential_id,
        commit=True,
    )
    upsert_hierarchy_node_cc_pair_entries(
        db_session=db_session,
        hierarchy_node_ids=[by_raw_id[SHARED_NODE_ID]],
        connector_id=cc_pair_2.connector_id,
        credential_id=cc_pair_2.credential_id,
        commit=True,
    )

    deleted_raw_ids, _reparented = _delete_cc_pair_and_cleanup(db_session, cc_pair_1)

    assert deleted_raw_ids == [UNIQUE_NODE_ID]
    assert get_hierarchy_node_by_raw_id(db_session, UNIQUE_NODE_ID, TEST_SOURCE) is None
    assert (
        get_hierarchy_node_by_raw_id(db_session, SHARED_NODE_ID, TEST_SOURCE)
        is not None
    )

    _cleanup_test_data(db_session)


def test_persisted_nodes_survive_source_wide_orphan_cleanup(
    db_session: Session,
) -> None:
    """Ownership links commit with the node, so orphan cleanup must keep it."""
    _cleanup_test_data(db_session)
    ensure_source_node_exists(db_session, TEST_SOURCE, commit=True)
    cc_pair = _create_cc_pair(db_session)

    persist_hierarchy_nodes_for_cc_pair(
        db_session=db_session,
        nodes=[_folder_node(SHARED_NODE_ID)],
        source=TEST_SOURCE,
        connector_id=cc_pair.connector_id,
        credential_id=cc_pair.credential_id,
        is_connector_public=False,
        commit=True,
    )

    deleted_raw_ids, _reparented = cleanup_unowned_hierarchy_nodes(
        db_session, TEST_SOURCE, commit=True
    )
    assert SHARED_NODE_ID not in deleted_raw_ids
    assert (
        get_hierarchy_node_by_raw_id(db_session, SHARED_NODE_ID, TEST_SOURCE)
        is not None
    )

    _cleanup_test_data(db_session)
