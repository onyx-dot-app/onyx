"""External dependency tests for reading the OpenSearch version.

They run against the real cluster and replace only its main endpoint
response, to stand in for an AWS domain in Elasticsearch compatibility mode.
"""

from typing import Any

import pytest

from onyx.document_index.opensearch.client import (
    OpenSearchClient,
    wait_for_opensearch_with_timeout,
)


@pytest.fixture
def client() -> OpenSearchClient:
    if not wait_for_opensearch_with_timeout():
        pytest.fail("OpenSearch is not available.")
    return OpenSearchClient()


def _real_version(client: OpenSearchClient) -> tuple[int, int]:
    number: str = client._client.info()["version"]["number"]
    major, minor = number.split(".")[:2]
    return int(major), int(minor)


def _main_response(
    client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch, version: dict[str, Any]
) -> None:
    monkeypatch.setattr(client._client, "info", lambda: {"version": version})


def test_the_main_endpoint_reports_the_version(client: OpenSearchClient) -> None:
    version: tuple[int, int] | None = client.get_opensearch_version()
    assert version is not None
    assert version == _real_version(client)


def test_compatibility_mode_reads_the_version_from_the_nodes(
    client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    real: tuple[int, int] = _real_version(client)
    # An AWS domain with override_main_response_version on answers as
    # Elasticsearch 7.10.2, with no OpenSearch distribution.
    _main_response(client, monkeypatch, {"number": "7.10.2"})
    assert client.get_opensearch_version() == real


def test_another_cluster_reports_no_version(
    client: OpenSearchClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A real Elasticsearch cluster is not read as OpenSearch.
    _main_response(
        client,
        monkeypatch,
        {"number": "8.15.0", "build_flavor": "default"},
    )
    assert client.get_opensearch_version() is None
