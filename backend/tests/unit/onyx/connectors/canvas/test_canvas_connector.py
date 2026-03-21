"""Tests for Canvas connector — client (PR1)."""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.canvas.client import CanvasApiClient
from onyx.connectors.canvas.client import _error_code_for_status
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_BASE_URL = "https://myschool.instructure.com"
FAKE_TOKEN = "fake-canvas-token"


def _mock_response(
    status_code: int = 200,
    json_data: Any = None,
    link_header: str = "",
) -> MagicMock:
    """Create a mock HTTP response with status, json, and Link header."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.reason = "OK" if status_code < 300 else "Error"
    resp.json.return_value = json_data if json_data else []
    resp.headers = {"Link": link_header}
    return resp


# ---------------------------------------------------------------------------
# _error_code_for_status tests
# ---------------------------------------------------------------------------


class TestErrorCodeForStatus:
    def test_401_maps_to_credential_expired(self) -> None:
        result = _error_code_for_status(401)

        assert result == OnyxErrorCode.CREDENTIAL_EXPIRED

    def test_403_maps_to_insufficient_permissions(self) -> None:
        result = _error_code_for_status(403)

        assert result == OnyxErrorCode.INSUFFICIENT_PERMISSIONS

    def test_404_maps_to_bad_gateway(self) -> None:
        result = _error_code_for_status(404)

        assert result == OnyxErrorCode.BAD_GATEWAY

    def test_429_maps_to_rate_limited(self) -> None:
        result = _error_code_for_status(429)

        assert result == OnyxErrorCode.RATE_LIMITED

    def test_500_maps_to_bad_gateway(self) -> None:
        result = _error_code_for_status(500)

        assert result == OnyxErrorCode.BAD_GATEWAY

    def test_503_maps_to_bad_gateway(self) -> None:
        result = _error_code_for_status(503)

        assert result == OnyxErrorCode.BAD_GATEWAY

    def test_unknown_4xx_maps_to_connector_validation_failed(self) -> None:
        result = _error_code_for_status(418)

        assert result == OnyxErrorCode.CONNECTOR_VALIDATION_FAILED


# ---------------------------------------------------------------------------
# CanvasApiClient.__init__ tests
# ---------------------------------------------------------------------------


class TestCanvasApiClientInit:
    def test_success(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        expected_base_url = f"{FAKE_BASE_URL}/api/v1"
        expected_host = "myschool.instructure.com"

        assert client.base_url == expected_base_url
        assert client._expected_host == expected_host

    def test_normalizes_trailing_slash(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=f"{FAKE_BASE_URL}/",
        )

        expected_base_url = f"{FAKE_BASE_URL}/api/v1"

        assert client.base_url == expected_base_url

    def test_normalizes_existing_api_v1(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=f"{FAKE_BASE_URL}/api/v1",
        )

        expected_base_url = f"{FAKE_BASE_URL}/api/v1"

        assert client.base_url == expected_base_url

    def test_rejects_non_https_scheme(self) -> None:
        with pytest.raises(ValueError, match="must use https"):
            CanvasApiClient(
                bearer_token=FAKE_TOKEN,
                canvas_base_url="ftp://myschool.instructure.com",
            )

    def test_rejects_http(self) -> None:
        with pytest.raises(ValueError, match="must use https"):
            CanvasApiClient(
                bearer_token=FAKE_TOKEN,
                canvas_base_url="http://myschool.instructure.com",
            )

    def test_rejects_missing_host(self) -> None:
        with pytest.raises(ValueError, match="must include a valid host"):
            CanvasApiClient(
                bearer_token=FAKE_TOKEN,
                canvas_base_url="https://",
            )


# ---------------------------------------------------------------------------
# CanvasApiClient._build_url tests
# ---------------------------------------------------------------------------


class TestBuildUrl:
    def test_appends_endpoint(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        result = client._build_url("courses")
        expected = f"{FAKE_BASE_URL}/api/v1/courses"

        assert result == expected

    def test_strips_leading_slash_from_endpoint(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        result = client._build_url("/courses")
        expected = f"{FAKE_BASE_URL}/api/v1/courses"

        assert result == expected


# ---------------------------------------------------------------------------
# CanvasApiClient._build_headers tests
# ---------------------------------------------------------------------------


class TestBuildHeaders:
    def test_returns_bearer_auth(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        result = client._build_headers()
        expected = {"Authorization": f"Bearer {FAKE_TOKEN}"}

        assert result == expected


# ---------------------------------------------------------------------------
# CanvasApiClient.get tests
# ---------------------------------------------------------------------------


class TestGet:
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_success_returns_json_and_next_url(self, mock_requests: MagicMock) -> None:
        next_link = f"<{FAKE_BASE_URL}/api/v1/courses?page=2>; " 'rel="next"'
        mock_requests.get.return_value = _mock_response(
            json_data=[{"id": 1}], link_header=next_link
        )
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        data, next_url = client.get("courses")

        expected_data = [{"id": 1}]
        expected_next = f"{FAKE_BASE_URL}/api/v1/courses?page=2"

        assert data == expected_data
        assert next_url == expected_next

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_success_no_next_page(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[{"id": 1}])
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        data, next_url = client.get("courses")

        assert data == [{"id": 1}]
        assert next_url is None

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_raises_on_error_status(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(403, {})
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        with pytest.raises(OnyxError) as exc_info:
            client.get("courses")

        assert exc_info.value.status_code == 403

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_skips_params_when_using_full_url(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[])
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )
        full = f"{FAKE_BASE_URL}/api/v1/courses?page=2"

        client.get(params={"per_page": "100"}, full_url=full)

        _, kwargs = mock_requests.get.call_args
        assert kwargs["params"] is None

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_error_extracts_message_from_error_dict(self, mock_requests: MagicMock) -> None:
        """Shape 1: {"error": {"message": "Not authorized"}}"""
        mock_requests.get.return_value = _mock_response(
            403, {"error": {"message": "Not authorized"}}
        )
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        with pytest.raises(OnyxError) as exc_info:
            client.get("courses")

        result = exc_info.value.detail
        expected = "Not authorized"

        assert result == expected

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_error_extracts_message_from_error_string(self, mock_requests: MagicMock) -> None:
        """Shape 2: {"error": "Invalid access token"}"""
        mock_requests.get.return_value = _mock_response(
            401, {"error": "Invalid access token"}
        )
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        with pytest.raises(OnyxError) as exc_info:
            client.get("courses")

        result = exc_info.value.detail
        expected = "Invalid access token"

        assert result == expected

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_error_extracts_message_from_errors_list(self, mock_requests: MagicMock) -> None:
        """Shape 3: {"errors": [{"message": "Invalid query"}]}"""
        mock_requests.get.return_value = _mock_response(
            400, {"errors": [{"message": "Invalid query"}]}
        )
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        with pytest.raises(OnyxError) as exc_info:
            client.get("courses")

        result = exc_info.value.detail
        expected = "Invalid query"

        assert result == expected

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_error_dict_takes_priority_over_errors_list(self, mock_requests: MagicMock) -> None:
        """When both error shapes are present, error dict wins."""
        mock_requests.get.return_value = _mock_response(
            403, {"error": "Specific error", "errors": [{"message": "Generic"}]}
        )
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        with pytest.raises(OnyxError) as exc_info:
            client.get("courses")

        result = exc_info.value.detail
        expected = "Specific error"

        assert result == expected

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_error_falls_back_to_reason_when_no_json_message(
        self, mock_requests: MagicMock
    ) -> None:
        """Empty error body falls back to response.reason."""
        mock_requests.get.return_value = _mock_response(500, {})
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        with pytest.raises(OnyxError) as exc_info:
            client.get("courses")

        result = exc_info.value.detail
        expected = "Error"  # from _mock_response's reason for >= 300

        assert result == expected

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_invalid_json_on_success_raises(self, mock_requests: MagicMock) -> None:
        """Invalid JSON on a 2xx response raises OnyxError."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("No JSON")
        resp.headers = {"Link": ""}
        mock_requests.get.return_value = resp
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        with pytest.raises(OnyxError, match="Invalid JSON"):
            client.get("courses")

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_invalid_json_on_error_falls_back_to_reason(
        self, mock_requests: MagicMock
    ) -> None:
        """Invalid JSON on a 4xx response falls back to response.reason."""
        resp = MagicMock()
        resp.status_code = 500
        resp.reason = "Internal Server Error"
        resp.json.side_effect = ValueError("No JSON")
        resp.headers = {"Link": ""}
        mock_requests.get.return_value = resp
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        with pytest.raises(OnyxError) as exc_info:
            client.get("courses")

        result = exc_info.value.detail
        expected = "Internal Server Error"

        assert result == expected


# ---------------------------------------------------------------------------
# CanvasApiClient._parse_next_link tests
# ---------------------------------------------------------------------------


class TestParseNextLink:
    def _make_client(self, base: str = "https://canvas.example.com") -> CanvasApiClient:
        return CanvasApiClient(bearer_token=FAKE_TOKEN, canvas_base_url=base)

    def test_found(self) -> None:
        client = self._make_client()
        header = '<https://canvas.example.com/api/v1/courses?page=2>; rel="next"'

        result = client._parse_next_link(header)
        expected = "https://canvas.example.com/api/v1/courses?page=2"

        assert result == expected

    def test_not_found(self) -> None:
        client = self._make_client()
        header = '<https://canvas.example.com/api/v1/courses?page=1>; rel="current"'

        result = client._parse_next_link(header)

        assert result is None

    def test_empty(self) -> None:
        client = self._make_client()

        result = client._parse_next_link("")

        assert result is None

    def test_multiple_rels(self) -> None:
        client = self._make_client()
        header = (
            '<https://canvas.example.com/api/v1/courses?page=1>; rel="current", '
            '<https://canvas.example.com/api/v1/courses?page=2>; rel="next"'
        )

        result = client._parse_next_link(header)
        expected = "https://canvas.example.com/api/v1/courses?page=2"

        assert result == expected

    def test_rejects_host_mismatch(self) -> None:
        client = self._make_client()
        header = '<https://evil.example.com/api/v1/courses?page=2>; rel="next"'

        with pytest.raises(OnyxError, match="unexpected host"):
            client._parse_next_link(header)

    def test_rejects_non_https_link(self) -> None:
        client = self._make_client()
        header = '<http://canvas.example.com/api/v1/courses?page=2>; rel="next"'

        with pytest.raises(OnyxError, match="must use https"):
            client._parse_next_link(header)
