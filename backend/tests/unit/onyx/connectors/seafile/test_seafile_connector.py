from collections import Counter
from collections.abc import Callable
from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import patch

import pytest
import requests

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import ImageSection
from onyx.connectors.models import SlimDocument
from onyx.connectors.models import TabularSection
from onyx.connectors.models import TextSection
from onyx.connectors.seafile.connector import _modified_time
from onyx.connectors.seafile.connector import SEAFILE_API_TOKEN_KEY
from onyx.connectors.seafile.connector import SEAFILE_SUPPORTED_EXTENSIONS
from onyx.connectors.seafile.connector import SeafileCheckpoint
from onyx.connectors.seafile.connector import SeafileConnector
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import ExtractionResult


class FakeResponse:
    def __init__(
        self,
        json_data: Any = None,
        content: bytes = b"",
        status_code: int = 200,
        text: str = "",
        json_exc: ValueError | None = None,
    ) -> None:
        self._json_data = json_data
        self._json_exc = json_exc
        self.content = content
        self.status_code = status_code
        self.text = text

    def json(self) -> Any:
        if self._json_exc:
            raise self._json_exc
        return self._json_data


def _connector(max_file_size_bytes: int = 100) -> SeafileConnector:
    connector = SeafileConnector(
        base_url="https://seafile.example.com",
        repo_ids=["repo-1"],
        path_prefixes=["/"],
        max_file_size_bytes=max_file_size_bytes,
        batch_size=2,
    )
    connector.load_credentials({SEAFILE_API_TOKEN_KEY: "token"})
    return connector


def _checkpoint_boundary_connector() -> SeafileConnector:
    connector = SeafileConnector(
        base_url="https://seafile.example.com",
        repo_ids=["repo-1"],
        path_prefixes=["/"],
        max_file_size_bytes=100,
        batch_size=1,
    )
    connector.load_credentials({SEAFILE_API_TOKEN_KEY: "token"})
    return connector


def _custom_connector(path_prefixes: list[str]) -> SeafileConnector:
    connector = SeafileConnector(
        base_url="https://seafile.example.com",
        repo_ids=["repo-1"],
        path_prefixes=path_prefixes,
        max_file_size_bytes=100,
        batch_size=20,
    )
    connector.load_credentials({SEAFILE_API_TOKEN_KEY: "token"})
    return connector


def _api_dispatcher(content_by_path: dict[str, bytes]) -> Callable[..., FakeResponse]:
    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> FakeResponse:
        if url == "https://seafile.example.com/api2/repos/repo-1/":
            return FakeResponse({"name": "Example Library"})

        if url == "https://seafile.example.com/api2/repos/repo-1/dir/":
            path = params["p"] if params else None
            if path == "/":
                return FakeResponse(
                    [
                        {"type": "dir", "name": "docs"},
                        {"type": "file", "name": "large.log", "size": 101},
                        {"type": "file", "name": "archive.zip", "size": 2},
                    ]
                )
            if path == "/docs":
                return FakeResponse(
                    [
                        {
                            "type": "file",
                            "name": "readme.md",
                            "size": 10,
                            "mtime": 1_700_000_000,
                        },
                        {
                            "type": "file",
                            "name": "page.html",
                            "size": 10,
                            "mtime": 1_700_000_010,
                        },
                    ]
                )

        if url == "https://seafile.example.com/api2/repos/repo-1/file/":
            path = params["p"] if params else ""
            return FakeResponse(f"https://download.example.com{path}")

        if url.startswith("https://download.example.com"):
            path = url.removeprefix("https://download.example.com")
            return FakeResponse(content=content_by_path[path])

        raise AssertionError(f"Unexpected request: {method} {url} {params} {headers}")

    return fake_request


def _binary_api_dispatcher(
    content_by_path: dict[str, bytes],
) -> Callable[..., FakeResponse]:
    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> FakeResponse:
        if url == "https://seafile.example.com/api2/repos/repo-1/":
            return FakeResponse({"repo_name": "Binary Library"})

        if url == "https://seafile.example.com/api2/repos/repo-1/dir/":
            path = params["p"] if params else None
            if path == "/":
                return FakeResponse(
                    [
                        {"type": "file", "name": "report.pdf", "size": 10},
                        {"type": "file", "name": "notes.docx", "size": 11},
                        {"type": "file", "name": "deck.pptx", "size": 12},
                        {"type": "file", "name": "metrics.xlsx", "size": 13},
                    ]
                )

        if url == "https://seafile.example.com/api2/repos/repo-1/file/":
            path = params["p"] if params else ""
            return FakeResponse(f"https://download.example.com{path}")

        if url.startswith("https://download.example.com"):
            path = url.removeprefix("https://download.example.com")
            return FakeResponse(content=content_by_path[path])

        raise AssertionError(f"Unexpected request: {method} {url} {params} {headers}")

    return fake_request


def _single_file_api_dispatcher(
    file_item: dict[str, Any],
) -> Callable[..., FakeResponse]:
    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> FakeResponse:
        if url == "https://seafile.example.com/api2/repos/repo-1/":
            return FakeResponse({"name": "Single File Library"})

        if url == "https://seafile.example.com/api2/repos/repo-1/dir/":
            return FakeResponse([{"type": "file", "name": "readme.md", **file_item}])

        if url == "https://seafile.example.com/api2/repos/repo-1/file/":
            path = params["p"] if params else ""
            return FakeResponse(f"https://download.example.com{path}")

        if url == "https://download.example.com/readme.md":
            return FakeResponse(content=b"# Readme\nSeafile indexed text")

        raise AssertionError(f"Unexpected request: {method} {url} {params} {headers}")

    return fake_request


def _empty_folder_api_dispatcher() -> Callable[..., FakeResponse]:
    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> FakeResponse:
        if url == "https://seafile.example.com/api2/repos/repo-1/":
            return FakeResponse({"name": "Example Library"})

        if url == "https://seafile.example.com/api2/repos/repo-1/dir/":
            path = params["p"] if params else None
            if path == "/":
                return FakeResponse([{"type": "dir", "name": "empty"}])
            if path == "/empty":
                return FakeResponse([])

        raise AssertionError(f"Unexpected request: {method} {url} {params} {headers}")

    return fake_request


def _tree_api_dispatcher(
    content_by_path: dict[str, bytes],
) -> Callable[..., FakeResponse]:
    normalized_paths = {
        _normalize_fake_path(path): content for path, content in content_by_path.items()
    }

    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> FakeResponse:
        if url == "https://seafile.example.com/api2/repos/repo-1/":
            return FakeResponse({"name": "Tree Library"})

        if url == "https://seafile.example.com/api2/repos/repo-1/dir/":
            path = _normalize_fake_path(params["p"] if params else "/")
            children: dict[str, dict[str, Any]] = {}
            for file_path, content in normalized_paths.items():
                if file_path == path:
                    continue
                relative_path = file_path.removeprefix(path.rstrip("/") + "/")
                if relative_path == file_path:
                    continue
                child_name = relative_path.split("/", 1)[0]
                if "/" in relative_path:
                    children[child_name] = {"type": "dir", "name": child_name}
                else:
                    children[child_name] = {
                        "type": "file",
                        "name": child_name,
                        "size": len(content),
                        "mtime": 1_700_000_000,
                    }

            return FakeResponse(
                [
                    children[name]
                    for name in sorted(
                        children,
                        key=lambda child_name: (
                            children[child_name]["type"] != "dir",
                            child_name,
                        ),
                    )
                ]
            )

        if url == "https://seafile.example.com/api2/repos/repo-1/file/":
            path = _normalize_fake_path(params["p"] if params else "")
            return FakeResponse(f"https://download.example.com{path}")

        if url.startswith("https://download.example.com"):
            path = _normalize_fake_path(
                url.removeprefix("https://download.example.com")
            )
            return FakeResponse(content=normalized_paths[path])

        raise AssertionError(f"Unexpected request: {method} {url} {params} {headers}")

    return fake_request


def _normalize_fake_path(path: str) -> str:
    return "/" + path.strip().lstrip("/")


def _flatten_batches(connector: SeafileConnector) -> list[Any]:
    return [item for item in _drain_checkpoint(connector) if isinstance(item, Document)]


def _flatten_items(connector: SeafileConnector) -> list[Any]:
    return _drain_checkpoint(connector)


def _drain_checkpoint(
    connector: SeafileConnector,
    checkpoint: SeafileCheckpoint | None = None,
) -> list[Any]:
    next_checkpoint = checkpoint or connector.build_dummy_checkpoint()
    items: list[Any] = []
    while True:
        generator = connector.load_from_checkpoint(
            start=0,
            end=1,
            checkpoint=next_checkpoint,
        )
        try:
            while True:
                items.append(next(generator))
        except StopIteration as stop:
            next_checkpoint = stop.value

        if not next_checkpoint.has_more:
            return items


def _run_checkpoint_once(
    connector: SeafileConnector,
    checkpoint: SeafileCheckpoint,
) -> tuple[list[Any], SeafileCheckpoint]:
    generator = connector.load_from_checkpoint(start=0, end=1, checkpoint=checkpoint)
    items: list[Any] = []
    try:
        while True:
            items.append(next(generator))
    except StopIteration as stop:
        return items, stop.value


def _flatten_slim_items(connector: SeafileConnector) -> list[Any]:
    return [item for batch in connector.retrieve_all_slim_docs() for item in batch]


def _docs_by_path(docs: list[Document]) -> dict[str, Document]:
    docs_by_path: dict[str, Document] = {}
    for doc in docs:
        path = doc.metadata["path"]
        assert isinstance(path, str)
        docs_by_path[path] = doc
    return docs_by_path


def _assert_seafile_hierarchy_contract(items: list[Any]) -> None:
    docs = [item for item in items if isinstance(item, (Document, SlimDocument))]
    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    raw_node_ids = [node.raw_node_id for node in nodes]
    duplicate_raw_node_ids = [
        raw_node_id for raw_node_id, count in Counter(raw_node_ids).items() if count > 1
    ]

    assert duplicate_raw_node_ids == []
    assert raw_node_ids

    for node in nodes:
        assert node.raw_node_id
        assert node.display_name
        assert node.link
        assert node.node_type == HierarchyNodeType.FOLDER
        if node.raw_parent_id is not None:
            assert node.raw_parent_id in raw_node_ids

    for doc in docs:
        assert doc.parent_hierarchy_raw_node_id in raw_node_ids


def test_load_credentials_requires_token() -> None:
    connector = SeafileConnector(
        base_url="https://seafile.example.com",
        repo_ids=["repo-1"],
    )

    with pytest.raises(ConnectorMissingCredentialError):
        connector.load_credentials({})


def test_load_from_checkpoint_indexes_supported_files_and_skips_other_files() -> None:
    connector = _connector()
    content_by_path = {
        "/docs/readme.md": b"# Readme\nSeafile indexed text",
        "/docs/page.html": b"<html><body><h1>Title</h1><p>HTML body</p></body></html>",
    }

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_api_dispatcher(content_by_path),
    ):
        docs = _flatten_batches(connector)

    assert [doc.id for doc in docs] == [
        "seafile:repo-1:/docs/page.html",
        "seafile:repo-1:/docs/readme.md",
    ]
    docs_by_path = _docs_by_path(docs)
    readme_doc = docs_by_path["/docs/readme.md"]
    page_doc = docs_by_path["/docs/page.html"]
    assert readme_doc.sections[0].text == "# Readme\nSeafile indexed text"
    page_text = page_doc.sections[0].text
    assert page_text is not None
    assert "HTML body" in page_text
    assert readme_doc.metadata["repo_id"] == "repo-1"
    assert readme_doc.metadata["library_id"] == "repo-1"
    assert readme_doc.metadata["library_name"] == "Example Library"
    assert readme_doc.metadata["path"] == "/docs/readme.md"
    assert readme_doc.metadata["path_parts"] == ["docs", "readme.md"]
    assert readme_doc.metadata["folder_path"] == "/docs"
    assert readme_doc.metadata["folder_path_parts"] == ["docs"]
    assert readme_doc.metadata["folder_name"] == "docs"
    assert readme_doc.metadata["filename"] == "readme.md"
    assert readme_doc.metadata["extension"] == ".md"
    assert readme_doc.metadata["size"] == "10"
    assert readme_doc.metadata["source_url"] == (
        "https://seafile.example.com/lib/repo-1/file/docs/readme.md"
    )
    assert readme_doc.doc_metadata is not None
    assert readme_doc.doc_metadata["size"] == 10
    assert readme_doc.doc_metadata["source_url"] == readme_doc.metadata["source_url"]
    assert readme_doc.doc_metadata["library_name"] == "Example Library"
    assert readme_doc.doc_metadata["folder_path_parts"] == ["docs"]
    assert readme_doc.doc_updated_at is not None
    assert readme_doc.parent_hierarchy_raw_node_id == "seafile:folder:repo-1:/docs"


def test_load_from_checkpoint_emits_library_and_folder_hierarchy_nodes() -> None:
    connector = _connector()
    content_by_path = {
        "/docs/readme.md": b"# Readme\nSeafile indexed text",
        "/docs/page.html": b"<html><body><h1>Title</h1><p>HTML body</p></body></html>",
    }

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_api_dispatcher(content_by_path),
    ):
        items = _flatten_items(connector)

    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    node_by_raw_id = {node.raw_node_id: node for node in nodes}

    assert set(node_by_raw_id) == {
        "seafile:library:repo-1",
        "seafile:folder:repo-1:/docs",
    }
    assert node_by_raw_id["seafile:library:repo-1"].raw_parent_id is None
    assert node_by_raw_id["seafile:library:repo-1"].display_name == "Example Library"
    assert node_by_raw_id["seafile:library:repo-1"].link == (
        "https://seafile.example.com/lib/repo-1/file/"
    )
    assert (
        node_by_raw_id["seafile:library:repo-1"].node_type == HierarchyNodeType.FOLDER
    )
    assert node_by_raw_id["seafile:folder:repo-1:/docs"].raw_parent_id == (
        "seafile:library:repo-1"
    )
    assert node_by_raw_id["seafile:folder:repo-1:/docs"].display_name == "docs"
    assert node_by_raw_id["seafile:folder:repo-1:/docs"].link == (
        "https://seafile.example.com/lib/repo-1/file/docs"
    )
    assert node_by_raw_id["seafile:folder:repo-1:/docs"].node_type == (
        HierarchyNodeType.FOLDER
    )
    _assert_seafile_hierarchy_contract(items)


def test_load_from_checkpoint_dedupes_hierarchy_nodes_for_overlapping_prefixes() -> (
    None
):
    connector = _custom_connector(path_prefixes=["/", "/docs"])
    content_by_path = {
        "/docs/readme.md": b"# Readme\nSeafile indexed text",
        "/docs/page.html": b"<html><body><h1>Title</h1><p>HTML body</p></body></html>",
    }

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_api_dispatcher(content_by_path),
    ):
        items = _flatten_items(connector)

    docs = [item for item in items if isinstance(item, Document)]
    nodes = [item for item in items if isinstance(item, HierarchyNode)]

    assert [doc.id for doc in docs] == [
        "seafile:repo-1:/docs/page.html",
        "seafile:repo-1:/docs/readme.md",
    ]
    assert [node.raw_node_id for node in nodes] == [
        "seafile:library:repo-1",
        "seafile:folder:repo-1:/docs",
    ]
    _assert_seafile_hierarchy_contract(items)


def test_load_from_checkpoint_emits_empty_traversed_folder_nodes() -> None:
    connector = _connector()

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_empty_folder_api_dispatcher(),
    ):
        items = _flatten_items(connector)

    assert not any(isinstance(item, Document) for item in items)
    assert {item.raw_node_id for item in items if isinstance(item, HierarchyNode)} == {
        "seafile:library:repo-1",
        "seafile:folder:repo-1:/empty",
    }
    _assert_seafile_hierarchy_contract(items)


def test_load_from_checkpoint_initializes_and_finishes_with_has_more_false() -> None:
    connector = _connector()

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_api_dispatcher(
            {
                "/docs/readme.md": b"# Readme\nSeafile indexed text",
                "/docs/page.html": b"<html><body><p>HTML body</p></body></html>",
            }
        ),
    ):
        items = _drain_checkpoint(connector)

    assert [item.id for item in items if isinstance(item, Document)] == [
        "seafile:repo-1:/docs/page.html",
        "seafile:repo-1:/docs/readme.md",
    ]

    checkpoint = connector.build_dummy_checkpoint()
    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_api_dispatcher(
            {
                "/docs/readme.md": b"# Readme\nSeafile indexed text",
                "/docs/page.html": b"<html><body><p>HTML body</p></body></html>",
            }
        ),
    ):
        while checkpoint.has_more:
            _items, checkpoint = _run_checkpoint_once(connector, checkpoint)

    assert checkpoint.initialized
    assert checkpoint.current_dir is None
    assert checkpoint.pending_dirs == []
    assert checkpoint.has_more is False


def test_load_from_checkpoint_resumes_partially_processed_directory() -> None:
    connector = _checkpoint_boundary_connector()
    checkpoint = connector.build_dummy_checkpoint()

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_api_dispatcher(
            {
                "/docs/readme.md": b"# Readme\nSeafile indexed text",
                "/docs/page.html": b"<html><body><p>HTML body</p></body></html>",
            }
        ),
    ):
        first_items, checkpoint = _run_checkpoint_once(connector, checkpoint)
        second_items, checkpoint = _run_checkpoint_once(connector, checkpoint)

    assert [item.id for item in first_items if isinstance(item, Document)] == [
        "seafile:repo-1:/docs/page.html"
    ]
    assert checkpoint.has_more is True
    assert checkpoint.current_dir is not None
    assert checkpoint.current_dir.path == "/docs"
    assert checkpoint.current_dir.last_child_path == "/docs/readme.md"
    assert [item.id for item in second_items if isinstance(item, Document)] == [
        "seafile:repo-1:/docs/readme.md"
    ]


def test_load_from_checkpoint_emits_hierarchy_nodes_once_across_boundaries() -> None:
    connector = _checkpoint_boundary_connector()
    checkpoint = connector.build_dummy_checkpoint()

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_api_dispatcher(
            {
                "/docs/readme.md": b"# Readme\nSeafile indexed text",
                "/docs/page.html": b"<html><body><p>HTML body</p></body></html>",
            }
        ),
    ):
        first_items, checkpoint = _run_checkpoint_once(connector, checkpoint)
        second_items, checkpoint = _run_checkpoint_once(connector, checkpoint)

    assert [item.raw_node_id for item in first_items if isinstance(item, HierarchyNode)]
    assert [item for item in second_items if isinstance(item, HierarchyNode)] == []


def test_moved_file_disappears_at_old_path_and_reappears_with_new_id() -> None:
    connector = _custom_connector(path_prefixes=["/docs"])

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_tree_api_dispatcher(
            {
                "/docs/readme.md": b"old location",
            }
        ),
    ):
        old_items = _flatten_items(connector)

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_tree_api_dispatcher(
            {
                "/docs/moved/readme.md": b"new location",
            }
        ),
    ):
        new_items = _flatten_items(connector)

    old_docs = [item for item in old_items if isinstance(item, Document)]
    new_docs = [item for item in new_items if isinstance(item, Document)]

    assert [doc.id for doc in old_docs] == ["seafile:repo-1:/docs/readme.md"]
    assert [doc.id for doc in new_docs] == ["seafile:repo-1:/docs/moved/readme.md"]
    assert new_docs[0].metadata["path"] == "/docs/moved/readme.md"
    assert new_docs[0].metadata["folder_path"] == "/docs/moved"
    assert new_docs[0].metadata["source_url"] == (
        "https://seafile.example.com/lib/repo-1/file/docs/moved/readme.md"
    )
    assert new_docs[0].parent_hierarchy_raw_node_id == (
        "seafile:folder:repo-1:/docs/moved"
    )
    _assert_seafile_hierarchy_contract(new_items)


def test_deleted_file_is_absent_from_slim_retrieval() -> None:
    connector = _custom_connector(path_prefixes=["/docs"])

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_tree_api_dispatcher(
            {
                "/docs/keep.md": b"kept",
                "/docs/delete-me.md": b"deleted",
            }
        ),
    ):
        before_items = _flatten_slim_items(connector)

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_tree_api_dispatcher(
            {
                "/docs/keep.md": b"kept",
            }
        ),
    ):
        after_items = _flatten_slim_items(connector)

    before_doc_ids = [
        item.id for item in before_items if isinstance(item, SlimDocument)
    ]
    after_doc_ids = [item.id for item in after_items if isinstance(item, SlimDocument)]

    assert before_doc_ids == [
        "seafile:repo-1:/docs/delete-me.md",
        "seafile:repo-1:/docs/keep.md",
    ]
    assert after_doc_ids == ["seafile:repo-1:/docs/keep.md"]
    _assert_seafile_hierarchy_contract(after_items)


def test_load_from_checkpoint_summarizes_skipped_files() -> None:
    connector = _connector()
    content_by_path = {
        "/docs/readme.md": b"# Readme\nSeafile indexed text",
        "/docs/page.html": b"<html><body><h1>Title</h1><p>HTML body</p></body></html>",
    }

    with (
        patch(
            "onyx.connectors.seafile.connector.request_with_retries",
            side_effect=_api_dispatcher(content_by_path),
        ),
        patch("onyx.connectors.seafile.connector.logger.info") as mock_info,
        patch("onyx.connectors.seafile.connector.logger.debug") as mock_debug,
    ):
        _flatten_batches(connector)

    assert mock_info.call_count == 1
    assert mock_info.call_args.args[0] == "Skipped Seafile files: %s"
    assert "oversized_listing=1" in mock_info.call_args.args[1]
    assert "unsupported_extension=1" in mock_info.call_args.args[1]
    assert mock_debug.call_count >= 3


def test_binary_files_use_onyx_file_parsers() -> None:
    connector = _connector()
    content_by_path = {
        "/report.pdf": b"pdf",
        "/notes.docx": b"docx",
        "/deck.pptx": b"pptx",
        "/metrics.xlsx": b"xlsx",
    }
    parser_calls: list[str] = []

    def fake_extract_text_and_images(
        *,
        file: Any,
        file_name: str,
        image_callback: Any,
    ) -> ExtractionResult:
        _ = file, image_callback
        parser_calls.append(file_name)
        return ExtractionResult(
            text_content=f"parsed {file_name}",
            embedded_images=[],
            metadata={},
        )

    def fake_tabular_file_to_sections(
        *, file: Any, file_name: str, link: str
    ) -> list[TabularSection]:
        _ = file
        parser_calls.append(file_name)
        return [TabularSection(csv_file_id=f"{file_name}.csv", link=link)]

    with (
        patch(
            "onyx.connectors.seafile.connector.request_with_retries",
            side_effect=_binary_api_dispatcher(content_by_path),
        ),
        patch(
            "onyx.connectors.seafile.connector.extract_text_and_images",
            side_effect=fake_extract_text_and_images,
        ),
        patch(
            "onyx.connectors.seafile.connector.tabular_file_to_sections",
            side_effect=fake_tabular_file_to_sections,
        ),
    ):
        docs = _flatten_batches(connector)

    assert [doc.id for doc in docs] == [
        "seafile:repo-1:/deck.pptx",
        "seafile:repo-1:/metrics.xlsx",
        "seafile:repo-1:/notes.docx",
        "seafile:repo-1:/report.pdf",
    ]
    assert parser_calls == ["deck.pptx", "metrics.xlsx", "notes.docx", "report.pdf"]
    docs_by_path = _docs_by_path(docs)
    assert docs_by_path["/deck.pptx"].sections[0].text == "parsed deck.pptx"
    assert docs_by_path["/notes.docx"].sections[0].text == "parsed notes.docx"
    assert docs_by_path["/report.pdf"].sections[0].text == "parsed report.pdf"
    assert isinstance(docs_by_path["/metrics.xlsx"].sections[0], TabularSection)
    assert docs_by_path["/metrics.xlsx"].sections[0].csv_file_id == "metrics.xlsx.csv"
    assert docs_by_path["/report.pdf"].metadata["extension"] == ".pdf"
    assert docs_by_path["/report.pdf"].doc_metadata is not None
    assert docs_by_path["/report.pdf"].doc_metadata["size"] == 10
    assert docs_by_path["/report.pdf"].parent_hierarchy_raw_node_id == (
        "seafile:library:repo-1"
    )


def test_extended_parser_extensions_are_supported() -> None:
    assert {
        ".eml",
        ".epub",
        ".xlsm",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
    }.issubset(SEAFILE_SUPPORTED_EXTENSIONS)


def test_tabular_files_emit_tabular_sections() -> None:
    connector = _connector()
    content_by_path = {
        "/table.csv": b"name,value\nalpha,1\n",
        "/macro.xlsm": b"xlsm",
    }

    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> FakeResponse:
        if url == "https://seafile.example.com/api2/repos/repo-1/":
            return FakeResponse({"name": "Tabular Library"})
        if url == "https://seafile.example.com/api2/repos/repo-1/dir/":
            return FakeResponse(
                [
                    {"type": "file", "name": "table.csv", "size": 10},
                    {"type": "file", "name": "macro.xlsm", "size": 10},
                ]
            )
        if url == "https://seafile.example.com/api2/repos/repo-1/file/":
            path = params["p"] if params else ""
            return FakeResponse(f"https://download.example.com{path}")
        if url.startswith("https://download.example.com"):
            path = url.removeprefix("https://download.example.com")
            return FakeResponse(content=content_by_path[path])
        raise AssertionError(f"Unexpected request: {method} {url} {params} {headers}")

    with (
        patch(
            "onyx.connectors.seafile.connector.request_with_retries",
            side_effect=fake_request,
        ),
        patch(
            "onyx.connectors.seafile.connector.tabular_file_to_sections",
            side_effect=[
                [TabularSection(csv_file_id="table.csv", link="csv-link")],
                [TabularSection(csv_file_id="macro.xlsm.csv", link="xlsm-link")],
            ],
        ) as mock_tabular,
    ):
        docs = _flatten_batches(connector)

    assert [doc.id for doc in docs] == [
        "seafile:repo-1:/macro.xlsm",
        "seafile:repo-1:/table.csv",
    ]
    assert all(isinstance(doc.sections[0], TabularSection) for doc in docs)
    assert [call.kwargs["file_name"] for call in mock_tabular.call_args_list] == [
        "macro.xlsm",
        "table.csv",
    ]


def test_standalone_image_emits_image_section() -> None:
    connector = _connector()
    content_by_path = {
        "/diagram.png": b"\x89PNG\r\n\x1a\nimage bytes",
    }

    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> FakeResponse:
        if url == "https://seafile.example.com/api2/repos/repo-1/":
            return FakeResponse({"name": "Image Library"})
        if url == "https://seafile.example.com/api2/repos/repo-1/dir/":
            return FakeResponse([{"type": "file", "name": "diagram.png", "size": 10}])
        if url == "https://seafile.example.com/api2/repos/repo-1/file/":
            path = params["p"] if params else ""
            return FakeResponse(f"https://download.example.com{path}")
        if url.startswith("https://download.example.com"):
            path = url.removeprefix("https://download.example.com")
            return FakeResponse(content=content_by_path[path])
        raise AssertionError(f"Unexpected request: {method} {url} {params} {headers}")

    with (
        patch(
            "onyx.connectors.seafile.connector.request_with_retries",
            side_effect=fake_request,
        ),
        patch(
            "onyx.connectors.seafile.connector.store_image_and_create_section",
            return_value=(ImageSection(image_file_id="stored-image", link=None), None),
        ) as mock_store_image,
    ):
        docs = _flatten_batches(connector)

    assert len(docs) == 1
    assert isinstance(docs[0].sections[0], ImageSection)
    assert docs[0].sections[0].image_file_id == "stored-image"
    assert docs[0].sections[0].link is None
    assert mock_store_image.call_args.kwargs["display_name"] == "diagram.png"


def test_document_parser_can_emit_text_and_embedded_images() -> None:
    connector = _connector()
    content_by_path = {
        "/message.eml": b"Subject: Test\n\nbody",
    }

    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> FakeResponse:
        if url == "https://seafile.example.com/api2/repos/repo-1/":
            return FakeResponse({"name": "Document Library"})
        if url == "https://seafile.example.com/api2/repos/repo-1/dir/":
            return FakeResponse([{"type": "file", "name": "message.eml", "size": 10}])
        if url == "https://seafile.example.com/api2/repos/repo-1/file/":
            path = params["p"] if params else ""
            return FakeResponse(f"https://download.example.com{path}")
        if url.startswith("https://download.example.com"):
            path = url.removeprefix("https://download.example.com")
            return FakeResponse(content=content_by_path[path])
        raise AssertionError(f"Unexpected request: {method} {url} {params} {headers}")

    def fake_extract_text_and_images(
        *,
        file: Any,
        file_name: str,
        image_callback: Any,
    ) -> ExtractionResult:
        _ = file, file_name
        image_callback(b"image", "embedded.png")
        return ExtractionResult(
            text_content="parsed email",
            embedded_images=[],
            metadata={},
        )

    with (
        patch(
            "onyx.connectors.seafile.connector.request_with_retries",
            side_effect=fake_request,
        ),
        patch(
            "onyx.connectors.seafile.connector.extract_text_and_images",
            side_effect=fake_extract_text_and_images,
        ),
        patch(
            "onyx.file_processing.image_utils.get_image_type_from_bytes",
            return_value="image/png",
        ),
        patch(
            "onyx.file_processing.image_utils.store_image_and_create_section",
            return_value=(
                ImageSection(image_file_id="embedded-image", link=None),
                None,
            ),
        ),
    ):
        docs = _flatten_batches(connector)

    assert len(docs) == 1
    assert isinstance(docs[0].sections[0], ImageSection)
    assert docs[0].sections[0].image_file_id == "embedded-image"
    assert isinstance(docs[0].sections[1], TextSection)
    assert docs[0].sections[1].text == "parsed email"


def test_source_url_encodes_repo_and_path() -> None:
    connector = SeafileConnector(
        base_url="https://seafile.example.com/",
        repo_ids=["repo 1"],
    )

    assert connector._source_url("repo 1", "/docs/a file+#.txt") == (
        "https://seafile.example.com/lib/repo%201/file/docs/a%20file%2B%23.txt"
    )


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        (
            {"mtime": 0},
            datetime(1970, 1, 1, tzinfo=timezone.utc),
        ),
        (
            {"mtime": 1_700_000_000},
            datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc),
        ),
        (
            {"mtime": "1700000000"},
            datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc),
        ),
        (
            {"modified": "2023-11-14T22:13:20Z"},
            datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc),
        ),
        (
            {"last_modified": "Tue, 14 Nov 2023 22:13:20 GMT"},
            datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc),
        ),
        (
            {"lastModifiedDateTime": "2023-11-14T17:13:20-05:00"},
            datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc),
        ),
        (
            {"updatedAt": "2023-11-14 22:13:20"},
            datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc),
        ),
    ],
)
def test_modified_time_parses_known_seafile_variants(
    item: dict[str, Any], expected: datetime
) -> None:
    assert _modified_time(item) == expected


def test_modified_time_uses_first_present_field() -> None:
    assert _modified_time(
        {
            "mtime": 1_700_000_000,
            "modified": "2023-11-15T22:13:20Z",
        }
    ) == datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)


def test_unparseable_modified_time_is_preserved_as_raw_metadata() -> None:
    connector = _connector()

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_single_file_api_dispatcher(
            {"size": 10, "last_modified": "not a timestamp"}
        ),
    ):
        docs = _flatten_batches(connector)

    assert len(docs) == 1
    assert docs[0].doc_updated_at is None
    assert "modified_time" not in docs[0].metadata
    assert docs[0].metadata["raw_modified_time"] == "not a timestamp"
    assert docs[0].doc_metadata is not None
    assert docs[0].doc_metadata["raw_modified_time"] == "not a timestamp"


def test_binary_parser_failure_skips_file_and_continues() -> None:
    connector = _connector()
    content_by_path = {
        "/report.pdf": b"pdf",
        "/notes.docx": b"docx",
        "/deck.pptx": b"pptx",
        "/metrics.xlsx": b"xlsx",
    }

    def fake_extract_text_and_images(
        *,
        file: Any,
        file_name: str,
        image_callback: Any,
    ) -> ExtractionResult:
        _ = file, image_callback
        if file_name == "report.pdf":
            raise RuntimeError("bad pdf")
        return ExtractionResult(
            text_content=f"parsed {file_name}",
            embedded_images=[],
            metadata={},
        )

    def fake_tabular_file_to_sections(
        *, file: Any, file_name: str, link: str
    ) -> list[TabularSection]:
        _ = file
        return [TabularSection(csv_file_id=f"{file_name}.csv", link=link)]

    with (
        patch(
            "onyx.connectors.seafile.connector.request_with_retries",
            side_effect=_binary_api_dispatcher(content_by_path),
        ),
        patch(
            "onyx.connectors.seafile.connector.extract_text_and_images",
            side_effect=fake_extract_text_and_images,
        ),
        patch(
            "onyx.connectors.seafile.connector.tabular_file_to_sections",
            side_effect=fake_tabular_file_to_sections,
        ),
    ):
        docs = _flatten_batches(connector)

    assert [doc.id for doc in docs] == [
        "seafile:repo-1:/deck.pptx",
        "seafile:repo-1:/metrics.xlsx",
        "seafile:repo-1:/notes.docx",
    ]


def test_repeated_sync_is_idempotent() -> None:
    connector = _connector()
    content_by_path = {
        "/docs/readme.md": b"same content",
        "/docs/page.html": b"<p>same html</p>",
    }

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_api_dispatcher(content_by_path),
    ):
        first_docs = _flatten_batches(connector)

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_api_dispatcher(content_by_path),
    ):
        second_docs = _flatten_batches(connector)

    assert [doc.id for doc in first_docs] == [doc.id for doc in second_docs]


def test_changed_file_updates_content_with_stable_id() -> None:
    connector = _connector()

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_api_dispatcher(
            {
                "/docs/readme.md": b"old content",
                "/docs/page.html": b"<p>same html</p>",
            }
        ),
    ):
        old_doc = _docs_by_path(_flatten_batches(connector))["/docs/readme.md"]

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=_api_dispatcher(
            {
                "/docs/readme.md": b"new content",
                "/docs/page.html": b"<p>same html</p>",
            }
        ),
    ):
        new_doc = _docs_by_path(_flatten_batches(connector))["/docs/readme.md"]

    assert old_doc.id == new_doc.id
    assert old_doc.sections[0].text == "old content"
    assert new_doc.sections[0].text == "new content"


def test_slim_retrieval_lists_ids_without_downloading_files() -> None:
    connector = _connector()
    calls: list[str] = []

    def fake_request(*args: Any, **kwargs: Any) -> FakeResponse:
        url = args[1] if len(args) > 1 else kwargs["url"]
        calls.append(url)
        return _api_dispatcher({})(*args, **kwargs)

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=fake_request,
    ):
        slim_items = [
            item for batch in connector.retrieve_all_slim_docs() for item in batch
        ]
    slim_docs = [item for item in slim_items if isinstance(item, SlimDocument)]
    hierarchy_nodes = [item for item in slim_items if isinstance(item, HierarchyNode)]
    slim_doc_ids: list[str] = []
    for doc in slim_docs:
        slim_doc_ids.append(doc.id)
        assert doc.parent_hierarchy_raw_node_id == "seafile:folder:repo-1:/docs"

    assert slim_doc_ids == [
        "seafile:repo-1:/docs/readme.md",
        "seafile:repo-1:/docs/page.html",
    ]
    assert {node.raw_node_id for node in hierarchy_nodes} == {
        "seafile:library:repo-1",
        "seafile:folder:repo-1:/docs",
    }
    _assert_seafile_hierarchy_contract(slim_items)
    assert all("/file/" not in call for call in calls)
    assert all("download.example.com" not in call for call in calls)


def test_auth_failure_is_reported_cleanly() -> None:
    connector = _connector()
    response = requests.Response()
    response.status_code = 401
    response._content = b"unauthorized"
    exc = requests.HTTPError("401 Client Error")
    exc.response = response

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=exc,
    ):
        with pytest.raises(CredentialExpiredError):
            _drain_checkpoint(connector)


def test_missing_seafile_permissions_are_reported_cleanly() -> None:
    connector = _connector()
    response = requests.Response()
    response.status_code = 403
    response._content = b"forbidden"
    exc = requests.HTTPError("403 Client Error")
    exc.response = response

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=exc,
    ):
        with pytest.raises(
            InsufficientPermissionsError,
            match="dedicated Seafile service account with read access",
        ):
            _drain_checkpoint(connector)


def test_missing_repo_or_path_is_reported_cleanly() -> None:
    connector = _connector()
    response = requests.Response()
    response.status_code = 404
    response._content = b"not found"
    exc = requests.HTTPError("404 Client Error")
    exc.response = response

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=exc,
    ):
        with pytest.raises(ConnectorValidationError, match="not found"):
            _drain_checkpoint(connector)


def test_rate_limit_is_reported_cleanly() -> None:
    connector = _connector()
    response = requests.Response()
    response.status_code = 429
    response._content = b"too many requests"
    exc = requests.HTTPError("429 Client Error")
    exc.response = response

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=exc,
    ):
        with pytest.raises(ConnectorValidationError, match="rate limit"):
            _drain_checkpoint(connector)


def test_server_error_is_reported_with_context() -> None:
    connector = _connector()
    response = requests.Response()
    response.status_code = 503
    response._content = b"maintenance"
    exc = requests.HTTPError("503 Server Error")
    exc.response = response

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=exc,
    ):
        with pytest.raises(ConnectorValidationError, match="repo=repo-1 path=/"):
            _drain_checkpoint(connector)


def test_timeout_is_reported_cleanly() -> None:
    connector = _connector()

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=requests.Timeout("timed out"),
    ):
        with pytest.raises(ConnectorValidationError, match="timed out"):
            _drain_checkpoint(connector)


def test_malformed_json_is_reported_with_context() -> None:
    connector = _connector()

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        return_value=FakeResponse(json_exc=ValueError("bad json")),
    ):
        with pytest.raises(ConnectorValidationError, match="malformed JSON"):
            _drain_checkpoint(connector)


def test_unexpected_directory_response_is_reported_with_context() -> None:
    connector = _connector()

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        return_value=FakeResponse("uptodate"),
    ):
        with pytest.raises(ConnectorValidationError, match="repo=repo-1 path=/"):
            _drain_checkpoint(connector)


def test_unexpected_download_response_is_reported_with_context() -> None:
    connector = _connector()

    def fake_request(
        method: str,
        url: str,
        *,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> FakeResponse:
        if url == "https://seafile.example.com/api2/repos/repo-1/":
            return FakeResponse({"name": "Example Library"})
        if url == "https://seafile.example.com/api2/repos/repo-1/dir/":
            return FakeResponse([{"type": "file", "name": "readme.md", "size": 10}])
        if url == "https://seafile.example.com/api2/repos/repo-1/file/":
            return FakeResponse({"unexpected": "shape"})
        raise AssertionError(f"Unexpected request: {method} {url} {params} {headers}")

    with patch(
        "onyx.connectors.seafile.connector.request_with_retries",
        side_effect=fake_request,
    ):
        with pytest.raises(
            ConnectorValidationError, match="repo=repo-1 path=/readme.md"
        ):
            _drain_checkpoint(connector)


def test_unsupported_extension_allowlist_is_rejected() -> None:
    with pytest.raises(
        ConnectorValidationError, match="Unsupported Seafile extensions"
    ):
        SeafileConnector(
            base_url="https://seafile.example.com",
            repo_ids=["repo-1"],
            allowed_extensions=[".zip"],
        )
