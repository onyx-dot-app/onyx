import time
from collections import Counter
from collections.abc import Sequence
from typing import Any

import pytest
import requests

import onyx.file_processing.extract_file_text as extract_file_text_module
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
from onyx.connectors.seafile.connector import SEAFILE_API_TOKEN_KEY
from onyx.connectors.seafile.connector import SeafileCheckpoint
from onyx.connectors.seafile.connector import SeafileConnector
from onyx.db.enums import HierarchyNodeType
from tests.external_dependency_unit.connectors.seafile.conftest import delete_directory
from tests.external_dependency_unit.connectors.seafile.conftest import delete_file
from tests.external_dependency_unit.connectors.seafile.conftest import move_file
from tests.external_dependency_unit.connectors.seafile.conftest import overwrite_file
from tests.external_dependency_unit.connectors.seafile.conftest import (
    SEAFILE_ADMIN_EMAIL,
)
from tests.external_dependency_unit.connectors.seafile.conftest import (
    SEAFILE_ADMIN_PASSWORD,
)
from tests.external_dependency_unit.connectors.seafile.conftest import (
    SeafileTestLibrary,
)


def _connector(seafile_test_library: SeafileTestLibrary) -> SeafileConnector:
    connector = SeafileConnector(
        base_url=seafile_test_library.base_url,
        repo_ids=[seafile_test_library.repo_id],
        path_prefixes=["/docs"],
        allowed_extensions=[".txt", ".md"],
        max_file_size_bytes=200,
        batch_size=1,
    )
    connector.load_credentials({SEAFILE_API_TOKEN_KEY: seafile_test_library.api_token})
    return connector


def _custom_connector(
    seafile_test_library: SeafileTestLibrary,
    *,
    repo_ids: list[str] | None = None,
    path_prefixes: list[str] | None = None,
    allowed_extensions: list[str] | None = None,
    max_file_size_bytes: int = 20 * 1024 * 1024,
    api_token: str | None = None,
    batch_size: int = 10,
) -> SeafileConnector:
    connector = SeafileConnector(
        base_url=seafile_test_library.base_url,
        repo_ids=repo_ids or [seafile_test_library.repo_id],
        path_prefixes=path_prefixes or ["/docs"],
        allowed_extensions=allowed_extensions,
        max_file_size_bytes=max_file_size_bytes,
        batch_size=batch_size,
    )
    connector.load_credentials(
        {SEAFILE_API_TOKEN_KEY: api_token or seafile_test_library.api_token}
    )
    return connector


def _flatten_batches(connector: SeafileConnector) -> list[Document]:
    return [item for item in _drain_checkpoint(connector) if isinstance(item, Document)]


def _flatten_slim_batches(connector: SeafileConnector) -> list[SlimDocument]:
    slim_docs: list[SlimDocument] = []
    for batch in connector.retrieve_all_slim_docs():
        for item in batch:
            if isinstance(item, SlimDocument):
                slim_docs.append(item)
    return slim_docs


def _flatten_items(connector: SeafileConnector) -> list[Document | HierarchyNode]:
    return _drain_checkpoint(connector)


def _drain_checkpoint(
    connector: SeafileConnector,
    checkpoint: SeafileCheckpoint | None = None,
) -> list[Document | HierarchyNode]:
    next_checkpoint = checkpoint or connector.build_dummy_checkpoint()
    items: list[Document | HierarchyNode] = []
    while True:
        generator = connector.load_from_checkpoint(
            start=0,
            end=1,
            checkpoint=next_checkpoint,
        )
        try:
            while True:
                item = next(generator)
                assert isinstance(item, (Document, HierarchyNode))
                items.append(item)
        except StopIteration as stop:
            next_checkpoint = stop.value

        if not next_checkpoint.has_more:
            return items


def _docs_by_path(docs: list[Document]) -> dict[str, Document]:
    docs_by_path: dict[str, Document] = {}
    for doc in docs:
        path = doc.metadata["path"]
        assert isinstance(path, str)
        docs_by_path[path] = doc
    return docs_by_path


def _assert_hierarchy_contract(
    items: Sequence[Document | SlimDocument | HierarchyNode],
) -> None:
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


def _assert_slim_docs_match_full_doc_hierarchy(connector: SeafileConnector) -> None:
    full_docs = _flatten_batches(connector)
    slim_docs = _flatten_slim_batches(connector)

    full_parent_by_id = {
        doc.id: doc.parent_hierarchy_raw_node_id for doc in full_docs if doc.id
    }
    slim_parent_by_id = {doc.id: doc.parent_hierarchy_raw_node_id for doc in slim_docs}

    assert slim_parent_by_id == full_parent_by_id


def _authenticated_seafile_session(base_url: str) -> requests.Session:
    session = requests.Session()
    login_page = session.get(f"{base_url}/accounts/login/", timeout=20)
    login_page.raise_for_status()
    csrf_token = session.cookies.get("sfcsrftoken") or session.cookies.get("csrftoken")
    assert csrf_token

    response = session.post(
        f"{base_url}/accounts/login/",
        data={
            "login": SEAFILE_ADMIN_EMAIL,
            "password": SEAFILE_ADMIN_PASSWORD,
            "next": "/",
            "csrfmiddlewaretoken": csrf_token,
        },
        headers={
            "Referer": f"{base_url}/accounts/login/",
            "X-CSRFToken": csrf_token,
        },
        timeout=20,
    )
    response.raise_for_status()
    return session


def _disable_retries_for_negative_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    def single_request(
        method: str,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        headers: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> requests.Response:
        response = requests.request(
            method=method,
            url=url,
            data=data,
            headers=headers,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        return response

    monkeypatch.setattr(
        "onyx.connectors.seafile.connector.request_with_retries",
        single_request,
    )


def test_live_sync_produces_expected_document_contract(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    docs = _flatten_batches(_connector(seafile_test_library))

    docs_by_path = {doc.metadata["path"]: doc for doc in docs}
    assert set(docs_by_path) == set(seafile_test_library.seeded_text_files)

    for path, expected_text in seafile_test_library.seeded_text_files.items():
        doc = docs_by_path[path]
        filename = path.rsplit("/", 1)[1]
        extension = "." + filename.rsplit(".", 1)[1]
        expected_source_url = (
            f"{seafile_test_library.base_url}/lib/"
            f"{seafile_test_library.repo_id}/file{path}"
        )

        assert doc.id == f"seafile:{seafile_test_library.repo_id}:{path}"
        assert doc.source == DocumentSource.SEAFILE
        assert doc.semantic_identifier == filename
        assert doc.title == filename
        assert doc.sections[0].text == expected_text.strip()
        assert doc.sections[0].link == expected_source_url
        assert doc.metadata["repo_id"] == seafile_test_library.repo_id
        assert doc.metadata["library_id"] == seafile_test_library.repo_id
        assert doc.metadata["library_name"] == seafile_test_library.library_name
        assert doc.metadata["path"] == path
        assert doc.metadata["path_parts"] == [part for part in path.split("/") if part]
        folder_path = path.rsplit("/", 1)[0] or "/"
        assert doc.metadata["folder_path"] == folder_path
        assert doc.metadata["folder_path_parts"] == [
            part for part in folder_path.split("/") if part
        ]
        assert doc.metadata["folder_name"] == (
            "" if folder_path == "/" else folder_path.rsplit("/", 1)[1]
        )
        assert doc.metadata["filename"] == filename
        assert doc.metadata["extension"] == extension
        assert doc.metadata["source_url"] == expected_source_url
        assert "size" in doc.metadata
        assert isinstance(doc.metadata["size"], str)
        assert doc.doc_metadata is not None
        assert isinstance(doc.doc_metadata["size"], int)
        assert doc.doc_metadata["source_url"] == expected_source_url
        assert doc.doc_metadata["library_name"] == seafile_test_library.library_name
        assert doc.doc_metadata["folder_path"] == folder_path
        assert doc.doc_updated_at is not None
        assert doc.parent_hierarchy_raw_node_id == (
            f"seafile:folder:{seafile_test_library.repo_id}:{folder_path}"
        )


def test_live_sync_produces_hierarchy_nodes(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    items = _flatten_items(_connector(seafile_test_library))

    nodes = [item for item in items if isinstance(item, HierarchyNode)]
    node_by_raw_id = {node.raw_node_id: node for node in nodes}
    library_raw_id = f"seafile:library:{seafile_test_library.repo_id}"
    docs_raw_id = f"seafile:folder:{seafile_test_library.repo_id}:/docs"

    assert set(node_by_raw_id) == {library_raw_id, docs_raw_id}
    assert node_by_raw_id[library_raw_id].raw_parent_id is None
    assert node_by_raw_id[library_raw_id].display_name == (
        seafile_test_library.library_name
    )
    assert node_by_raw_id[library_raw_id].node_type == HierarchyNodeType.FOLDER
    assert node_by_raw_id[docs_raw_id].raw_parent_id == library_raw_id
    assert node_by_raw_id[docs_raw_id].display_name == "docs"
    assert node_by_raw_id[docs_raw_id].node_type == HierarchyNodeType.FOLDER
    _assert_hierarchy_contract(items)


def test_live_source_urls_resolve_for_authenticated_session(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    docs = _flatten_batches(_connector(seafile_test_library))
    session = _authenticated_seafile_session(seafile_test_library.base_url)

    for doc in docs:
        source_url = doc.metadata["source_url"]
        assert isinstance(source_url, str)
        response = session.get(source_url, allow_redirects=False, timeout=20)
        assert response.status_code == 200


def test_live_healthcheck_lists_configured_path(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    connector = _connector(seafile_test_library)

    connector.validate_connector_settings()

    slim_doc_ids = {slim_doc.id for slim_doc in _flatten_slim_batches(connector)}
    assert slim_doc_ids == {
        f"seafile:{seafile_test_library.repo_id}:{path}"
        for path in seafile_test_library.seeded_text_files
    }


def test_live_sync_respects_configured_path_scope(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    scoped_docs = _flatten_batches(
        _custom_connector(
            seafile_test_library,
            path_prefixes=["/docs"],
            allowed_extensions=[".txt"],
            max_file_size_bytes=200,
        )
    )
    unscoped_docs = _flatten_batches(
        _custom_connector(
            seafile_test_library,
            path_prefixes=["/"],
            allowed_extensions=[".txt"],
            max_file_size_bytes=200,
        )
    )

    scoped_paths = {doc.metadata["path"] for doc in scoped_docs}
    unscoped_paths = {doc.metadata["path"] for doc in unscoped_docs}

    assert scoped_paths == {"/docs/readme.txt"}
    assert "/private/secret.txt" not in scoped_paths
    assert "/private/secret.txt" in unscoped_paths


def test_live_sync_respects_allowed_extensions(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    txt_docs = _flatten_batches(
        _custom_connector(
            seafile_test_library,
            allowed_extensions=[".txt"],
            max_file_size_bytes=200,
        )
    )
    csv_docs = _flatten_batches(
        _custom_connector(
            seafile_test_library,
            allowed_extensions=[".csv"],
        )
    )

    assert {doc.metadata["path"] for doc in txt_docs} == {"/docs/readme.txt"}
    assert {doc.metadata["path"] for doc in csv_docs} == set(
        seafile_test_library.seeded_csv_files
    )


def test_live_sync_skips_files_over_max_size(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    docs = _flatten_batches(
        _custom_connector(
            seafile_test_library,
            allowed_extensions=[".txt"],
            max_file_size_bytes=200,
        )
    )

    indexed_paths = {doc.metadata["path"] for doc in docs}

    assert "/docs/readme.txt" in indexed_paths
    assert indexed_paths.isdisjoint(seafile_test_library.seeded_large_files)


def test_live_sync_batches_documents(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    connector = _custom_connector(
        seafile_test_library,
        allowed_extensions=[".txt", ".md"],
        max_file_size_bytes=200,
        batch_size=1,
    )

    checkpoint = connector.build_dummy_checkpoint()
    document_counts_by_checkpoint: list[int] = []
    while checkpoint.has_more:
        generator = connector.load_from_checkpoint(0, 1, checkpoint)
        document_count = 0
        try:
            while True:
                if isinstance(next(generator), Document):
                    document_count += 1
        except StopIteration as stop:
            checkpoint = stop.value
        if document_count:
            document_counts_by_checkpoint.append(document_count)

    assert document_counts_by_checkpoint == [1, 1]


def test_live_slim_docs_match_full_document_ids(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    connector = _connector(seafile_test_library)

    full_doc_ids = {doc.id for doc in _flatten_batches(connector)}
    slim_doc_ids = {slim_doc.id for slim_doc in _flatten_slim_batches(connector)}

    assert slim_doc_ids == full_doc_ids
    assert {
        slim_doc.parent_hierarchy_raw_node_id
        for slim_doc in _flatten_slim_batches(connector)
    } == {f"seafile:folder:{seafile_test_library.repo_id}:/docs"}
    _assert_slim_docs_match_full_doc_hierarchy(connector)


def test_live_validation_failure_for_invalid_token(
    seafile_test_library: SeafileTestLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_retries_for_negative_validation(monkeypatch)
    connector = _custom_connector(seafile_test_library, api_token="invalid-token")

    try:
        connector.validate_connector_settings()
    except CredentialExpiredError:
        return
    except ConnectorValidationError as exc:
        assert "invalid" in str(exc).lower() or "forbidden" in str(exc).lower()
        return

    raise AssertionError("Expected invalid Seafile token to fail validation")


def test_live_validation_failure_for_missing_path(
    seafile_test_library: SeafileTestLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _disable_retries_for_negative_validation(monkeypatch)
    connector = _custom_connector(
        seafile_test_library,
        path_prefixes=["/missing"],
    )

    try:
        connector.validate_connector_settings()
    except ConnectorValidationError as exc:
        assert "not found" in str(exc).lower() or "failed" in str(exc).lower()
        return

    raise AssertionError("Expected missing Seafile path to fail validation")


def test_live_sync_indexes_two_text_files_and_skips_unsupported_file(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    docs = _flatten_batches(_connector(seafile_test_library))

    indexed_paths = {doc.metadata["path"] for doc in docs}

    assert indexed_paths == set(seafile_test_library.seeded_text_files)
    assert indexed_paths.isdisjoint(seafile_test_library.seeded_unsupported_files)


def test_live_sync_fetches_expected_file_content(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    docs = _flatten_batches(_connector(seafile_test_library))

    docs_by_path = {doc.metadata["path"]: doc for doc in docs}

    for path, expected_text in seafile_test_library.seeded_text_files.items():
        assert docs_by_path[path].sections[0].text == expected_text.strip()


def test_live_sync_extracts_parser_supported_files(
    seafile_test_library: SeafileTestLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        extract_file_text_module,
        "get_unstructured_api_key",
        lambda: None,
    )
    connector = _custom_connector(
        seafile_test_library,
        allowed_extensions=[".eml", ".epub", ".xlsm"],
    )

    docs = _flatten_batches(connector)
    docs_by_path = {doc.metadata["path"]: doc for doc in docs}

    assert set(docs_by_path) == set(seafile_test_library.seeded_parser_files)
    for path, expected_text in seafile_test_library.seeded_parser_files.items():
        section_text = "\n".join(
            section.text or "" for section in docs_by_path[path].sections
        )
        assert expected_text in section_text


def test_live_sync_produces_stable_ids_across_two_runs(
    seafile_test_library: SeafileTestLibrary,
) -> None:
    first_run_docs = _flatten_batches(_connector(seafile_test_library))
    second_run_docs = _flatten_batches(_connector(seafile_test_library))

    first_run_ids = [doc.id for doc in first_run_docs]
    second_run_ids = [doc.id for doc in second_run_docs]

    assert first_run_ids == second_run_ids
    assert set(first_run_ids) == {
        f"seafile:{seafile_test_library.repo_id}:{path}"
        for path in seafile_test_library.seeded_text_files
    }

    docs_by_path = {doc.metadata["path"]: doc for doc in first_run_docs}
    for path in seafile_test_library.seeded_text_files:
        doc = docs_by_path[path]
        assert doc.id == f"seafile:{seafile_test_library.repo_id}:{path}"
        assert doc.source == DocumentSource.SEAFILE
        assert doc.metadata["repo_id"] == seafile_test_library.repo_id
        assert doc.metadata["library_id"] == seafile_test_library.repo_id
        assert doc.metadata["library_name"] == seafile_test_library.library_name
        assert doc.metadata["source_url"] == (
            f"{seafile_test_library.base_url}/lib/"
            f"{seafile_test_library.repo_id}/file{path}"
        )


def test_live_overwrite_updates_content_with_stable_document_id(
    seafile_mutation_test_library: SeafileTestLibrary,
) -> None:
    connector = _custom_connector(
        seafile_mutation_test_library,
        allowed_extensions=[".txt"],
        max_file_size_bytes=200,
    )
    original_doc = _docs_by_path(_flatten_batches(connector))["/docs/readme.txt"]

    time.sleep(1.1)
    overwrite_file(
        base_url=seafile_mutation_test_library.base_url,
        api_token=seafile_mutation_test_library.api_token,
        repo_id=seafile_mutation_test_library.repo_id,
        path="/docs/readme.txt",
        content=b"Mutation fixture readme replaced\n",
    )

    updated_doc = _docs_by_path(_flatten_batches(connector))["/docs/readme.txt"]

    assert updated_doc.id == original_doc.id
    assert updated_doc.sections[0].text == "Mutation fixture readme replaced"
    assert updated_doc.doc_updated_at is not None
    assert original_doc.doc_updated_at is None or (
        updated_doc.doc_updated_at >= original_doc.doc_updated_at
    )
    assert updated_doc.metadata["modified_time"] == (
        updated_doc.doc_updated_at.isoformat()
    )


def test_live_delete_removes_file_from_full_and_slim_listing(
    seafile_mutation_test_library: SeafileTestLibrary,
) -> None:
    connector = _custom_connector(
        seafile_mutation_test_library,
        allowed_extensions=[".txt"],
        max_file_size_bytes=200,
    )
    removed_id = f"seafile:{seafile_mutation_test_library.repo_id}:/docs/delete-me.txt"

    delete_file(
        base_url=seafile_mutation_test_library.base_url,
        api_token=seafile_mutation_test_library.api_token,
        repo_id=seafile_mutation_test_library.repo_id,
        path="/docs/delete-me.txt",
    )

    full_doc_ids = {doc.id for doc in _flatten_batches(connector)}
    slim_doc_ids = {doc.id for doc in _flatten_slim_batches(connector)}

    assert removed_id not in full_doc_ids
    assert removed_id not in slim_doc_ids
    assert f"seafile:{seafile_mutation_test_library.repo_id}:/docs/readme.txt" in (
        full_doc_ids
    )


def test_live_move_file_changes_document_id_and_parent_metadata(
    seafile_mutation_test_library: SeafileTestLibrary,
) -> None:
    connector = _custom_connector(
        seafile_mutation_test_library,
        allowed_extensions=[".txt"],
        max_file_size_bytes=200,
    )
    old_id = f"seafile:{seafile_mutation_test_library.repo_id}:/docs/move-me.txt"
    new_path = "/docs/moved/move-me.txt"
    new_id = f"seafile:{seafile_mutation_test_library.repo_id}:{new_path}"

    move_file(
        base_url=seafile_mutation_test_library.base_url,
        api_token=seafile_mutation_test_library.api_token,
        repo_id=seafile_mutation_test_library.repo_id,
        source_path="/docs/move-me.txt",
        destination_dir="/docs/moved",
    )

    docs_by_path = _docs_by_path(_flatten_batches(connector))

    assert old_id not in {doc.id for doc in docs_by_path.values()}
    assert docs_by_path[new_path].id == new_id
    assert docs_by_path[new_path].metadata["folder_path"] == "/docs/moved"
    assert docs_by_path[new_path].metadata["source_url"] == (
        f"{seafile_mutation_test_library.base_url}/lib/"
        f"{seafile_mutation_test_library.repo_id}/file{new_path}"
    )
    assert docs_by_path[new_path].parent_hierarchy_raw_node_id == (
        f"seafile:folder:{seafile_mutation_test_library.repo_id}:/docs/moved"
    )


def test_live_move_file_out_of_scope_disappears_from_scoped_connector(
    seafile_mutation_test_library: SeafileTestLibrary,
) -> None:
    scoped_connector = _custom_connector(
        seafile_mutation_test_library,
        path_prefixes=["/docs"],
        allowed_extensions=[".txt"],
        max_file_size_bytes=200,
    )
    root_connector = _custom_connector(
        seafile_mutation_test_library,
        path_prefixes=["/"],
        allowed_extensions=[".txt"],
        max_file_size_bytes=200,
    )
    old_path = "/docs/move-me.txt"
    new_path = "/private/move-me.txt"

    move_file(
        base_url=seafile_mutation_test_library.base_url,
        api_token=seafile_mutation_test_library.api_token,
        repo_id=seafile_mutation_test_library.repo_id,
        source_path=old_path,
        destination_dir="/private",
    )

    scoped_paths = {doc.metadata["path"] for doc in _flatten_batches(scoped_connector)}
    root_paths = {doc.metadata["path"] for doc in _flatten_batches(root_connector)}

    assert old_path not in scoped_paths
    assert new_path not in scoped_paths
    assert new_path in root_paths


def test_live_delete_folder_removes_stale_doc_and_hierarchy_node(
    seafile_mutation_test_library: SeafileTestLibrary,
) -> None:
    connector = _custom_connector(
        seafile_mutation_test_library,
        allowed_extensions=[".txt"],
        max_file_size_bytes=200,
    )

    delete_directory(
        base_url=seafile_mutation_test_library.base_url,
        api_token=seafile_mutation_test_library.api_token,
        repo_id=seafile_mutation_test_library.repo_id,
        path="/docs/obsolete",
    )

    items = _flatten_items(connector)
    doc_paths = {item.metadata["path"] for item in items if isinstance(item, Document)}
    node_ids = {item.raw_node_id for item in items if isinstance(item, HierarchyNode)}

    assert "/docs/obsolete/stale.txt" not in doc_paths
    assert (
        f"seafile:folder:{seafile_mutation_test_library.repo_id}:/docs/obsolete"
        not in node_ids
    )
    _assert_hierarchy_contract(items)
