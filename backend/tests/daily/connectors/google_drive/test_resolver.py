"""Tests for GoogleDriveConnector.reindex against real Google Drive."""

import json
import os
from collections.abc import Callable
from unittest.mock import patch

import pytest

from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import HierarchyNode
from tests.daily.connectors.google_drive.consts_and_utils import ADMIN_EMAIL
from tests.daily.connectors.google_drive.consts_and_utils import (
    ALL_EXPECTED_HIERARCHY_NODES,
)
from tests.daily.connectors.google_drive.consts_and_utils import FOLDER_1_ID
from tests.daily.connectors.google_drive.consts_and_utils import SHARED_DRIVE_1_ID
from tests.utils.secret_names import TestSecret

_DRIVE_ID_MAPPING_PATH = os.path.join(
    os.path.dirname(__file__), "drive_id_mapping.json"
)


def _load_web_view_links(file_ids: list[int]) -> list[str]:
    with open(_DRIVE_ID_MAPPING_PATH) as f:
        mapping: dict[str, str] = json.load(f)
    return [mapping[str(fid)] for fid in file_ids]


def _build_failures(web_view_links: list[str]) -> list[ConnectorFailure]:
    return [
        ConnectorFailure(
            failed_document=DocumentFailure(
                document_id=link,
                document_link=link,
            ),
            failure_message=f"Synthetic failure for {link}",
        )
        for link in web_view_links
    ]


@pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR)
@patch("onyx.file_processing.extract_file_text.get_unstructured_api_key")
def test_resolve_single_file(
    mock_api_key: None,  # noqa: ARG001
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    """Resolve a single known file and verify we get back exactly one Document."""
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        shared_drive_urls=None,
        include_my_drives=True,
        my_drive_emails=None,
        shared_folder_urls=None,
        include_files_shared_with_me=False,
    )

    web_view_links = _load_web_view_links([0])
    failures = _build_failures(web_view_links)

    results = list(connector.reindex(failures))

    docs = [r for r in results if isinstance(r, Document)]
    new_failures = [r for r in results if isinstance(r, ConnectorFailure)]
    hierarchy_nodes = [r for r in results if isinstance(r, HierarchyNode)]

    assert len(docs) == 1
    assert len(new_failures) == 0
    assert docs[0].semantic_identifier == "file_0.txt"

    # Should yield at least one hierarchy node (the file's parent folder chain)
    assert len(hierarchy_nodes) > 0


@pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR)
@patch("onyx.file_processing.extract_file_text.get_unstructured_api_key")
def test_resolve_multiple_files(
    mock_api_key: None,  # noqa: ARG001
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    """Resolve multiple files across different folders via batch API."""
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        shared_drive_urls=None,
        include_my_drives=True,
        my_drive_emails=None,
        shared_folder_urls=None,
        include_files_shared_with_me=False,
    )

    # Pick files from different folders: admin files (0-4), shared drive 1 (20-24), folder_2 (45-49)
    file_ids = [0, 1, 20, 21, 45]
    web_view_links = _load_web_view_links(file_ids)
    failures = _build_failures(web_view_links)

    results = list(connector.reindex(failures))

    docs = [r for r in results if isinstance(r, Document)]
    new_failures = [r for r in results if isinstance(r, ConnectorFailure)]
    hierarchy_nodes = [r for r in results if isinstance(r, HierarchyNode)]

    assert len(new_failures) == 0
    retrieved_names = {doc.semantic_identifier for doc in docs}
    expected_names = {f"file_{fid}.txt" for fid in file_ids}
    assert expected_names == retrieved_names

    # Files span multiple folders, so we should get hierarchy nodes
    assert len(hierarchy_nodes) > 0


@pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR)
@patch("onyx.file_processing.extract_file_text.get_unstructured_api_key")
def test_resolve_hierarchy_nodes_are_valid(
    mock_api_key: None,  # noqa: ARG001
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    """Verify that hierarchy nodes from reindex match expected structure."""
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        shared_drive_urls=None,
        include_my_drives=True,
        my_drive_emails=None,
        shared_folder_urls=None,
        include_files_shared_with_me=False,
    )

    # File in folder_1 (inside shared_drive_1) — should walk up to shared_drive_1 root
    web_view_links = _load_web_view_links([25])
    failures = _build_failures(web_view_links)

    results = list(connector.reindex(failures))

    hierarchy_nodes = [r for r in results if isinstance(r, HierarchyNode)]
    node_ids = {node.raw_node_id for node in hierarchy_nodes}

    # File 25 is in folder_1 which is inside shared_drive_1.
    # The parent walk must yield at least these two ancestors.
    assert (
        FOLDER_1_ID in node_ids
    ), f"Expected folder_1 ({FOLDER_1_ID}) in hierarchy nodes, got: {node_ids}"
    assert (
        SHARED_DRIVE_1_ID in node_ids
    ), f"Expected shared_drive_1 ({SHARED_DRIVE_1_ID}) in hierarchy nodes, got: {node_ids}"

    for node in hierarchy_nodes:
        if node.raw_node_id not in ALL_EXPECTED_HIERARCHY_NODES:
            continue
        expected = ALL_EXPECTED_HIERARCHY_NODES[node.raw_node_id]
        assert node.display_name == expected.display_name, (
            f"Display name mismatch for {node.raw_node_id}: "
            f"expected '{expected.display_name}', got '{node.display_name}'"
        )
        assert node.node_type == expected.node_type, (
            f"Node type mismatch for {node.raw_node_id}: "
            f"expected '{expected.node_type}', got '{node.node_type}'"
        )


@pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR)
@patch("onyx.file_processing.extract_file_text.get_unstructured_api_key")
def test_resolve_with_invalid_link(
    mock_api_key: None,  # noqa: ARG001
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    """Resolve with a mix of valid and invalid links — invalid ones yield ConnectorFailure."""
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        shared_drive_urls=None,
        include_my_drives=True,
        my_drive_emails=None,
        shared_folder_urls=None,
        include_files_shared_with_me=False,
    )

    valid_links = _load_web_view_links([0])
    invalid_link = "https://drive.google.com/file/d/NONEXISTENT_FILE_ID_12345"
    failures = _build_failures(valid_links + [invalid_link])

    results = list(connector.reindex(failures))

    docs = [r for r in results if isinstance(r, Document)]
    new_failures = [r for r in results if isinstance(r, ConnectorFailure)]

    assert len(docs) == 1
    assert docs[0].semantic_identifier == "file_0.txt"
    assert len(new_failures) == 1
    assert new_failures[0].failed_document is not None
    assert new_failures[0].failed_document.document_id == invalid_link


@pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR)
@patch("onyx.file_processing.extract_file_text.get_unstructured_api_key")
def test_resolve_empty_errors(
    mock_api_key: None,  # noqa: ARG001
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    """Resolving an empty error list should yield nothing."""
    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        shared_drive_urls=None,
        include_my_drives=True,
        my_drive_emails=None,
        shared_folder_urls=None,
        include_files_shared_with_me=False,
    )

    results = list(connector.reindex([]))

    assert len(results) == 0


@pytest.mark.secrets(TestSecret.GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON_STR)
@patch("onyx.file_processing.extract_file_text.get_unstructured_api_key")
def test_resolve_entity_failures_are_skipped(
    mock_api_key: None,  # noqa: ARG001
    google_drive_service_acct_connector_factory: Callable[..., GoogleDriveConnector],
) -> None:
    """Entity failures (not document failures) should be skipped by reindex."""
    from onyx.connectors.models import EntityFailure

    connector = google_drive_service_acct_connector_factory(
        primary_admin_email=ADMIN_EMAIL,
        include_shared_drives=True,
        shared_drive_urls=None,
        include_my_drives=True,
        my_drive_emails=None,
        shared_folder_urls=None,
        include_files_shared_with_me=False,
    )

    entity_failure = ConnectorFailure(
        failed_entity=EntityFailure(entity_id="some_stage"),
        failure_message="retrieval failure",
    )

    results = list(connector.reindex([entity_failure]))

    assert len(results) == 0
