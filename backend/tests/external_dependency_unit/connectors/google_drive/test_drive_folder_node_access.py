"""A run that does not read folder permissions must keep the stored access of
folder nodes. The first run of a perm-synced pair reads permissions; later
indexing runs and pruning do not. Doc sync rewrites the access in the form
that group sync stores."""

import time
from collections.abc import Callable, Iterator
from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import patch

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ee.onyx.db.hierarchy import _get_accessible_hierarchy_nodes_for_source
from ee.onyx.external_permissions.google_drive.doc_sync import gdrive_doc_sync
from ee.onyx.external_permissions.models import DocSyncResume
from ee.onyx.external_permissions.perm_sync_types import DocSyncCheckpointer
from onyx.access.models import NodeExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import GoogleDriveCheckpoint
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.models import ConnectorCheckpoint, HierarchyNode
from onyx.db.enums import HierarchyNodeType
from onyx.db.hierarchy import (
    get_hierarchy_node_by_raw_id,
    update_hierarchy_node_permissions,
    upsert_hierarchy_nodes_batch,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import HierarchyNode as DBHierarchyNode
from onyx.db.utils import DocumentRow, SortOrder
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)
from tests.external_dependency_unit.connectors.google_drive.conftest import (
    _SMALL_CORPUS,
    MockDrive,
)

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


class _FreshCrawl(DocSyncCheckpointer):
    @property
    def resume(self) -> DocSyncResume | None:
        return None

    def save(
        self,
        checkpoint: ConnectorCheckpoint,  # noqa: ARG002
        poll_range_start: datetime | None,  # noqa: ARG002
        poll_range_end: datetime,  # noqa: ARG002
    ) -> None:
        return None


def _no_docs(sort_order: SortOrder | None = None) -> list[DocumentRow]:  # noqa: ARG001
    return []


def _no_doc_ids() -> list[str]:
    return []


def _doc_sync(connector: GoogleDriveConnector) -> list[NodeExternalAccess]:
    """The node access that the Drive doc sync yields."""
    cc_pair = cast(ConnectorCredentialPair, SimpleNamespace(last_time_perm_sync=None))
    with patch(
        "ee.onyx.external_permissions.google_drive.doc_sync.build_perm_sync_connector",
        return_value=connector,
    ):
        return [
            element
            for element in gdrive_doc_sync(
                cc_pair, _no_docs, _no_doc_ids, None, _FreshCrawl()
            )
            if isinstance(element, NodeExternalAccess)
        ]


def _write_node_access(db_session: Session, element: NodeExternalAccess) -> None:
    # As the doc sync task writes a node's access.
    access = element.external_access
    update_hierarchy_node_permissions(
        db_session=db_session,
        raw_node_id=element.raw_node_id,
        source=DocumentSource(element.source),
        is_public=access.is_public,
        external_user_emails=list(access.external_user_emails) or None,
        external_user_group_ids=list(access.external_user_group_ids) or None,
    )


def _group_synced_ids(group_ids: set[str]) -> set[str]:
    """The ids that group sync stores for these Drive groups."""
    return {
        build_ext_group_name_for_onyx(group_id, DocumentSource.GOOGLE_DRIVE)
        for group_id in group_ids
    }


def _stored_group_ids(db_session: Session, raw_ids: list[str]) -> dict[str, set[str]]:
    rows = {
        raw_id: get_hierarchy_node_by_raw_id(
            db_session, raw_id, DocumentSource.GOOGLE_DRIVE
        )
        for raw_id in raw_ids
    }
    return {
        raw_id: set(row.external_user_group_ids or []) if row else set()
        for raw_id, row in rows.items()
    }


def _visible_to_group_member(db_session: Session, group_ids: set[str]) -> set[str]:
    return {
        n.raw_node_id
        for n in _get_accessible_hierarchy_nodes_for_source(
            db_session,
            DocumentSource.GOOGLE_DRIVE,
            _OUTSIDER,
            sorted(_group_synced_ids(group_ids)),
        )
    }


def test_doc_sync_keeps_folder_node_group_access(
    own_mock_drive: MockDrive,
    db_session: Session,
    ee_drive_nodes: None,  # noqa: ARG001
) -> None:
    # Folder permissions are read as the admin, so the admin joins every
    # drive. A group is a member of one of them.
    own_mock_drive.set_corpus({**_SMALL_CORPUS, "admin_drive_membership": 1.0})
    connector = own_mock_drive.build_connector()
    connector.set_raw_file_callback(_discard_raw_file)
    _persist(
        db_session,
        _run(connector, connector.load_from_checkpoint_with_perm_sync, 0, time.time()),
    )
    synced = _doc_sync(own_mock_drive.build_connector())
    # Doc sync yields the bare ids that group sync also reads from Drive.
    group_folders = {
        element.raw_node_id: set(element.external_access.external_user_group_ids)
        for element in synced
        if not element.external_access.is_public
        and element.external_access.external_user_group_ids
        and _OUTSIDER not in element.external_access.external_user_emails
    }
    assert group_folders, "the corpus has no folder shared with a group"
    expected = {
        raw_id: _group_synced_ids(group_ids)
        for raw_id, group_ids in group_folders.items()
    }
    raw_ids = list(group_folders)
    db_session.expire_all()
    assert _stored_group_ids(db_session, raw_ids) == expected

    for element in synced:
        _write_node_access(db_session, element)
    db_session.expire_all()

    assert _stored_group_ids(db_session, raw_ids) == expected
    for raw_id, group_ids in group_folders.items():
        assert raw_id in _visible_to_group_member(db_session, group_ids)
    assert not (set(raw_ids) & _visible_to_outsider(db_session))
