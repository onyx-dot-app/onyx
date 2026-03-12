"""Unit tests for SharepointConnector._fetch_site_pages 404 handling.

The Graph Pages API returns 404 for classic sites or sites without
modern pages enabled.  _fetch_site_pages should gracefully skip these
rather than crashing the entire indexing run.
"""

from __future__ import annotations

from typing import Any

import pytest
from requests import Response
from requests.exceptions import HTTPError

from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.connector import SiteDescriptor

SITE_URL = "https://tenant.sharepoint.com/sites/ClassicSite"
FAKE_SITE_ID = "tenant.sharepoint.com,abc123,def456"


def _site_descriptor() -> SiteDescriptor:
    return SiteDescriptor(url=SITE_URL, drive_name=None, folder_path=None)


def _make_http_error(status_code: int) -> HTTPError:
    response = Response()
    response.status_code = status_code
    response._content = b'{"error":{"code":"itemNotFound","message":"Item not found"}}'
    return HTTPError(response=response)


def _setup_connector(
    monkeypatch: pytest.MonkeyPatch,  # noqa: ARG001
) -> SharepointConnector:
    """Create a connector with the graph client and site resolution mocked."""
    connector = SharepointConnector(sites=[SITE_URL])
    connector.graph_api_base = "https://graph.microsoft.com/v1.0"

    mock_sites = type(
        "FakeSites",
        (),
        {
            "get_by_url": staticmethod(
                lambda url: type(  # noqa: ARG005
                    "Q",
                    (),
                    {
                        "execute_query": lambda self: None,  # noqa: ARG005
                        "id": FAKE_SITE_ID,
                    },
                )()
            ),
        },
    )()
    connector._graph_client = type("FakeGraphClient", (), {"sites": mock_sites})()

    return connector


def _patch_graph_api_get_json(
    monkeypatch: pytest.MonkeyPatch,
    fake_fn: Any,
) -> None:
    monkeypatch.setattr(SharepointConnector, "_graph_api_get_json", fake_fn)


class TestFetchSitePages404:
    def test_404_yields_no_pages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 404 from the Pages API should result in zero yielded pages."""
        connector = _setup_connector(monkeypatch)

        def fake_get_json(
            self: SharepointConnector,  # noqa: ARG001
            url: str,  # noqa: ARG001
            params: dict[str, str] | None = None,  # noqa: ARG001
        ) -> dict[str, Any]:
            raise _make_http_error(404)

        _patch_graph_api_get_json(monkeypatch, fake_get_json)

        pages = list(connector._fetch_site_pages(_site_descriptor()))
        assert pages == []

    def test_404_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A 404 must not propagate as an exception."""
        connector = _setup_connector(monkeypatch)

        def fake_get_json(
            self: SharepointConnector,  # noqa: ARG001
            url: str,  # noqa: ARG001
            params: dict[str, str] | None = None,  # noqa: ARG001
        ) -> dict[str, Any]:
            raise _make_http_error(404)

        _patch_graph_api_get_json(monkeypatch, fake_get_json)

        for _ in connector._fetch_site_pages(_site_descriptor()):
            pass

    def test_non_404_http_error_still_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-404 HTTP errors (e.g. 403) must still propagate."""
        connector = _setup_connector(monkeypatch)

        def fake_get_json(
            self: SharepointConnector,  # noqa: ARG001
            url: str,  # noqa: ARG001
            params: dict[str, str] | None = None,  # noqa: ARG001
        ) -> dict[str, Any]:
            raise _make_http_error(403)

        _patch_graph_api_get_json(monkeypatch, fake_get_json)

        with pytest.raises(HTTPError):
            list(connector._fetch_site_pages(_site_descriptor()))

    def test_successful_fetch_yields_pages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the API succeeds, pages should be yielded normally."""
        connector = _setup_connector(monkeypatch)

        fake_page = {
            "id": "page-1",
            "title": "Hello World",
            "webUrl": f"{SITE_URL}/SitePages/Hello.aspx",
            "lastModifiedDateTime": "2025-06-01T00:00:00Z",
        }

        def fake_get_json(
            self: SharepointConnector,  # noqa: ARG001
            url: str,  # noqa: ARG001
            params: dict[str, str] | None = None,  # noqa: ARG001
        ) -> dict[str, Any]:
            return {"value": [fake_page]}

        _patch_graph_api_get_json(monkeypatch, fake_get_json)

        pages = list(connector._fetch_site_pages(_site_descriptor()))
        assert len(pages) == 1
        assert pages[0]["id"] == "page-1"

    def test_404_on_second_page_stops_pagination(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the first API page succeeds but a nextLink returns 404,
        already-yielded pages are kept and iteration stops cleanly."""
        connector = _setup_connector(monkeypatch)

        call_count = 0
        first_page = {
            "id": "page-1",
            "title": "First",
            "webUrl": f"{SITE_URL}/SitePages/First.aspx",
            "lastModifiedDateTime": "2025-06-01T00:00:00Z",
        }

        def fake_get_json(
            self: SharepointConnector,  # noqa: ARG001
            url: str,  # noqa: ARG001
            params: dict[str, str] | None = None,  # noqa: ARG001
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "value": [first_page],
                    "@odata.nextLink": "https://graph.microsoft.com/next",
                }
            raise _make_http_error(404)

        _patch_graph_api_get_json(monkeypatch, fake_get_json)

        pages = list(connector._fetch_site_pages(_site_descriptor()))
        assert len(pages) == 1
        assert pages[0]["id"] == "page-1"
