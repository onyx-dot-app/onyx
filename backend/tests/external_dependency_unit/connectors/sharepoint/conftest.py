"""Fixtures that point the SharePoint connector at the mock Graph and
SharePoint server (tests/integration/mock_services/mock_sharepoint_server)."""

import time
from collections.abc import Iterator
from typing import Any
from unittest import mock

import httpx
import pytest
from pydantic import BaseModel, ConfigDict

from onyx.connectors.models import ConnectorFailure, HierarchyNode, SlimDocumentStub
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)
from tests.integration.mock_services.mock_sharepoint_server.mock_sharepoint.patch_onyx import (
    point_onyx_at_mock,
)
from tests.integration.mock_services.mock_sharepoint_server.mock_sharepoint.runner import (
    start_mock_server,
)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_SMALL_CORPUS = {
    "num_sites": 2,
    "libraries_per_site": 2,
    "folder_depth": 2,
    "folder_branching": 2,
    "files_per_folder": 2,
    "pages_per_site": 2,
    # Enough unique permissions and sharing links for the permission tests.
    "unique_permission_fraction": 0.3,
    "public_fraction": 0.3,
    "sharing_link_fraction": 0.2,
}
_CONFIG = {"corpus": _SMALL_CORPUS, "latency": {"enabled": False}}
# The module's shared server serves several full runs with permission reads
# in one minute, which pass the smallest tier. Throttle tests use their own
# server and set its quota.
_SHARED_CONFIG = {**_CONFIG, "quota": {"ru_per_minute": 1_000_000}}


class MockSharepoint(BaseModel):
    """A running mock server and a client for its control endpoints."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    url: str
    client: httpx.Client

    def _get(self, path: str, **params: Any) -> dict[str, Any]:
        response = self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self.client.post(path, json=body or {})
        response.raise_for_status()
        return response.json()

    # --- the corpus ---

    def summary(self) -> dict[str, Any]:
        return self._get("/_mock/corpus/summary", include_ids=True)

    def site_urls(self) -> list[str]:
        return list(self.summary()["site_urls"])

    def drive_ids(self) -> list[str]:
        return list(self.summary()["drive_ids"])

    def supported_file_ids(self) -> set[str]:
        return set(self.summary()["supported_file_ids"])

    def unsupported_file_ids(self) -> set[str]:
        return set(self.summary()["unsupported_file_ids"])

    def page_ids(self) -> set[str]:
        return set(self.summary()["page_ids"])

    def document_ids(self) -> set[str]:
        """The ids a full run must index: each supported file and each page."""
        summary = self.summary()
        return set(summary["supported_file_ids"]) | set(summary["page_ids"])

    def hierarchy_node_ids(self) -> set[str]:
        """The raw ids of the site, library and folder nodes of the corpus."""
        summary = self.summary()
        return {
            *summary["site_urls"],
            *summary["drive_web_urls"],
            *summary["folder_web_urls"],
        }

    def describe_file(self, item_id: str) -> dict[str, Any]:
        """A file or folder as stored, with its `effective_access`."""
        return self._get(f"/_mock/corpus/files/{item_id}")

    def describe_page(self, page_id: str) -> dict[str, Any]:
        return self._get(f"/_mock/corpus/pages/{page_id}")

    def sites(self) -> list[dict[str, Any]]:
        """Each site with its libraries, their access and its groups."""
        return list(self._get("/_mock/corpus/sites")["sites"])

    def set_corpus(self, corpus: dict[str, Any]) -> None:
        """Generates a new corpus. Resets the stats."""
        self._post("/_mock/corpus", corpus)

    def touch(self, file_ids: list[str]) -> None:
        self._post("/_mock/corpus/touch", {"file_ids": file_ids})

    def add_file(self, **file: Any) -> dict[str, Any]:
        return self._post("/_mock/corpus/files", file)

    def delete_file(self, item_id: str) -> None:
        self.client.delete(f"/_mock/corpus/files/{item_id}").raise_for_status()

    def set_permissions(self, **request: Any) -> dict[str, Any]:
        return self._post("/_mock/corpus/permissions", request)

    def write_during_walk(self, **hook: Any) -> dict[str, Any]:
        return self._post("/_mock/corpus/write-during-walk", hook)

    def walk_hooks(self) -> list[dict[str, Any]]:
        return list(self._get("/_mock/corpus/write-during-walk")["hooks"])

    # --- the server ---

    def stats(self) -> dict[str, Any]:
        return self._get("/_mock/stats")

    def reset_stats(self) -> None:
        """Clears the stats, the RU counts and each pause."""
        self._post("/_mock/stats/reset")

    def patch_config(self, patch: dict[str, Any]) -> None:
        self.client.patch("/_mock/config", json=patch).raise_for_status()

    def op_count(self, op: str) -> int:
        """Calls of one operation since the last stats reset."""
        return int(self.stats()["ops"].get(op, {}).get("count", 0))

    def credentials(self, certificate: bool = False) -> dict[str, Any]:
        forms = self._get("/_mock/credentials")
        return dict(forms["certificate" if certificate else "client_secret"])

    def build_connector(
        self, certificate: bool = False, **kwargs: Any
    ) -> SharepointConnector:
        """A connector for the whole mock tenant. Permission sync needs
        `certificate=True`: SharePoint REST refuses a client secret token."""
        connector = SharepointConnector(**kwargs)
        connector.load_credentials(self.credentials(certificate))
        return connector

    def graph_get(
        self,
        path: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """A Graph call through the mock's own path prefix, as the connector's
        app. `path` may be a full link from an earlier answer."""
        token = self.access_token("https://graph.microsoft.com")
        path = path.removeprefix(GRAPH_BASE)
        return self.client.get(
            f"/graph/v1.0{path}",
            params=params,
            headers={**(headers or {}), "Authorization": f"Bearer {token}"},
        )

    def access_token(self, resource: str, client_id: str | None = None) -> str:
        credentials = self.credentials()
        response = self.client.post(
            f"/login/{credentials['sp_directory_id']}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id or credentials["sp_client_id"],
                "client_secret": credentials["sp_client_secret"],
                "scope": f"{resource}/.default",
            },
        )
        response.raise_for_status()
        return str(response.json()["access_token"])


@pytest.fixture(scope="module")
def mock_sharepoint_url() -> Iterator[str]:
    process, url = start_mock_server(_SHARED_CONFIG)
    try:
        yield url
    finally:
        process.terminate()
        process.wait(timeout=30)


@pytest.fixture
def _no_unstructured_api() -> Iterator[None]:
    """Text extraction reads the Unstructured API key from the database."""
    with mock.patch(
        "onyx.file_processing.extract_file_text.get_unstructured_api_key",
        return_value=None,
    ):
        yield


@pytest.fixture
def mock_sharepoint(
    mock_sharepoint_url: str,
    _no_unstructured_api: None,
) -> Iterator[MockSharepoint]:
    """The module's shared mock server. Do not change its corpus or config:
    use ``own_mock_sharepoint`` for that."""
    with (
        point_onyx_at_mock(mock_sharepoint_url),
        httpx.Client(base_url=mock_sharepoint_url, timeout=30) as client,
    ):
        client.post("/_mock/stats/reset").raise_for_status()
        yield MockSharepoint(url=mock_sharepoint_url, client=client)


@pytest.fixture
def own_mock_sharepoint(
    _no_unstructured_api: None,
) -> Iterator[MockSharepoint]:
    """A mock server for one test, which can change its corpus and config."""
    process, url = start_mock_server(_CONFIG)
    try:
        with (
            point_onyx_at_mock(url),
            httpx.Client(base_url=url, timeout=120) as client,
        ):
            yield MockSharepoint(url=url, client=client)
    finally:
        process.terminate()
        process.wait(timeout=30)


@pytest.fixture
def ee_permission_sync(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Permission sync is Enterprise code. Without it the connector gives each
    document empty access."""
    fetch_versioned_implementation.cache_clear()
    monkeypatch.setattr(global_version, "is_ee_version", lambda: True)
    yield
    fetch_versioned_implementation.cache_clear()


class StubListing:
    def __init__(self) -> None:
        self.stubs: list[SlimDocumentStub] = []
        self.nodes: list[HierarchyNode] = []
        self.failures: list[ConnectorFailure] = []
        self.steps = 0
        self.largest_checkpoint = 0


def list_stubs(
    connector: SharepointConnector,
    start: float = 0,
    end: float | None = None,
    include_permissions: bool = False,
) -> StubListing:
    """Runs the stub listing to its end, each step from the checkpoint as
    docfetching stores it."""
    listing = StubListing()
    checkpoint = connector.build_dummy_checkpoint()
    end = time.time() if end is None else end
    while checkpoint.has_more:
        listing.steps += 1
        assert listing.steps < 10_000, "the listing does not end"
        step = connector.retrieve_slim_docs_from_checkpoint(
            start, end, checkpoint, include_permissions
        )
        while True:
            try:
                item = next(step)
            except StopIteration as stop:
                checkpoint = stop.value
                break
            if isinstance(item, SlimDocumentStub):
                listing.stubs.append(item)
            elif isinstance(item, HierarchyNode):
                listing.nodes.append(item)
            elif isinstance(item, ConnectorFailure):
                listing.failures.append(item)
        stored = checkpoint.model_dump_json()
        listing.largest_checkpoint = max(listing.largest_checkpoint, len(stored))
        checkpoint = connector.validate_checkpoint_json(stored)
    return listing
