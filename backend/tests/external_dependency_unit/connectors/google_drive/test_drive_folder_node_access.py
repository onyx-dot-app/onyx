"""A run that does not read folder permissions must keep the stored access of
folder nodes. The first run of a perm-synced pair reads permissions; later
indexing runs and pruning do not."""

import time
from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ee.onyx.db.hierarchy import _get_accessible_hierarchy_nodes_for_source
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import GoogleDriveCheckpoint
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.models import HierarchyNode
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import get_hierarchy_node_by_raw_id, upsert_hierarchy_nodes_batch
from onyx.db.models import HierarchyNode as DBHierarchyNode
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)
from tests.external_dependency_unit.connectors.google_drive.conftest import MockDrive

_OUTSIDER = "outsider@not-in-the-folder-acl.example"

LoadFn = Callable[
    [float, float, GoogleDriveCheckpoint], CheckpointOutput[GoogleDriveCheckpoint]
]


def _discard_raw_file(file: object, content_type: str) -> str:  # noqa: ARG001
    return "staged"


def _run(
    connector: GoogleDriveConnector, load: LoadFn, start: float, end: float
) -> list[HierarchyNode]:
    nodes: list[HierarchyNode] = []
    checkpoint = connector.build_dummy_checkpoint()
    for _ in range(1000):
        output = load(start, end, checkpoint)
        while True:
            try:
                item = next(output)
            except StopIteration as stop:
                checkpoint = connector.validate_checkpoint_json(
                    stop.value.model_dump_json()
                )
                break
            if isinstance(item, HierarchyNode):
                nodes.append(item)
        if not checkpoint.has_more:
            return nodes
    raise AssertionError("listing did not finish")


def _persist(db_session: Session, nodes: list[HierarchyNode]) -> None:
    # As docfetching and pruning persist the nodes of a SYNC pair.
    upsert_hierarchy_nodes_batch(
        db_session,
        nodes,
        DocumentSource.GOOGLE_DRIVE,
        commit=True,
        is_connector_public=False,
    )


@pytest.fixture
def ee_drive_nodes(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """EE reads folder permissions. Removes the Drive nodes the test stores."""
    fetch_versioned_implementation.cache_clear()
    monkeypatch.setattr(global_version, "is_ee_version", lambda: True)
    yield
    db_session.rollback()
    db_session.execute(
        delete(DBHierarchyNode).where(
            DBHierarchyNode.source == DocumentSource.GOOGLE_DRIVE,
            DBHierarchyNode.node_type != HierarchyNodeType.SOURCE,
        )
    )
    db_session.commit()
    fetch_versioned_implementation.cache_clear()


def _private_folder_ids(nodes: list[HierarchyNode]) -> list[str]:
    return [
        n.raw_node_id
        for n in nodes
        if n.node_type == HierarchyNodeType.FOLDER
        and n.external_access is not None
        and not n.external_access.is_public
        and n.external_access.external_user_emails
        and _OUTSIDER not in n.external_access.external_user_emails
    ]


def _visible_to_outsider(db_session: Session) -> set[str]:
    return {
        n.raw_node_id
        for n in _get_accessible_hierarchy_nodes_for_source(
            db_session, DocumentSource.GOOGLE_DRIVE, _OUTSIDER, []
        )
    }


def _first_run(
    db_session: Session, connector: GoogleDriveConnector
) -> tuple[list[str], float]:
    connector.set_raw_file_callback(_discard_raw_file)
    end = time.time()
    nodes = _run(connector, connector.load_from_checkpoint_with_perm_sync, 0, end)
    _persist(db_session, nodes)
    private_ids = _private_folder_ids(nodes)
    assert private_ids, "the corpus has no private folder"
    db_session.expire_all()
    assert not (set(private_ids) & _visible_to_outsider(db_session))
    return private_ids, end


def _stored_access(
    db_session: Session, raw_ids: list[str]
) -> dict[str, tuple[bool, list[str] | None, list[str] | None]]:
    access: dict[str, tuple[bool, list[str] | None, list[str] | None]] = {}
    for raw_id in raw_ids:
        row = get_hierarchy_node_by_raw_id(
            db_session, raw_id, DocumentSource.GOOGLE_DRIVE
        )
        assert row is not None
        access[raw_id] = (
            row.is_public,
            row.external_user_emails,
            row.external_user_group_ids,
        )
    return access


def test_incremental_run_keeps_folder_node_access(
    mock_drive: MockDrive,
    db_session: Session,
    ee_drive_nodes: None,  # noqa: ARG001
) -> None:
    connector = mock_drive.build_connector()
    private_ids, first_end = _first_run(db_session, connector)
    before = _stored_access(db_session, private_ids)

    # Docfetching after a successful attempt runs without permissions.
    nodes = _run(connector, connector.load_from_checkpoint, first_end, time.time())
    assert all(node.external_access is None for node in nodes)
    _persist(db_session, nodes)
    db_session.expire_all()

    assert _stored_access(db_session, private_ids) == before
    assert not (set(private_ids) & _visible_to_outsider(db_session))


def test_pruning_keeps_folder_node_access(
    mock_drive: MockDrive,
    db_session: Session,
    ee_drive_nodes: None,  # noqa: ARG001
) -> None:
    connector = mock_drive.build_connector()
    private_ids, _ = _first_run(db_session, connector)
    before = _stored_access(db_session, private_ids)

    # Pruning lists without permissions.
    for batch in connector.retrieve_all_slim_docs():
        nodes = [item for item in batch if isinstance(item, HierarchyNode)]
        assert all(node.external_access is None for node in nodes)
        _persist(db_session, nodes)
    db_session.expire_all()

    assert _stored_access(db_session, private_ids) == before
    assert not (set(private_ids) & _visible_to_outsider(db_session))
