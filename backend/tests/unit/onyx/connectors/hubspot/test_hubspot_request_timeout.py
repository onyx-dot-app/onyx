from __future__ import annotations

from unittest.mock import MagicMock

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.connectors.hubspot.connector import HubSpotConnector


def _make_connector() -> HubSpotConnector:
    connector = HubSpotConnector()
    connector._access_token = "token"
    connector._portal_id = "portal"
    return connector


class TestCallHubspotRequestTimeout:
    def test_default_timeout_is_passed_to_sdk(self) -> None:
        connector = _make_connector()
        sdk_fn = MagicMock(return_value="ok")

        result = connector._call_hubspot(sdk_fn, "arg", key="value")

        assert result == "ok"
        sdk_fn.assert_called_once_with(
            "arg", key="value", _request_timeout=REQUEST_TIMEOUT_SECONDS
        )

    def test_explicit_timeout_is_preserved(self) -> None:
        connector = _make_connector()
        sdk_fn = MagicMock(return_value="ok")

        connector._call_hubspot(sdk_fn, _request_timeout=5)

        sdk_fn.assert_called_once_with(_request_timeout=5)

    def test_search_path_passes_timeout_to_sdk(self) -> None:
        connector = _make_connector()
        page = MagicMock()
        page.results = []
        page.paging = None
        search_fn = MagicMock(return_value=page)
        filter_group = connector._build_time_filter_group(
            None, None, "hs_lastmodifieddate"
        )

        list(connector._search_paginated_results(search_fn, ["prop"], filter_group))

        search_fn.assert_called_once()
        assert search_fn.call_args.kwargs["_request_timeout"] == REQUEST_TIMEOUT_SECONDS
