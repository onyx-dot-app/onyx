"""Fixtures that point the Google connectors at the mock Google Drive server
(tests/integration/mock_services/mock_google_drive_server)."""

import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ConfigDict
from scripts.benchmark_google_drive_connector import start_mock_server

from onyx.connectors.google_drive import source_operations
from onyx.connectors.google_drive.connector import GoogleDriveConnector
from onyx.connectors.google_utils import google_auth, resources

_SMALL_CORPUS = {
    "num_users": 3,
    "num_groups": 2,
    "num_shared_drives": 2,
    "files_per_shared_drive": 15,
    "files_per_user": 8,
    "folders_per_container": 3,
}


class MockDrive(BaseModel):
    """A running mock server and a client for its control endpoints."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str
    client: httpx.Client

    def content_file_ids(self) -> set[str]:
        summary = self.client.get(
            "/_mock/corpus/summary", params={"include_ids": True}
        ).json()
        return set(summary["content_file_ids"])

    def stats(self) -> dict[str, Any]:
        return self.client.get("/_mock/stats").json()

    def reset_stats(self) -> None:
        self.client.post("/_mock/stats/reset").raise_for_status()

    def patch_config(self, patch: dict[str, Any]) -> None:
        self.client.patch("/_mock/config", json=patch).raise_for_status()

    def set_corpus(self, corpus: dict[str, Any]) -> None:
        """Generates a new corpus. Resets the stats."""
        self.client.post("/_mock/corpus", json=corpus).raise_for_status()

    def build_connector(self, **kwargs: Any) -> GoogleDriveConnector:
        """A service account connector for the whole mock Workspace."""
        summary = self.client.get("/_mock/corpus/summary").json()
        key = self.client.get("/_mock/service-account-key").json()
        settings: dict[str, Any] = {
            "include_shared_drives": True,
            "include_my_drives": True,
            "include_files_shared_with_me": True,
        }
        settings.update(kwargs)
        connector = GoogleDriveConnector(**settings)
        connector.load_credentials(
            {
                "google_service_account_key": json.dumps(key),
                "google_primary_admin": summary["admin_email"],
                "authentication_method": "uploaded",
            }
        )
        return connector

    def list_calls(self) -> int:
        """files.list calls since the last stats reset."""
        ops = self.stats()["ops"]
        return int(ops.get("drive.files.list", {}).get("count", 0))


def _patch_google_endpoints(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """Sends this test's Google API calls to the mock server. The values are
    what GOOGLE_API_ENDPOINT_OVERRIDE sets at import time."""
    override = f"{url}/"
    monkeypatch.setattr(resources, "GOOGLE_API_ENDPOINT_OVERRIDE", override)
    monkeypatch.setattr(google_auth, "GOOGLE_API_TOKEN_URI", f"{override}token")
    monkeypatch.setattr(
        source_operations,
        "_DOCS_API_DOCUMENT_URL",
        override + "v1/documents/{doc_id}",
    )
    resources._overridden_discovery_doc.cache_clear()


@pytest.fixture(scope="module")
def mock_drive_url() -> Iterator[str]:
    process, url = start_mock_server(
        {"corpus": _SMALL_CORPUS, "latency": {"enabled": False}}
    )
    try:
        yield url
    finally:
        process.terminate()
        process.wait(timeout=30)


@pytest.fixture
def mock_drive(
    mock_drive_url: str, monkeypatch: pytest.MonkeyPatch
) -> Iterator[MockDrive]:
    """The module's shared mock server. Do not change its corpus or config:
    use ``own_mock_drive`` for that."""
    _patch_google_endpoints(monkeypatch, mock_drive_url)
    with httpx.Client(base_url=mock_drive_url, timeout=30) as client:
        client.post("/_mock/stats/reset").raise_for_status()
        yield MockDrive(url=mock_drive_url, client=client)
    resources._overridden_discovery_doc.cache_clear()


@pytest.fixture
def own_mock_drive(monkeypatch: pytest.MonkeyPatch) -> Iterator[MockDrive]:
    """A mock server for one test, which can change its corpus and config."""
    process, url = start_mock_server(
        {"corpus": _SMALL_CORPUS, "latency": {"enabled": False}}
    )
    try:
        _patch_google_endpoints(monkeypatch, url)
        with httpx.Client(base_url=url, timeout=120) as client:
            yield MockDrive(url=url, client=client)
    finally:
        resources._overridden_discovery_doc.cache_clear()
        process.terminate()
        process.wait(timeout=30)
