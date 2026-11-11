"""The Egnyte connector's folder walk: one folder node per folder, documents
keyed by group_id under their folder, pages that overlap without repeats,
resume from a serialized checkpoint, per-item failures, and a slim listing
that matches indexing and raises instead of stopping short."""

from collections.abc import Callable
from io import BytesIO
from unittest.mock import MagicMock

import pytest

from onyx.connectors.connector_runner import CheckpointOutputWrapper
from onyx.connectors.egnyte import connector as connector_module
from onyx.connectors.egnyte.connector import EgnyteCheckpoint, EgnyteConnector
from onyx.connectors.egnyte.models import EgnyteFile, EgnyteFolder, EgnyteFolderPage
from onyx.connectors.egnyte.source_operations import (
    EgnyteApiError,
    EgnyteQuotaExhaustedError,
)
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    SlimDocument,
)

_LAST_MODIFIED = "Tue, 10 Nov 2026 18:00:00 GMT"
_LAST_MODIFIED_EPOCH = 1794333600


def _folder(path: str, parent_id: str | None = None) -> EgnyteFolder:
    return EgnyteFolder(
        name=path.rsplit("/", 1)[-1],
        path=path,
        folder_id=f"id:{path}",
        parent_id=parent_id,
    )


def _file(path: str) -> EgnyteFile:
    return EgnyteFile(
        name=path.rsplit("/", 1)[-1],
        path=path,
        group_id=f"group:{path}",
        entry_id=f"entry:{path}",
        last_modified=_LAST_MODIFIED,
    )


class _FakeEgnyte:
    """An in-memory Egnyte tree served one sorted page at a time."""

    def __init__(self, tree: dict[str, list[str]]) -> None:
        # Folder path to child paths; a child is a folder when it is a key.
        self.tree = tree
        self.downloads: list[str] = []
        self.on_list: Callable[[str, int], None] | None = None

    def list_folder_page(
        self, *, folder_path: str, offset: int, page_size: int
    ) -> EgnyteFolderPage:
        if self.on_list is not None:
            self.on_list(folder_path, offset)
        if folder_path not in self.tree:
            raise EgnyteApiError("missing", status_code=404)
        parent = folder_path.rsplit("/", 1)[0] or "/"
        children = sorted(self.tree[folder_path])[offset : offset + page_size]
        return EgnyteFolderPage(
            folder=_folder(folder_path, parent_id=f"id:{parent}"),
            folders=[
                _folder(child, f"id:{folder_path}")
                for child in children
                if child in self.tree
            ],
            files=[_file(child) for child in children if child not in self.tree],
        )

    def download_file(self, *, file_path: str) -> BytesIO:
        self.downloads.append(file_path)
        return BytesIO(f"text of {file_path}".encode())


def _connector(fake: object, folder_path: str = "/Shared") -> EgnyteConnector:
    connector = EgnyteConnector(folder_path=folder_path)
    connector.load_credentials({"domain": "acme", "access_token": "test-token"})
    connector._ops = fake  # ty: ignore[invalid-assignment]
    return connector


def _run(
    connector: EgnyteConnector, start: float = 0
) -> list[Document | HierarchyNode | ConnectorFailure]:
    """Every item of a full run, through a JSON round trip of each checkpoint."""
    items: list[Document | HierarchyNode | ConnectorFailure] = []
    checkpoint = connector.build_dummy_checkpoint()
    for _ in range(1000):
        if not checkpoint.has_more:
            return items
        wrapper = CheckpointOutputWrapper[EgnyteCheckpoint]()
        for document, node, failure, next_checkpoint in wrapper(
            connector.load_from_checkpoint(start, 2_000_000_000, checkpoint)
        ):
            items.extend(item for item in (document, node, failure) if item)
            if next_checkpoint is not None:
                checkpoint = connector.validate_checkpoint_json(
                    next_checkpoint.model_dump_json()
                )
    raise RuntimeError("The walk did not end")


@pytest.fixture
def small_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(connector_module, "FOLDER_PAGE_SIZE", 10)
    monkeypatch.setattr(connector_module, "_PAGE_OVERLAP", 1)


def test_walk_yields_folder_nodes_and_documents_under_them() -> None:
    fake = _FakeEgnyte(
        {
            "/Shared": ["/Shared/Sub", "/Shared/a.txt", "/Shared/photo.png"],
            "/Shared/Sub": ["/Shared/Sub/b.md"],
        }
    )

    items = _run(_connector(fake, folder_path="Shared/"))

    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    assert [(n.raw_node_id, n.raw_parent_id) for n in nodes] == [
        ("id:/Shared", None),
        ("id:/Shared/Sub", "id:/Shared"),
    ]
    docs = [item for item in items if isinstance(item, Document)]
    assert [
        (d.id, d.parent_hierarchy_raw_node_id, d.sections[0].text) for d in docs
    ] == [
        ("egnyte-group:/Shared/a.txt", "id:/Shared", "text of /Shared/a.txt"),
        ("egnyte-group:/Shared/Sub/b.md", "id:/Shared/Sub", "text of /Shared/Sub/b.md"),
    ]
    # Unsupported types are never downloaded.
    assert "/Shared/photo.png" not in fake.downloads


@pytest.mark.usefixtures("small_pages")
def test_pages_overlap_so_a_deletion_between_pages_skips_nothing() -> None:
    names = [f"/Shared/f{n:02d}.txt" for n in range(25)]
    fake = _FakeEgnyte({"/Shared": list(names)})

    def delete_after_first_page(folder_path: str, offset: int) -> None:
        if offset > 0 and "/Shared/f03.txt" in fake.tree[folder_path]:
            fake.tree[folder_path].remove("/Shared/f03.txt")

    fake.on_list = delete_after_first_page

    items = _run(_connector(fake))

    assert [item.id for item in items if isinstance(item, Document)] == [
        f"egnyte-group:{name}" for name in names
    ]


def test_failures_are_per_item_and_the_walk_goes_on() -> None:
    fake = _FakeEgnyte(
        {
            "/Shared": [
                "/Shared/Locked",
                "/Shared/Next",
                "/Shared/bad.txt",
                "/Shared/deleted.txt",
            ],
            "/Shared/Locked": [],
            "/Shared/Next": ["/Shared/Next/ok.txt"],
        }
    )

    def fail_locked(folder_path: str, offset: int) -> None:  # noqa: ARG001
        if folder_path == "/Shared/Locked":
            raise EgnyteApiError("boom", status_code=500)

    def download_file(*, file_path: str) -> BytesIO:
        if file_path == "/Shared/bad.txt":
            raise EgnyteApiError("boom", status_code=500)
        if file_path == "/Shared/deleted.txt":
            raise EgnyteApiError("gone", status_code=404)
        return BytesIO(b"ok")

    fake.on_list = fail_locked
    ops = MagicMock(list_folder_page=fake.list_folder_page, download_file=download_file)

    items = _run(_connector(ops))

    failures = [item for item in items if isinstance(item, ConnectorFailure)]
    assert [
        (
            f.failed_document.document_id if f.failed_document else None,
            f.failed_entity.entity_id if f.failed_entity else None,
        )
        for f in failures
    ] == [("egnyte-group:/Shared/bad.txt", None), (None, "/Shared/Locked")]
    assert [item.id for item in items if isinstance(item, Document)] == [
        "egnyte-group:/Shared/Next/ok.txt"
    ]


def test_used_up_quota_ends_the_run() -> None:
    fake = _FakeEgnyte({"/Shared": ["/Shared/a.txt"]})
    ops = MagicMock(
        list_folder_page=fake.list_folder_page,
        download_file=MagicMock(side_effect=EgnyteQuotaExhaustedError("quota")),
    )

    with pytest.raises(EgnyteQuotaExhaustedError):
        _run(_connector(ops))


def test_poll_window_skips_files_modified_before_it() -> None:
    fake = _FakeEgnyte({"/Shared": ["/Shared/a.txt"]})

    items = _run(_connector(fake), start=_LAST_MODIFIED_EPOCH + 1)

    assert not [item for item in items if isinstance(item, Document)]
    assert fake.downloads == []


@pytest.mark.usefixtures("small_pages")
def test_slim_listing_matches_indexing_without_downloads() -> None:
    tree = {
        "/Shared": ["/Shared/Sub", "/Shared/photo.png"]
        + [f"/Shared/f{n:02d}.txt" for n in range(12)],
        "/Shared/Sub": ["/Shared/Sub/b.md"],
    }
    fake = _FakeEgnyte(tree)
    connector = _connector(fake)

    slim = [
        item
        for batch in connector.retrieve_all_slim_docs()
        for item in batch
        if isinstance(item, SlimDocument)
    ]

    indexed = [item.id for item in _run(connector) if isinstance(item, Document)]
    assert sorted(doc.id for doc in slim) == sorted(indexed)
    assert len(slim) == 13


def test_slim_listing_raises_on_a_listing_error_and_on_stop() -> None:
    fake = _FakeEgnyte({"/Shared": ["/Shared/Sub"], "/Shared/Sub": []})

    def fail_sub(folder_path: str, offset: int) -> None:  # noqa: ARG001
        if folder_path == "/Shared/Sub":
            raise EgnyteApiError("boom", status_code=500)

    fake.on_list = fail_sub
    with pytest.raises(EgnyteApiError):
        list(_connector(fake).retrieve_all_slim_docs())

    callback = MagicMock()
    callback.should_stop.return_value = True
    fake = _FakeEgnyte({"/Shared": []})
    with pytest.raises(RuntimeError, match="stop signal"):
        list(_connector(fake).retrieve_all_slim_docs(callback=callback))
