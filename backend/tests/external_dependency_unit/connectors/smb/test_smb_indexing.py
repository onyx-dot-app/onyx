"""Indexing a live share: the full index, a poll, pruning and the checkpoint."""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.models import (
    CapabilityCheckContext,
    CheckNotApplicableError,
)
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    SlimDocument,
    TextSection,
)
from onyx.connectors.smb import connector as smb_connector
from onyx.connectors.smb.capability_checks import (
    KERBEROS_TICKET_CHECK_ID,
    build_smb_indexing_checks,
)
from onyx.connectors.smb.connector import SmbConnector
from onyx.connectors.smb.models import SmbCheckpoint
from tests.external_dependency_unit.connectors.smb.conftest import (
    HOST,
    SHARE,
    ConnectorFactory,
    credential_json,
)
from tests.external_dependency_unit.connectors.smb.smb_share_admin import ShareAdmin

ROOT_ID = f"smb://{HOST.lower()}/{SHARE}"
EPOCH = 0.0
A_LONG_TIME_AGO = datetime(2001, 9, 9, tzinfo=timezone.utc).timestamp()

Item = Document | HierarchyNode | ConnectorFailure


def _step(
    connector: SmbConnector, start: float, end: float, checkpoint: SmbCheckpoint
) -> tuple[list[Item], SmbCheckpoint]:
    items: list[Item] = []
    next_checkpoint: SmbCheckpoint | None = None
    for document, node, failure, returned in CheckpointOutputWrapper[SmbCheckpoint]()(
        connector.load_from_checkpoint(start, end, checkpoint)
    ):
        items.extend(item for item in (document, node, failure) if item is not None)
        next_checkpoint = returned or next_checkpoint
    assert next_checkpoint is not None
    return items, connector.validate_checkpoint_json(next_checkpoint.model_dump_json())


def _index(
    connector: SmbConnector, start: float = EPOCH, end: float | None = None
) -> list[Item]:
    items: list[Item] = []
    checkpoint = connector.build_dummy_checkpoint()
    # The server's clock is the test machine's clock.
    window_end = end if end is not None else time.time() + 60
    while checkpoint.has_more:
        step_items, checkpoint = _step(connector, start, window_end, checkpoint)
        items.extend(step_items)
    assert not [item for item in items if isinstance(item, ConnectorFailure)]
    return items


def _texts(items: list[Item]) -> dict[str, str]:
    return {
        item.id.removeprefix(f"{ROOT_ID}/"): "".join(
            section.text
            for section in item.sections
            if isinstance(section, TextSection)
        )
        for item in items
        if isinstance(item, Document)
    }


def _slim_ids(connector: SmbConnector) -> set[str]:
    return {
        item.id.removeprefix(f"{ROOT_ID}/")
        for batch in connector.retrieve_all_slim_docs()
        for item in batch
        if isinstance(item, SlimDocument)
    }


def _newest_change(connector: SmbConnector, folder: str) -> datetime:
    """The newest timestamp below ``folder``, by the server's clock."""
    newest = datetime.fromtimestamp(0, tz=timezone.utc)
    pending = [folder]
    while pending:
        current = pending.pop()
        for entry in connector.ops.list_folder(path=current):
            newest = max(newest, entry.changed_at)
            if entry.is_directory:
                pending.append(f"{current}/{entry.name}")
    return newest


def test_full_index_reads_the_tree_with_its_folders(
    share_admin: ShareAdmin, workspace: str, connector_factory: ConnectorFactory
) -> None:
    share_admin.write(f"{workspace}/readme.txt", "top level")
    share_admin.write(f"{workspace}/Projects/Alpha/plan.txt", "alpha plan")
    share_admin.write(f"{workspace}/Projects/~$plan.docx", "an Office lock file")
    share_admin.write(f"{workspace}/Projects/drawing.dwg", "not a supported type")
    share_admin.write(f"{workspace}/Archive/old.txt", "excluded")
    connector = connector_factory(workspace, excluded_paths=[f"{workspace}/archive"])

    items = _index(connector)

    assert _texts(items) == {
        f"{workspace}/readme.txt": "top level",
        f"{workspace}/Projects/Alpha/plan.txt": "alpha plan",
    }
    nodes = {
        item.raw_node_id: item.raw_parent_id
        for item in items
        if isinstance(item, HierarchyNode)
    }
    assert nodes == {
        ROOT_ID: None,
        f"{ROOT_ID}/{workspace}": ROOT_ID,
        f"{ROOT_ID}/{workspace}/Projects": f"{ROOT_ID}/{workspace}",
        f"{ROOT_ID}/{workspace}/Projects/Alpha": f"{ROOT_ID}/{workspace}/Projects",
    }
    plan = next(
        item
        for item in items
        if isinstance(item, Document) and item.id.endswith("plan.txt")
    )
    assert plan.source is DocumentSource.SMB
    assert plan.parent_hierarchy_raw_node_id == f"{ROOT_ID}/{workspace}/Projects/Alpha"
    assert plan.metadata["path"] == (
        f"\\\\{HOST}\\{SHARE}\\{workspace}\\Projects\\Alpha\\plan.txt"
    )


def test_poll_reads_a_modified_file_and_a_copied_one_and_nothing_else(
    share_admin: ShareAdmin, workspace: str, connector_factory: ConnectorFactory
) -> None:
    share_admin.write(f"{workspace}/edited.txt", "first draft")
    share_admin.write(f"{workspace}/untouched.txt", "stays the same")
    connector = connector_factory(workspace)
    assert set(_texts(_index(connector))) == {
        f"{workspace}/edited.txt",
        f"{workspace}/untouched.txt",
    }
    # Every later change on the server has a newer timestamp than this.
    poll_start = (
        _newest_change(connector, workspace) + timedelta(microseconds=1)
    ).timestamp()

    share_admin.write(f"{workspace}/edited.txt", "second draft")
    # A copy keeps the last write time of its origin: only its creation time
    # says that the share has not seen it before.
    share_admin.write(f"{workspace}/copied.txt", "copied onto the share")
    share_admin.set_last_write_time(f"{workspace}/copied.txt", A_LONG_TIME_AGO)

    assert _texts(_index(connector, start=poll_start)) == {
        f"{workspace}/edited.txt": "second draft",
        f"{workspace}/copied.txt": "copied onto the share",
    }


def test_slim_listing_drops_a_deleted_file_so_pruning_removes_it(
    share_admin: ShareAdmin, workspace: str, connector_factory: ConnectorFactory
) -> None:
    share_admin.write(f"{workspace}/kept.txt", "kept")
    share_admin.write(f"{workspace}/Sub/deleted.txt", "deleted")
    connector = connector_factory(workspace)
    assert _slim_ids(connector) == {
        f"{workspace}/kept.txt",
        f"{workspace}/Sub/deleted.txt",
    }

    share_admin.remove(f"{workspace}/Sub/deleted.txt")

    assert _slim_ids(connector) == {f"{workspace}/kept.txt"}


def test_checkpoint_resumes_in_the_middle_of_a_folder(
    share_admin: ShareAdmin, workspace: str, connector_factory: ConnectorFactory
) -> None:
    for name in ("a", "b", "c", "d", "e"):
        share_admin.write(f"{workspace}/{name}.txt", name)
    share_admin.write(f"{workspace}/Sub/f.txt", "f")
    end = time.time() + 60

    with patch.object(smb_connector, "FILES_PER_STEP", 2):
        first, checkpoint = _step(
            connector_factory(workspace), EPOCH, end, SmbCheckpoint(has_more=True)
        )
        assert set(_texts(first)) == {f"{workspace}/a.txt", f"{workspace}/b.txt"}
        assert checkpoint.has_more and checkpoint.last_name == "b.txt"

        # A new connector, as after a restart of the worker, with the stored
        # checkpoint.
        resumed = connector_factory(workspace)
        rest: list[Item] = []
        while checkpoint.has_more:
            step_items, checkpoint = _step(resumed, EPOCH, end, checkpoint)
            rest.extend(step_items)

    assert set(_texts(rest)) == {
        f"{workspace}/c.txt",
        f"{workspace}/d.txt",
        f"{workspace}/e.txt",
        f"{workspace}/Sub/f.txt",
    }


def test_a_folder_the_service_account_may_not_list_is_out_of_scope(
    connector_factory: ConnectorFactory,
) -> None:
    """The seed script makes ``Fixtures/NoAccess`` readable by administrators
    only."""
    connector = connector_factory("Fixtures", excluded_paths=["Fixtures/Loop"])

    assert set(_texts(_index(connector))) == {"Fixtures/readme.txt"}
    assert _slim_ids(connector) == {"Fixtures/readme.txt"}


def test_a_link_loop_on_the_server_ends_at_the_depth_limit(
    connector_factory: ConnectorFactory,
) -> None:
    """The seed script links ``Fixtures/Loop/again`` to ``Fixtures``. Samba
    follows the link and shows a plain folder."""
    connector = connector_factory("Fixtures/Loop")

    with patch.object(smb_connector, "MAX_FOLDER_DEPTH", 6):
        nodes = [item for item in _index(connector) if isinstance(item, HierarchyNode)]

    deepest = max(
        node.raw_node_id.removeprefix(f"{ROOT_ID}/").count("/") + 1 for node in nodes
    )
    assert deepest == 6


def test_every_indexing_check_passes_for_the_service_account(
    share_admin: ShareAdmin, workspace: str, connector_factory: ConnectorFactory
) -> None:
    share_admin.write(f"{workspace}/readme.txt", "readable")
    connector = connector_factory(workspace)
    context = CapabilityCheckContext(
        source=DocumentSource.SMB,
        credential_json=credential_json(),
        connector_specific_config=connector.config().model_dump(mode="json"),
        source_operations=connector.ops,
    )

    not_applicable: list[str] = []
    for check in build_smb_indexing_checks():
        try:
            check.run(context)
        except CheckNotApplicableError:
            not_applicable.append(check.check_id)

    # The service account signs in with NTLM here.
    assert not_applicable == [KERBEROS_TICKET_CHECK_ID]
