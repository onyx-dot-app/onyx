"""Unit tests for SharepointConnector._fetch_site_pages error handling.

Covers 404 handling (classic sites / no modern pages) and 400
canvasLayout fallback (corrupt pages causing $expand=canvasLayout to
fail on the LIST endpoint), plus propagation of a site lookup that
raises out of `_fetch_site_pages` so the Phase 5 wrap in
`_load_from_checkpoint` can convert it into a ConnectorFailure instead
of crashing the connector run.
"""

import json
from typing import Any

import pytest
from requests import Response
from requests.exceptions import HTTPError

from onyx.connectors.microsoft_utils.graph_errors import MicrosoftGraphError
from onyx.connectors.sharepoint.connector import (
    GRAPH_INVALID_REQUEST_CODE,
    SharepointConnector,
    SiteDescriptor,
)
from tests.unit.onyx.connectors.sharepoint.sharepoint_gateway_fakes import (
    GetJson,
    connector_with_gateway,
    stub_operation,
)

SITE_URL = "https://tenant.sharepoint.com/sites/ClassicSite"
FAKE_SITE_ID = "tenant.sharepoint.com,abc123,def456"
PAGES_COLLECTION = f"https://graph.microsoft.com/v1.0/sites/{FAKE_SITE_ID}/pages"
SITE_PAGES_BASE = f"{PAGES_COLLECTION}/microsoft.graph.sitePage"


def _site_descriptor() -> SiteDescriptor:
    return SiteDescriptor(url=SITE_URL, drive_name=None, folder_path=None)


def _make_http_error(
    status_code: int,
    error_code: str = "itemNotFound",
    message: str = "Item not found",
) -> HTTPError:
    body = {"error": {"code": error_code, "message": message}}
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return HTTPError(response=response)


def _setup_connector(fake_get_json: GetJson) -> SharepointConnector:
    """A connector whose Graph transport answers from ``fake_get_json`` and
    whose site lookup resolves to ``FAKE_SITE_ID``."""
    connector = SharepointConnector(sites=[SITE_URL])
    gateway = connector_with_gateway(connector, get_json=fake_get_json)
    stub_operation(
        gateway,
        "get_site_id",
        lambda *, site_url: FAKE_SITE_ID,  # noqa: ARG005
    )
    return connector


class TestFetchSitePages404:
    def test_404_yields_no_pages(self) -> None:
        """A 404 from the Pages API should result in zero yielded pages."""

        def fake_get_json(
            url: str,  # noqa: ARG001
            params: dict[str, str] | None,  # noqa: ARG001
        ) -> dict[str, Any]:
            raise _make_http_error(404)

        connector = _setup_connector(fake_get_json)

        pages = list(connector._fetch_site_pages(_site_descriptor()))
        assert pages == []

    def test_404_does_not_raise(self) -> None:
        """A 404 must not propagate as an exception."""

        def fake_get_json(
            url: str,  # noqa: ARG001
            params: dict[str, str] | None,  # noqa: ARG001
        ) -> dict[str, Any]:
            raise _make_http_error(404)

        connector = _setup_connector(fake_get_json)

        for _ in connector._fetch_site_pages(_site_descriptor()):
            pass

    def test_non_404_http_error_still_raises(self) -> None:
        """Non-404 HTTP errors (e.g. 403) must still propagate."""

        def fake_get_json(
            url: str,  # noqa: ARG001
            params: dict[str, str] | None,  # noqa: ARG001
        ) -> dict[str, Any]:
            raise _make_http_error(403)

        connector = _setup_connector(fake_get_json)

        with pytest.raises(MicrosoftGraphError):
            list(connector._fetch_site_pages(_site_descriptor()))

    def test_successful_fetch_yields_pages(self) -> None:
        """When the API succeeds, pages should be yielded normally."""
        fake_page = {
            "id": "page-1",
            "title": "Hello World",
            "webUrl": f"{SITE_URL}/SitePages/Hello.aspx",
            "lastModifiedDateTime": "2025-06-01T00:00:00Z",
        }

        def fake_get_json(
            url: str,  # noqa: ARG001
            params: dict[str, str] | None,  # noqa: ARG001
        ) -> dict[str, Any]:
            return {"value": [fake_page]}

        connector = _setup_connector(fake_get_json)

        pages = list(connector._fetch_site_pages(_site_descriptor()))
        assert len(pages) == 1
        assert pages[0]["id"] == "page-1"

    def test_404_on_second_page_stops_pagination(self) -> None:
        """If the first API page succeeds but a nextLink returns 404,
        already-yielded pages are kept and iteration stops cleanly."""
        call_count = 0
        first_page = {
            "id": "page-1",
            "title": "First",
            "webUrl": f"{SITE_URL}/SitePages/First.aspx",
            "lastModifiedDateTime": "2025-06-01T00:00:00Z",
        }

        def fake_get_json(
            url: str,  # noqa: ARG001
            params: dict[str, str] | None,  # noqa: ARG001
        ) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {
                    "value": [first_page],
                    "@odata.nextLink": "https://graph.microsoft.com/next",
                }
            raise _make_http_error(404)

        connector = _setup_connector(fake_get_json)

        pages = list(connector._fetch_site_pages(_site_descriptor()))
        assert len(pages) == 1
        assert pages[0]["id"] == "page-1"


class TestFetchSitePages400Fallback:
    """When $expand=canvasLayout on the LIST endpoint returns 400
    invalidRequest, _fetch_site_pages should fall back to listing
    without expansion, then expanding each page individually."""

    GOOD_PAGE: dict[str, Any] = {
        "id": "good-1",
        "name": "Good.aspx",
        "title": "Good Page",
        "lastModifiedDateTime": "2025-06-01T00:00:00Z",
    }
    BAD_PAGE: dict[str, Any] = {
        "id": "bad-1",
        "name": "Bad.aspx",
        "title": "Bad Page",
        "lastModifiedDateTime": "2025-06-01T00:00:00Z",
    }
    GOOD_PAGE_EXPANDED: dict[str, Any] = {
        **GOOD_PAGE,
        "canvasLayout": {"horizontalSections": []},
    }

    def test_fallback_expands_good_pages_individually(self) -> None:
        """On 400 from the LIST expand, the connector should list without
        expand, then GET each page individually with $expand=canvasLayout."""
        good_page = self.GOOD_PAGE
        bad_page = self.BAD_PAGE
        good_page_expanded = self.GOOD_PAGE_EXPANDED

        def fake_get_json(
            url: str,
            params: dict[str, str] | None,
        ) -> dict[str, Any]:
            if url == SITE_PAGES_BASE and params == {"$expand": "canvasLayout"}:
                raise _make_http_error(
                    400, GRAPH_INVALID_REQUEST_CODE, "Invalid request"
                )
            if url == SITE_PAGES_BASE and params is None:
                return {"value": [good_page, bad_page]}
            expand_params = {"$expand": "canvasLayout"}
            if url == f"{PAGES_COLLECTION}/good-1/microsoft.graph.sitePage":
                assert params == expand_params, f"Expected $expand params, got {params}"
                return good_page_expanded
            if url == f"{PAGES_COLLECTION}/bad-1/microsoft.graph.sitePage":
                assert params == expand_params, f"Expected $expand params, got {params}"
                raise _make_http_error(
                    400, GRAPH_INVALID_REQUEST_CODE, "Invalid request"
                )
            raise AssertionError(f"Unexpected call: {url} {params}")

        connector = _setup_connector(fake_get_json)
        pages = list(connector._fetch_site_pages(_site_descriptor()))

        assert len(pages) == 2
        assert pages[0].get("canvasLayout") is not None
        assert pages[1].get("canvasLayout") is None
        assert pages[1]["id"] == "bad-1"

    def test_mid_pagination_400_does_not_duplicate(self) -> None:
        """If the first paginated batch succeeds but a later nextLink
        returns 400, pages from the first batch must not be re-yielded
        by the fallback."""
        good_page = self.GOOD_PAGE
        good_page_expanded = self.GOOD_PAGE_EXPANDED
        bad_page = self.BAD_PAGE
        second_page = {
            "id": "page-2",
            "name": "Second.aspx",
            "title": "Second Page",
            "lastModifiedDateTime": "2025-06-01T00:00:00Z",
        }
        next_link = "https://graph.microsoft.com/v1.0/next-page-link"

        def fake_get_json(
            url: str,
            params: dict[str, str] | None,
        ) -> dict[str, Any]:
            if url == SITE_PAGES_BASE and params == {"$expand": "canvasLayout"}:
                return {
                    "value": [good_page],
                    "@odata.nextLink": next_link,
                }
            if url == next_link:
                raise _make_http_error(
                    400, GRAPH_INVALID_REQUEST_CODE, "Invalid request"
                )
            if url == SITE_PAGES_BASE and params is None:
                return {"value": [good_page, bad_page, second_page]}
            expand_params = {"$expand": "canvasLayout"}
            if url == f"{PAGES_COLLECTION}/good-1/microsoft.graph.sitePage":
                assert params == expand_params, f"Expected $expand params, got {params}"
                return good_page_expanded
            if url == f"{PAGES_COLLECTION}/bad-1/microsoft.graph.sitePage":
                assert params == expand_params, f"Expected $expand params, got {params}"
                raise _make_http_error(
                    400, GRAPH_INVALID_REQUEST_CODE, "Invalid request"
                )
            if url == f"{PAGES_COLLECTION}/page-2/microsoft.graph.sitePage":
                assert params == expand_params, f"Expected $expand params, got {params}"
                return {**second_page, "canvasLayout": {"horizontalSections": []}}
            raise AssertionError(f"Unexpected call: {url} {params}")

        connector = _setup_connector(fake_get_json)
        pages = list(connector._fetch_site_pages(_site_descriptor()))

        ids = [p["id"] for p in pages]
        assert ids == ["good-1", "bad-1", "page-2"]

    def test_non_invalid_request_400_still_raises(self) -> None:
        """A 400 with a different error code (not invalidRequest) should
        propagate, not trigger the fallback."""

        def fake_get_json(
            url: str,  # noqa: ARG001
            params: dict[str, str] | None,  # noqa: ARG001
        ) -> dict[str, Any]:
            raise _make_http_error(400, "badRequest", "Something else went wrong")

        connector = _setup_connector(fake_get_json)

        with pytest.raises(MicrosoftGraphError):
            list(connector._fetch_site_pages(_site_descriptor()))


class TestFetchSitePagesPropagatesSiteLookup404:
    """When the site lookup itself raises (the site URL does not resolve),
    `_fetch_site_pages` must let the exception propagate so
    the outer Phase 5 wrap can convert it into a ConnectorFailure and
    continue to the next site.
    """

    def _setup_connector_with_failing_site_lookup(
        self, status_code: int
    ) -> SharepointConnector:
        connector = SharepointConnector(sites=[SITE_URL])
        gateway = connector_with_gateway(connector)
        error = MicrosoftGraphError(
            status_code, "itemNotFound", "Requested site could not be found"
        )

        def raising_get_site(*, site_url: str) -> str:  # noqa: ARG001
            raise error

        stub_operation(gateway, "get_site_id", raising_get_site)
        return connector

    def test_404_propagates_so_outer_handler_can_skip(self) -> None:
        connector = self._setup_connector_with_failing_site_lookup(404)

        with pytest.raises(MicrosoftGraphError):
            list(connector._fetch_site_pages(_site_descriptor()))

    def test_401_propagates(self) -> None:
        connector = self._setup_connector_with_failing_site_lookup(401)

        with pytest.raises(MicrosoftGraphError):
            list(connector._fetch_site_pages(_site_descriptor()))
