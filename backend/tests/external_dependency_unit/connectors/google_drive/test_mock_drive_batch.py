"""Batch requests against the mock Google Drive server, with the real Google
client: the client must match each response part to its request."""

import json
from collections.abc import Iterator

import httpx
import pytest
from scripts.benchmark_google_drive_connector import start_mock_server

from onyx.connectors.google_drive import source_operations
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_drive.file_retrieval import (
    DriveFileFieldType,
    get_files_by_web_view_links_batch,
)
from onyx.connectors.google_utils import google_auth, resources
from onyx.server.documents.models import GoogleServiceAccountKey

_CORPUS = {
    "num_users": 2,
    "num_groups": 1,
    "num_shared_drives": 1,
    "files_per_shared_drive": 10,
    "files_per_user": 5,
    "folders_per_container": 2,
}


@pytest.fixture
def mock_drive_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[httpx.Client]:
    process, url = start_mock_server({"corpus": _CORPUS, "latency": {"enabled": False}})
    try:
        override = f"{url}/"
        monkeypatch.setattr(resources, "GOOGLE_API_ENDPOINT_OVERRIDE", override)
        monkeypatch.setattr(google_auth, "GOOGLE_API_TOKEN_URI", f"{override}token")
        monkeypatch.setattr(
            source_operations,
            "_DOCS_API_DOCUMENT_URL",
            override + "v1/documents/{doc_id}",
        )
        resources._overridden_discovery_doc.cache_clear()
        with httpx.Client(base_url=url, timeout=30) as client:
            yield client
    finally:
        resources._overridden_discovery_doc.cache_clear()
        process.terminate()
        process.wait(timeout=30)


def test_batch_get_files_by_web_view_link(mock_drive_client: httpx.Client) -> None:
    summary = mock_drive_client.get(
        "/_mock/corpus/summary", params={"include_ids": True}
    ).json()
    admin = summary["admin_email"]
    readable = [
        file_id
        for file_id in summary["content_file_ids"]
        if admin
        in mock_drive_client.get(f"/_mock/corpus/files/{file_id}").json()["readers"]
    ]
    assert readable

    connector = GoogleDriveConnector(include_shared_drives=True)
    connector.load_credentials(
        {
            "google_service_account_key": json.dumps(
                mock_drive_client.get("/_mock/service-account-key").json()
            ),
            "google_primary_admin": admin,
            "authentication_method": "uploaded",
        }
    )
    # Long keys: the client folds a long Content-ID header over two lines.
    file_id_by_link = {
        f"https://drive.google.com/file/d/{file_id}/view?usp=drivesdk": file_id
        for file_id in readable
    }
    result = get_files_by_web_view_links_batch(
        connector.ops,
        admin,
        list(file_id_by_link),
        DriveFileFieldType.WITH_PERMISSIONS,
    )

    assert result.errors == {}
    # Each answer belongs to the link that asked for it.
    assert {link: file["id"] for link, file in result.files.items()} == (
        file_id_by_link
    )


def test_service_account_key_is_accepted(mock_drive_client: httpx.Client) -> None:
    """The admin panel accepts the mock's key file as a service account key."""
    key = mock_drive_client.get("/_mock/service-account-key").json()
    assert GoogleServiceAccountKey.model_validate(key).type == "service_account"
