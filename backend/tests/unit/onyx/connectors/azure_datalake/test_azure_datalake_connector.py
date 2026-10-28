from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import MagicMock, create_autospec, patch

import pytest

from onyx.connectors.azure_datalake.connector import AzureDataLakeConnector
from onyx.connectors.azure_datalake.models import (
    AzureDataLakeCheckpoint,
    AzureDataLakeFile,
    AzureDataLakePath,
    AzureDataLakePathPage,
)
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeSourceOperations,
)
from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.exceptions import (
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    DocumentFailure,
    HierarchyNode,
    SlimDocument,
)

UPDATED = datetime(2026, 3, 1, tzinfo=timezone.utc)
OLD = datetime(2025, 1, 1, tzinfo=timezone.utc)
WINDOW_START = datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp()
WINDOW_END = datetime(2026, 4, 1, tzinfo=timezone.utc).timestamp()
ID_PREFIX = "azure_datalake:onyxtest:docs"


def _file(
    name: str, last_modified: datetime = UPDATED, size: int = 10
) -> AzureDataLakePath:
    return AzureDataLakePath(
        name=name, is_directory=False, last_modified=last_modified, content_length=size
    )


def _directory(name: str) -> AzureDataLakePath:
    return AzureDataLakePath(
        name=name, is_directory=True, last_modified=UPDATED, content_length=0
    )


@pytest.fixture(autouse=True)
def _no_unstructured_key() -> Generator[None, None, None]:
    with patch(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        return_value=None,
    ):
        yield


def _connector(
    pages: dict[str | None, AzureDataLakePathPage], path_prefix: str = ""
) -> tuple[AzureDataLakeConnector, MagicMock]:
    """A connector whose gateway serves ``pages`` by continuation token and
    returns each file's name as its text."""
    connector = AzureDataLakeConnector(
        account_name="onyxtest", container_name="docs", path_prefix=path_prefix
    )
    ops = create_autospec(AzureDataLakeSourceOperations, instance=True)
    ops.list_paths_page.side_effect = lambda **kwargs: pages[
        kwargs["continuation_token"]
    ]
    ops.read_file.side_effect = lambda *, path, max_bytes: AzureDataLakeFile(  # noqa: ARG005
        size=len(path), last_modified=UPDATED, content=path.encode()
    )
    connector._ops = ops
    return connector, ops


def _run(
    connector: AzureDataLakeConnector, checkpoint: AzureDataLakeCheckpoint
) -> tuple[list[Document | HierarchyNode | ConnectorFailure], AzureDataLakeCheckpoint]:
    items: list[Document | HierarchyNode | ConnectorFailure] = []
    next_checkpoint: AzureDataLakeCheckpoint | None = None
    for document, node, failure, returned in CheckpointOutputWrapper[
        AzureDataLakeCheckpoint
    ]()(connector.load_from_checkpoint(WINDOW_START, WINDOW_END, checkpoint)):
        items.extend(item for item in (document, node, failure) if item is not None)
        next_checkpoint = returned or next_checkpoint
    assert next_checkpoint is not None
    return items, connector.validate_checkpoint_json(next_checkpoint.model_dump_json())


def test_each_step_reads_one_page_and_resumes_from_its_cursor() -> None:
    connector, ops = _connector(
        {
            None: AzureDataLakePathPage(
                paths=[_directory("a"), _file("a/one.txt")], continuation_token="t1"
            ),
            "t1": AzureDataLakePathPage(
                paths=[_file("b.txt")], continuation_token=None
            ),
        }
    )

    first, checkpoint = _run(connector, connector.build_dummy_checkpoint())
    second, final = _run(connector, checkpoint)

    assert [type(item) for item in first] == [HierarchyNode, HierarchyNode, Document]
    assert checkpoint.continuation_token == "t1" and checkpoint.has_more
    assert [item.id for item in second if isinstance(item, Document)] == [
        f"{ID_PREFIX}:b.txt"
    ]
    assert not final.has_more
    assert ops.list_paths_page.call_count == 2


def test_documents_hang_under_their_directory_and_the_prefix() -> None:
    connector, _ = _connector(
        {
            None: AzureDataLakePathPage(
                paths=[_directory("root/sub"), _file("root/sub/x.md")],
                continuation_token=None,
            )
        },
        path_prefix="/root/",
    )

    items, _ = _run(connector, connector.build_dummy_checkpoint())

    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    assert [(node.raw_node_id, node.raw_parent_id) for node in nodes] == [
        (ID_PREFIX, None),
        (f"{ID_PREFIX}:root", ID_PREFIX),
        (f"{ID_PREFIX}:root/sub", f"{ID_PREFIX}:root"),
    ]
    document = next(item for item in items if isinstance(item, Document))
    assert document.parent_hierarchy_raw_node_id == f"{ID_PREFIX}:root/sub"
    assert document.sections[0].link == (
        "https://onyxtest.blob.core.windows.net/docs/root/sub/x.md"
    )


def test_window_type_size_and_image_rules_match_the_slim_listing() -> None:
    paths = [
        _file("new.txt"),
        _file("old.txt", last_modified=OLD),
        _file("unsupported.xyz"),
        _file("huge.txt", size=10**12),
        _file("picture.png"),
    ]
    connector, _ = _connector(
        {None: AzureDataLakePathPage(paths=paths, continuation_token=None)}
    )

    items, _ = _run(connector, connector.build_dummy_checkpoint())
    slim_ids = {
        doc.id
        for batch in connector.retrieve_all_slim_docs()
        for doc in batch
        if isinstance(doc, SlimDocument)
    }

    assert [item.id for item in items if isinstance(item, Document)] == [
        f"{ID_PREFIX}:new.txt"
    ]
    # The slim listing ignores the window, so it also lists the old file.
    assert slim_ids == {f"{ID_PREFIX}:new.txt", f"{ID_PREFIX}:old.txt"}


def test_a_file_that_fails_to_read_is_a_failure_with_its_document_id() -> None:
    connector, ops = _connector(
        {None: AzureDataLakePathPage(paths=[_file("x.txt")], continuation_token=None)}
    )
    ops.read_file.side_effect = InsufficientPermissionsError("ACL denies it")

    items, _ = _run(connector, connector.build_dummy_checkpoint())

    failure = next(item for item in items if isinstance(item, ConnectorFailure))
    assert failure.failed_document is not None
    assert failure.failed_document.document_id == f"{ID_PREFIX}:x.txt"


def test_a_rejected_credential_fails_the_attempt() -> None:
    connector, ops = _connector(
        {None: AzureDataLakePathPage(paths=[_file("x.txt")], continuation_token=None)}
    )
    ops.read_file.side_effect = CredentialInvalidError("rejected")

    with pytest.raises(CredentialInvalidError):
        _run(connector, connector.build_dummy_checkpoint())


def test_a_stopped_slim_walk_raises() -> None:
    connector, _ = _connector(
        {None: AzureDataLakePathPage(paths=[_file("x.txt")], continuation_token=None)}
    )
    callback = MagicMock()
    callback.should_stop.return_value = True

    with pytest.raises(RuntimeError, match="stop signal"):
        list(connector.retrieve_all_slim_docs(callback=callback))


def test_reindex_reads_the_file_again_with_its_folders() -> None:
    connector, _ = _connector({})
    failure = ConnectorFailure(
        failed_document=DocumentFailure(document_id=f"{ID_PREFIX}:a/b/c.txt"),
        failure_message="earlier failure",
    )

    items = list(connector.reindex([failure]))

    assert [item.raw_node_id for item in items if isinstance(item, HierarchyNode)] == [
        ID_PREFIX,
        f"{ID_PREFIX}:a",
        f"{ID_PREFIX}:a/b",
    ]
    assert [item.id for item in items if isinstance(item, Document)] == [
        f"{ID_PREFIX}:a/b/c.txt"
    ]


def test_reindex_refuses_a_document_of_another_container() -> None:
    connector, ops = _connector({})
    other = ConnectorFailure(
        failed_document=DocumentFailure(
            document_id="azure_datalake:onyxtest:other:x.txt"
        ),
        failure_message="earlier failure",
    )

    items = list(connector.reindex([other]))

    assert len(items) == 1 and isinstance(items[0], ConnectorFailure)
    ops.read_file.assert_not_called()
