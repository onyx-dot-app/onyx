"""Regression tests for hierarchy-node walker mis-parenting bugs in the
Google Drive connector.

Both tests drive `_get_new_ancestors_for_files` directly with a stubbed
`_get_folder_metadata`, then replay the resulting nodes through the real
`ConnectorRunner.run` (via a tiny test-only `CheckpointedConnector` that
just yields the precomputed list). For each batch the runner emits we
hand it to the *production* `cache_and_upsert_hierarchy_nodes` helper
(`run_docfetching.py`) so sanitization, the cc_pair join-table write,
and the Redis caching all run in the test exactly the way they do in
production. Using the production runner + persistence helper means the
tests stay honest if either ever changes.

These tests exist *first* to demonstrate that two distinct failure modes
exist in the current code:

1. ``test_off_by_one_batch_split_misparents_child``
   Off-by-one batch split: walker emits ancestors child-first, the runner
   chops the stream at fixed slice boundaries, and the child whose parent
   lands in the next slice gets fallback-parented to the SOURCE node.

2. ``test_cross_yield_walk_does_not_heal_misparented_child``
   Cross-yield healing gap: a node yielded with an unresolvable parent in
   one walk stays mis-parented forever because the walker's
   ``seen_hierarchy_node_raw_ids`` short-circuit prevents re-yield even
   after a later walk discovers the missing ancestor.

After the planned fixes both tests should pass.
"""

from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import Mock
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.background.indexing.run_docfetching import cache_and_upsert_hierarchy_nodes
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.connector_runner import ConnectorRunner
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.models import DriveRetrievalStage
from onyx.connectors.google_drive.models import GoogleDriveCheckpoint
from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.connectors.google_drive.models import RetrievedDriveFile
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import HierarchyNode as PydanticHierarchyNode
from onyx.connectors.models import InputType
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.hierarchy import ensure_source_node_exists
from onyx.db.hierarchy import get_hierarchy_node_by_raw_id
from onyx.db.hierarchy import get_source_hierarchy_node
from onyx.db.models import Connector
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential
from onyx.db.models import HierarchyNode
from onyx.utils.threadpool_concurrency import ThreadSafeDict
from onyx.utils.threadpool_concurrency import ThreadSafeSet

SOURCE = DocumentSource.GOOGLE_DRIVE
ADMIN_EMAIL = "admin@example.com"
USER_X_EMAIL = "x@example.com"
USER_Y_EMAIL = "y@example.com"


def _make_connector() -> GoogleDriveConnector:
    """Build a `GoogleDriveConnector` with the minimum surface needed to
    invoke `_get_new_ancestors_for_files`.

    `get_drive_service` is module-level patched by callers; here we just set
    the credential sentinel and admin email that the function reads.
    """
    connector = GoogleDriveConnector(include_shared_drives=True)
    connector._primary_admin_email = ADMIN_EMAIL
    connector._creds = Mock(name="creds")
    return connector


def _folder(
    folder_id: str,
    parent_id: str | None,
    *,
    drive_id: str | None = None,
    name: str | None = None,
) -> GoogleDriveFileType:
    """Build a fake drive folder dict in the shape returned by files().get()."""
    folder: GoogleDriveFileType = {
        "id": folder_id,
        "name": name or folder_id,
        "webViewLink": f"https://drive.google.com/drive/folders/{folder_id}",
        "parents": [parent_id] if parent_id else [],
    }
    if drive_id is not None:
        folder["driveId"] = drive_id
    return folder


def _shared_drive_root(
    folder_id: str, name: str = "TestSharedDrive"
) -> GoogleDriveFileType:
    """A verified shared drive root: id == driveId, no parents."""
    return _folder(folder_id, parent_id=None, drive_id=folder_id, name=name)


def _retrieved_file(
    file_id: str, parent_id: str, user_email: str
) -> RetrievedDriveFile:
    return RetrievedDriveFile(
        completion_stage=DriveRetrievalStage.SHARED_DRIVE_FILES,
        drive_file={
            "id": file_id,
            "name": file_id,
            "parents": [parent_id],
            "webViewLink": f"https://drive.google.com/file/d/{file_id}",
        },
        user_email=user_email,
        parent_id=parent_id,
    )


class _PrecomputedHierarchyConnector(CheckpointedConnector[GoogleDriveCheckpoint]):
    """Minimal `CheckpointedConnector` that yields a precomputed list of
    hierarchy nodes. Used to drive the *real* `ConnectorRunner.run` in
    tests without having to mock the entire Google Drive API surface that
    the production `GoogleDriveConnector.load_from_checkpoint` walks.
    """

    def __init__(self, nodes: list[PydanticHierarchyNode]) -> None:
        self._nodes = nodes

    def load_credentials(
        self,
        credentials: dict[str, Any],  # noqa: ARG002
    ) -> dict[str, Any] | None:
        return None

    def build_dummy_checkpoint(self) -> GoogleDriveCheckpoint:
        return GoogleDriveCheckpoint(
            retrieved_folder_and_drive_ids=set(),
            completion_stage=DriveRetrievalStage.DONE,
            completion_map=ThreadSafeDict(),
            all_retrieved_file_ids=set(),
            has_more=False,
        )

    def validate_checkpoint_json(
        self,
        checkpoint_json: str,  # noqa: ARG002
    ) -> GoogleDriveCheckpoint:
        raise NotImplementedError

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
        checkpoint: GoogleDriveCheckpoint,  # noqa: ARG002
    ) -> CheckpointOutput[GoogleDriveCheckpoint]:
        for node in self._nodes:
            yield node
        return self.build_dummy_checkpoint()


def _run_through_runner_and_persist(
    db_connector: Connector,
    db_credential: Credential,
    nodes: list[PydanticHierarchyNode],
    batch_size: int = INDEX_BATCH_SIZE,
) -> int:
    """Drive the real `ConnectorRunner` over the given node list, calling
    the production `cache_and_upsert_hierarchy_nodes` helper for each batch
    the runner emits — exactly the way `run_docfetching.py` does in
    production. This exercises sanitization, the cc_pair join-table write,
    and Redis caching alongside the upsert.

    Returns the number of hierarchy-node batches the runner produced (for
    optional sanity assertions).
    """
    test_connector = _PrecomputedHierarchyConnector(nodes)
    runner: ConnectorRunner[GoogleDriveCheckpoint] = ConnectorRunner(
        connector=test_connector,
        batch_size=batch_size,
        include_permissions=False,
        time_range=(
            datetime(2020, 1, 1, tzinfo=timezone.utc),
            datetime(2030, 1, 1, tzinfo=timezone.utc),
        ),
    )
    starting_checkpoint = test_connector.build_dummy_checkpoint()
    starting_checkpoint.has_more = True

    batch_count = 0
    for _docs, hierarchy_batch, _failure, _next_cp in runner.run(starting_checkpoint):
        if not hierarchy_batch:
            continue
        cache_and_upsert_hierarchy_nodes(
            db_connector=db_connector,
            db_credential=db_credential,
            is_connector_public=False,
            hierarchy_node_batch=hierarchy_batch,
        )
        batch_count += 1
    return batch_count


def _create_test_cc_pair_triple(
    db_session: Session,
) -> tuple[Connector, Credential, ConnectorCredentialPair]:
    """Create a fresh `(Connector, Credential, ConnectorCredentialPair)`
    triple for `cache_and_upsert_hierarchy_nodes` to write the join-table
    rows against. Caller is responsible for cleanup via
    `_cleanup_cc_pair_triple`.
    """
    unique = uuid4().hex[:8]
    connector = Connector(
        name=f"test-gdrive-walker-{unique}",
        source=SOURCE,
        input_type=InputType.POLL,
        connector_specific_config={"include_shared_drives": True},
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )
    db_session.add(connector)
    db_session.flush()

    credential = Credential(
        source=SOURCE,
        credential_json={},
        user_id=None,
    )
    db_session.add(credential)
    db_session.flush()

    cc_pair = ConnectorCredentialPair(
        connector_id=connector.id,
        credential_id=credential.id,
        name=f"test-gdrive-walker-cc-{unique}",
        status=ConnectorCredentialPairStatus.ACTIVE,
        access_type=AccessType.PUBLIC,
        auto_sync_options=None,
    )
    db_session.add(cc_pair)
    db_session.commit()
    db_session.refresh(connector)
    db_session.refresh(credential)
    db_session.refresh(cc_pair)
    return connector, credential, cc_pair


def _cleanup_cc_pair_triple(
    db_session: Session,
    connector: Connector,
    credential: Credential,
) -> None:
    """Delete the cc_pair, credential, and connector. The cascading FKs on
    `HierarchyNodeByConnectorCredentialPair` clean the join table up too."""
    db_session.execute(
        delete(ConnectorCredentialPair).where(
            ConnectorCredentialPair.connector_id == connector.id
        )
    )
    db_session.execute(delete(Credential).where(Credential.id == credential.id))
    db_session.execute(delete(Connector).where(Connector.id == connector.id))
    db_session.commit()


def _cleanup_nodes(db_session: Session, raw_node_id_prefix: str) -> None:
    """Delete every HierarchyNode for `SOURCE` whose raw_node_id starts with
    the given prefix. The SOURCE node is preserved (it never matches)."""
    db_session.execute(
        delete(HierarchyNode).where(
            HierarchyNode.source == SOURCE,
            HierarchyNode.raw_node_id.startswith(raw_node_id_prefix),
        )
    )
    db_session.commit()


def _stub_metadata_lookup(
    folders_by_id: dict[str, GoogleDriveFileType | None],
) -> Callable[..., GoogleDriveFileType | None]:
    """Build a side_effect function for `_get_folder_metadata` that returns
    folders out of a dict, treating `None` as 'inaccessible'."""

    def _side_effect(
        folder_id: str,
        retriever_email: str,  # noqa: ARG001
        field_type: Any,  # noqa: ARG001
        failed_folder_ids_by_email: Any = None,  # noqa: ARG001
    ) -> GoogleDriveFileType | None:
        return folders_by_id.get(folder_id)

    return _side_effect


def test_off_by_one_batch_split_misparents_child(db_session: Session) -> None:
    """Issue 1: when ancestors yielded by the connector are split across
    `INDEX_BATCH_SIZE` slices, the child whose parent lands in the next
    slice falls back to the SOURCE node.

    Setup:
      - Single file F whose ancestor chain is
        ROOT (shared drive root) → P_n → P_{n-1} → ... → P_1 → P_0 → F
      - n = INDEX_BATCH_SIZE so the walker emits exactly
        INDEX_BATCH_SIZE + 1 ancestor nodes (P_0..P_{n-1}, ROOT).
      - With current child-first emission, slice 1 gets [P_0..P_{n-1}] and
        slice 2 gets [ROOT]. P_{n-1}'s parent (ROOT) is not in slice 1's
        node_by_id and not yet committed to the DB, so P_{n-1} falls back
        to SOURCE.

    Expected after the fix: every emitted node's stored parent matches its
    raw_parent_id (or SOURCE for the shared drive root).
    """
    test_id = "issue1_offbyone"
    chain_len = INDEX_BATCH_SIZE
    p_ids = [f"{test_id}_P{i}" for i in range(chain_len)]
    root_id = f"{test_id}_ROOT"

    folders: dict[str, GoogleDriveFileType | None] = {}
    for i, p_id in enumerate(p_ids):
        parent_of_p = p_ids[i + 1] if i + 1 < chain_len else root_id
        folders[p_id] = _folder(p_id, parent_id=parent_of_p)
    folders[root_id] = _shared_drive_root(root_id)

    file = _retrieved_file(
        file_id=f"{test_id}_F", parent_id=p_ids[0], user_email=USER_X_EMAIL
    )

    db_connector, db_credential, _cc_pair = _create_test_cc_pair_triple(db_session)

    try:
        ensure_source_node_exists(db_session, SOURCE, commit=True)

        connector = _make_connector()

        with (
            patch(
                "onyx.connectors.google_drive.connector.get_drive_service",
                return_value=Mock(name="drive_service"),
            ),
            patch.object(
                connector,
                "_get_folder_metadata",
                side_effect=_stub_metadata_lookup(folders),
            ),
            patch.object(
                connector,
                "_get_shared_drive_name",
                return_value="TestSharedDrive",
            ),
        ):
            new_nodes = connector._get_new_ancestors_for_files(
                files=[file],
                seen_hierarchy_node_raw_ids=ThreadSafeSet(),
                fully_walked_hierarchy_node_raw_ids=ThreadSafeSet(),
                failed_folder_ids_by_email=None,
                permission_sync_context=None,
                add_prefix=False,
            )

        assert len(new_nodes) == chain_len + 1, (
            f"Walker should emit one node per ancestor; got {len(new_nodes)}"
        )

        batch_count = _run_through_runner_and_persist(
            db_connector, db_credential, new_nodes
        )
        assert batch_count >= 2, (
            "Test setup must straddle a runner batch boundary to exercise "
            f"the bug; runner produced only {batch_count} batch(es) for "
            f"{len(new_nodes)} nodes."
        )

        db_session.expire_all()
        source_node = get_source_hierarchy_node(db_session, SOURCE)
        assert source_node is not None
        source_node_id = source_node.id

        stored = {
            raw_id: get_hierarchy_node_by_raw_id(db_session, raw_id, SOURCE)
            for raw_id in p_ids + [root_id]
        }
        for raw_id, node in stored.items():
            assert node is not None, f"Node {raw_id} was never persisted"

        root_node = stored[root_id]
        assert root_node is not None
        assert root_node.parent_id == source_node_id, (
            "Shared drive roots should always be parented to SOURCE"
        )

        misparented: list[tuple[str, str | None, int | None, int | None]] = []
        for i, raw_id in enumerate(p_ids):
            child = stored[raw_id]
            assert child is not None
            expected_parent_raw_id = p_ids[i + 1] if i + 1 < chain_len else root_id
            expected_parent = stored[expected_parent_raw_id]
            assert expected_parent is not None
            if child.parent_id != expected_parent.id:
                misparented.append(
                    (
                        raw_id,
                        expected_parent_raw_id,
                        expected_parent.id,
                        child.parent_id,
                    )
                )

        assert misparented == [], (
            "These nodes were mis-parented (likely to SOURCE) due to the "
            f"off-by-one batch split bug: {misparented}. SOURCE id is "
            f"{source_node_id}."
        )
    finally:
        _cleanup_nodes(db_session, test_id)
        _cleanup_cc_pair_triple(db_session, db_connector, db_credential)


def test_cross_yield_walk_does_not_heal_misparented_child(
    db_session: Session,
) -> None:
    """Issue 2: a node yielded with an unresolvable parent in one walk stays
    mis-parented to SOURCE forever because `seen_hierarchy_node_raw_ids`
    prevents re-yield even after a later walk discovers the missing
    ancestor.

    Setup:
      - Chain: ROOT (shared drive) → A → B → C → F
      - Yield 1 (user X): cannot fetch A. Walker emits [C, B], leaves
        ``fully_walked`` empty. Upsert: B is mis-parented to SOURCE
        because A is unknown.
      - Yield 2 (user Y, broader access): can fetch A. Walker climbs
        starting from B (the parent of file F2), but skips re-yielding B
        because it's already in ``seen``. Upsert: A and ROOT land
        correctly, but B's row never gets touched again.

    Expected after the fix: B's stored parent is updated to A in yield 2.
    """
    test_id = "issue2_crossyield"
    a_id = f"{test_id}_A"
    b_id = f"{test_id}_B"
    c_id = f"{test_id}_C"
    root_id = f"{test_id}_ROOT"

    folders_yield_1: dict[str, GoogleDriveFileType | None] = {
        c_id: _folder(c_id, parent_id=b_id),
        b_id: _folder(b_id, parent_id=a_id),
        a_id: None,
        root_id: _shared_drive_root(root_id),
    }
    folders_yield_2 = dict(folders_yield_1)
    folders_yield_2[a_id] = _folder(a_id, parent_id=root_id)

    file_yield_1 = _retrieved_file(
        file_id=f"{test_id}_F1", parent_id=c_id, user_email=USER_X_EMAIL
    )
    file_yield_2 = _retrieved_file(
        file_id=f"{test_id}_F2", parent_id=b_id, user_email=USER_Y_EMAIL
    )

    seen = ThreadSafeSet[str]()
    fully_walked = ThreadSafeSet[str]()

    db_connector, db_credential, _cc_pair = _create_test_cc_pair_triple(db_session)

    try:
        ensure_source_node_exists(db_session, SOURCE, commit=True)
        source_node = get_source_hierarchy_node(db_session, SOURCE)
        assert source_node is not None
        source_node_id = source_node.id

        connector = _make_connector()

        with (
            patch(
                "onyx.connectors.google_drive.connector.get_drive_service",
                return_value=Mock(name="drive_service"),
            ),
            patch.object(
                connector,
                "_get_shared_drive_name",
                return_value="TestSharedDrive",
            ),
        ):
            with patch.object(
                connector,
                "_get_folder_metadata",
                side_effect=_stub_metadata_lookup(folders_yield_1),
            ):
                new_nodes_1 = connector._get_new_ancestors_for_files(
                    files=[file_yield_1],
                    seen_hierarchy_node_raw_ids=seen,
                    fully_walked_hierarchy_node_raw_ids=fully_walked,
                    failed_folder_ids_by_email=None,
                    permission_sync_context=None,
                    add_prefix=False,
                )
            _run_through_runner_and_persist(db_connector, db_credential, new_nodes_1)

            db_session.expire_all()
            b_after_yield_1 = get_hierarchy_node_by_raw_id(db_session, b_id, SOURCE)
            assert b_after_yield_1 is not None
            assert b_after_yield_1.parent_id == source_node_id, (
                "Setup invariant: B should be mis-parented to SOURCE after "
                "yield 1 (its parent A is inaccessible). Got "
                f"parent_id={b_after_yield_1.parent_id}, SOURCE id={source_node_id}."
            )
            assert get_hierarchy_node_by_raw_id(db_session, a_id, SOURCE) is None, (
                "Setup invariant: A should not exist in the DB after yield 1."
            )

            with patch.object(
                connector,
                "_get_folder_metadata",
                side_effect=_stub_metadata_lookup(folders_yield_2),
            ):
                new_nodes_2 = connector._get_new_ancestors_for_files(
                    files=[file_yield_2],
                    seen_hierarchy_node_raw_ids=seen,
                    fully_walked_hierarchy_node_raw_ids=fully_walked,
                    failed_folder_ids_by_email=None,
                    permission_sync_context=None,
                    add_prefix=False,
                )
            _run_through_runner_and_persist(db_connector, db_credential, new_nodes_2)

        db_session.expire_all()
        a_node = get_hierarchy_node_by_raw_id(db_session, a_id, SOURCE)
        b_node = get_hierarchy_node_by_raw_id(db_session, b_id, SOURCE)
        root_node = get_hierarchy_node_by_raw_id(db_session, root_id, SOURCE)

        assert a_node is not None, "A should be persisted by yield 2"
        assert root_node is not None, "ROOT should be persisted by yield 2"
        assert b_node is not None

        assert a_node.parent_id == root_node.id, (
            "Sanity check: A should be parented to ROOT after yield 2."
        )

        assert b_node.parent_id == a_node.id, (
            "Cross-yield healing failed: B's parent_id was not updated to A "
            "after a later walk discovered A. Stored parent_id is "
            f"{b_node.parent_id} (A id={a_node.id}, SOURCE id={source_node_id})."
        )
    finally:
        _cleanup_nodes(db_session, test_id)
        _cleanup_cc_pair_triple(db_session, db_connector, db_credential)
