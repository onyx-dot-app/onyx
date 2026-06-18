"""Unit tests for SharepointConnector._fetch_site_pages error handling.

Covers 404 handling (classic sites / no modern pages) and 400
canvasLayout fallback (corrupt pages causing $expand=canvasLayout to
fail on the LIST endpoint), plus the per-site failure classifier and
propagation of `site.execute_query()` 404s out of `_fetch_site_pages`
so the Phase 5 wrap in `_load_from_checkpoint` can convert them into a
ConnectorFailure instead of crashing the connector run.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from office365.runtime.client_request_exception import ClientRequestException
from requests import Response
from requests.exceptions import HTTPError

from onyx.connectors.sharepoint.connector import _is_per_site_graph_failure
from onyx.connectors.sharepoint.connector import GRAPH_INVALID_REQUEST_CODE
from onyx.connectors.sharepoint.connector import PER_SITE_GRAPH_FAILURE_STATUSES
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.connectors.sharepoint.connector import SiteDescriptor

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


def _make_client_request_exception(
    status_code: int,
    error_code: str = "itemNotFound",
    message: str = "Requested site could not be found",
) -> ClientRequestException:
    body = {"error": {"code": error_code, "message": message}}
    response = Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return ClientRequestException(f"{status_code} Client Error", response=response)


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
    connector._graph_client = type(  # ty: ignore[invalid-assignment]
        "FakeGraphClient", (), {"sites": mock_sites}
    )()

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

    def test_fallback_expands_good_pages_individually(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On 400 from the LIST expand, the connector should list without
        expand, then GET each page individually with $expand=canvasLayout."""
        connector = _setup_connector(monkeypatch)
        good_page = self.GOOD_PAGE
        bad_page = self.BAD_PAGE
        good_page_expanded = self.GOOD_PAGE_EXPANDED

        def fake_get_json(
            self: SharepointConnector,  # noqa: ARG001
            url: str,
            params: dict[str, str] | None = None,
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

        _patch_graph_api_get_json(monkeypatch, fake_get_json)
        pages = list(connector._fetch_site_pages(_site_descriptor()))

        assert len(pages) == 2
        assert pages[0].get("canvasLayout") is not None
        assert pages[1].get("canvasLayout") is None
        assert pages[1]["id"] == "bad-1"

    def test_mid_pagination_400_does_not_duplicate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the first paginated batch succeeds but a later nextLink
        returns 400, pages from the first batch must not be re-yielded
        by the fallback."""
        connector = _setup_connector(monkeypatch)
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
            self: SharepointConnector,  # noqa: ARG001
            url: str,
            params: dict[str, str] | None = None,
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

        _patch_graph_api_get_json(monkeypatch, fake_get_json)
        pages = list(connector._fetch_site_pages(_site_descriptor()))

        ids = [p["id"] for p in pages]
        assert ids == ["good-1", "bad-1", "page-2"]

    def test_non_invalid_request_400_still_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 400 with a different error code (not invalidRequest) should
        propagate, not trigger the fallback."""
        connector = _setup_connector(monkeypatch)

        def fake_get_json(
            self: SharepointConnector,  # noqa: ARG001
            url: str,  # noqa: ARG001
            params: dict[str, str] | None = None,  # noqa: ARG001
        ) -> dict[str, Any]:
            raise _make_http_error(400, "badRequest", "Something else went wrong")

        _patch_graph_api_get_json(monkeypatch, fake_get_json)

        with pytest.raises(HTTPError):
            list(connector._fetch_site_pages(_site_descriptor()))


class TestIsPerSiteGraphFailure:
    """Classifier the Phase 5 wrap in `_load_from_checkpoint` uses to
    decide skip-this-site (yield ConnectorFailure) vs abort-the-run."""

    @pytest.mark.parametrize("status_code", sorted(PER_SITE_GRAPH_FAILURE_STATUSES))
    def test_per_site_statuses_classify_as_per_site(self, status_code: int) -> None:
        exc = _make_client_request_exception(status_code)
        assert _is_per_site_graph_failure(exc) is True

    @pytest.mark.parametrize("status_code", [401, 500, 502, 503, 504])
    def test_tenant_wide_statuses_classify_as_raise(self, status_code: int) -> None:
        exc = _make_client_request_exception(status_code)
        assert _is_per_site_graph_failure(exc) is False

    def test_none_response_classifies_as_raise(self) -> None:
        # Older SDK paths and transport-error wrappers can produce a
        # ClientRequestException with response=None. The retry layer owns
        # those, so we treat None as "not per-site".
        exc = _make_client_request_exception(404)
        exc.response = None  # type: ignore[assignment]
        assert _is_per_site_graph_failure(exc) is False

    def test_itemnotfound_404_is_per_site(self) -> None:
        # Mirrors the production traceback exactly.
        exc = _make_client_request_exception(
            404,
            error_code="itemNotFound",
            message="Requested site could not be found",
        )
        assert exc.code == "itemNotFound"
        assert _is_per_site_graph_failure(exc) is True

    @pytest.mark.parametrize("status_code", sorted(PER_SITE_GRAPH_FAILURE_STATUSES))
    def test_per_site_http_errors_classify_as_per_site(self, status_code: int) -> None:
        exc = _make_http_error(status_code)
        assert _is_per_site_graph_failure(exc) is True

    @pytest.mark.parametrize("status_code", [401, 500, 502, 503, 504])
    def test_tenant_wide_http_errors_classify_as_raise(self, status_code: int) -> None:
        exc = _make_http_error(status_code)
        assert _is_per_site_graph_failure(exc) is False


class TestFetchSitePagesPropagatesSiteLookup404:
    """When `site.execute_query()` itself raises (the site URL no longer
    resolves), `_fetch_site_pages` must let the exception propagate so
    the outer Phase 5 wrap can convert it into a ConnectorFailure and
    continue to the next site.
    """

    def _setup_connector_with_failing_site_lookup(
        self, status_code: int
    ) -> SharepointConnector:
        connector = SharepointConnector(sites=[SITE_URL])
        connector.graph_api_base = "https://graph.microsoft.com/v1.0"

        exc = _make_client_request_exception(status_code)

        def raising_execute_query(self: Any) -> None:  # noqa: ARG001
            raise exc

        fake_site_query = type(
            "Q",
            (),
            {"execute_query": raising_execute_query, "id": None},
        )()
        mock_sites = type(
            "FakeSites",
            (),
            {
                "get_by_url": staticmethod(
                    lambda url: fake_site_query  # noqa: ARG005
                ),
            },
        )()
        connector._graph_client = type(  # ty: ignore[invalid-assignment]
            "FakeGraphClient", (), {"sites": mock_sites}
        )()
        return connector

    def test_404_propagates_so_outer_handler_can_skip(self) -> None:
        connector = self._setup_connector_with_failing_site_lookup(404)

        with pytest.raises(ClientRequestException) as excinfo:
            list(connector._fetch_site_pages(_site_descriptor()))

        # The exception must carry enough info for the outer handler to
        # classify it as per-site rather than tenant-wide.
        assert _is_per_site_graph_failure(excinfo.value) is True

    def test_401_propagates_and_classifies_as_tenant_wide(self) -> None:
        connector = self._setup_connector_with_failing_site_lookup(401)

        with pytest.raises(ClientRequestException) as excinfo:
            list(connector._fetch_site_pages(_site_descriptor()))

        # 401 is tenant-wide — outer handler should re-raise on this one.
        assert _is_per_site_graph_failure(excinfo.value) is False
