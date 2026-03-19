"""Tests for Canvas connector — client (PR1)."""

from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.connectors.canvas.client import CanvasApiClient
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
    resp.json.return_value = json_data if json_data is not None else []
    resp.headers = {"Link": link_header}
    return resp


# ---------------------------------------------------------------------------
# CanvasApiClient tests
# ---------------------------------------------------------------------------


class TestCanvasApiClient:
    def test_init_rejects_non_https_scheme(self) -> None:
        with pytest.raises(ValueError, match="must use https"):
            CanvasApiClient(
                bearer_token=FAKE_TOKEN,
                canvas_base_url="ftp://myschool.instructure.com",
            )

    def test_init_rejects_missing_host(self) -> None:
        with pytest.raises(ValueError, match="must include a valid host"):
            CanvasApiClient(
                bearer_token=FAKE_TOKEN,
                canvas_base_url="https://",
            )

    def test_init_rejects_non_https(self) -> None:
        with pytest.raises(ValueError, match="must use https"):
            CanvasApiClient(
                bearer_token=FAKE_TOKEN,
                canvas_base_url="http://myschool.instructure.com",
            )

    def test_build_url(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )
        assert client._build_url("courses") == (
            f"{FAKE_BASE_URL}/api/v1/courses"
        )

    def test_build_url_strips_trailing_slash(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=f"{FAKE_BASE_URL}/",
        )
        assert client._build_url("courses") == (
            f"{FAKE_BASE_URL}/api/v1/courses"
        )

    def test_build_headers(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )
        assert client._build_headers() == {
            "Authorization": f"Bearer {FAKE_TOKEN}"
        }

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_get_raises_on_error_status(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(403, {})
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )
        with pytest.raises(OnyxError) as exc_info:
            client.get("courses")
        assert exc_info.value.status_code == 403

    def test_parse_next_link_found(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url="https://canvas.example.com",
        )
        header = '<https://canvas.example.com/api/v1/courses?page=2>; rel="next"'
        assert client._parse_next_link(header) == (
            "https://canvas.example.com/api/v1/courses?page=2"
        )

    def test_parse_next_link_not_found(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url="https://canvas.example.com",
        )
        header = '<https://canvas.example.com/api/v1/courses?page=1>; rel="current"'
        assert client._parse_next_link(header) is None

    def test_parse_next_link_empty(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url="https://canvas.example.com",
        )
        assert client._parse_next_link("") is None

    def test_parse_next_link_multiple_rels(self) -> None:
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url="https://canvas.example.com",
        )
        header = (
            '<https://canvas.example.com/api/v1/courses?page=1>; rel="current", '
            '<https://canvas.example.com/api/v1/courses?page=2>; rel="next"'
        )
        assert client._parse_next_link(header) == (
            "https://canvas.example.com/api/v1/courses?page=2"
        )
