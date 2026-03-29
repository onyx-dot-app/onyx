"""Tests for Canvas connector — client, credentials, conversion."""

from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.connectors.canvas.connector import CanvasConnector
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.error_handling.exceptions import OnyxError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_BASE_URL = "https://myschool.instructure.com"
FAKE_TOKEN = "fake-canvas-token"


def _mock_course(
    course_id: int = 1,
    name: str = "Intro to CS",
    course_code: str = "CS101",
) -> dict[str, Any]:
    return {
        "id": course_id,
        "name": name,
        "course_code": course_code,
        "created_at": "2025-01-01T00:00:00Z",
        "workflow_state": "available",
    }


def _build_connector(base_url: str = FAKE_BASE_URL) -> CanvasConnector:
    """Build a connector with mocked credential validation."""
    with patch("onyx.connectors.canvas.client.rl_requests") as mock_req:
        mock_req.get.return_value = _mock_response(json_data=[_mock_course()])
        connector = CanvasConnector(canvas_base_url=base_url)
        connector.load_credentials({"canvas_access_token": FAKE_TOKEN})
    return connector


def _mock_page(
    page_id: int = 10,
    title: str = "Syllabus",
    updated_at: str = "2025-06-01T12:00:00Z",
) -> dict[str, Any]:
    return {
        "page_id": page_id,
        "url": "syllabus",
        "title": title,
        "body": "<p>Welcome to the course</p>",
        "created_at": "2025-01-15T00:00:00Z",
        "updated_at": updated_at,
    }


def _mock_assignment(
    assignment_id: int = 20,
    name: str = "Homework 1",
    course_id: int = 1,
    updated_at: str = "2025-06-01T12:00:00Z",
) -> dict[str, Any]:
    return {
        "id": assignment_id,
        "name": name,
        "description": "<p>Solve these problems</p>",
        "html_url": f"{FAKE_BASE_URL}/courses/{course_id}/assignments/{assignment_id}",
        "course_id": course_id,
        "created_at": "2025-01-20T00:00:00Z",
        "updated_at": updated_at,
        "due_at": "2025-02-01T23:59:00Z",
    }


def _mock_announcement(
    announcement_id: int = 30,
    title: str = "Class Cancelled",
    course_id: int = 1,
    posted_at: str = "2025-06-01T12:00:00Z",
) -> dict[str, Any]:
    return {
        "id": announcement_id,
        "title": title,
        "message": "<p>No class today</p>",
        "html_url": f"{FAKE_BASE_URL}/courses/{course_id}/discussion_topics/{announcement_id}",
        "posted_at": posted_at,
    }


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
    def setup_method(self) -> None:
        self.client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

    def test_appends_endpoint(self) -> None:
        result = self.client._build_url("courses")
        expected = f"{FAKE_BASE_URL}/api/v1/courses"

        assert result == expected

    def test_strips_leading_slash_from_endpoint(self) -> None:
        result = self.client._build_url("/courses")
        expected = f"{FAKE_BASE_URL}/api/v1/courses"

        assert result == expected


# ---------------------------------------------------------------------------
# CanvasApiClient._build_headers tests
# ---------------------------------------------------------------------------


class TestBuildHeaders:
    def setup_method(self) -> None:
        self.client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

    def test_returns_bearer_auth(self) -> None:
        result = self.client._build_headers()
        expected = {"Authorization": f"Bearer {FAKE_TOKEN}"}

        assert result == expected


# ---------------------------------------------------------------------------
# CanvasApiClient.get tests
# ---------------------------------------------------------------------------


class TestGet:
    def setup_method(self) -> None:
        self.client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_success_returns_json_and_next_url(self, mock_requests: MagicMock) -> None:
        next_link = f"<{FAKE_BASE_URL}/api/v1/courses?page=2>; " 'rel="next"'
        mock_requests.get.return_value = _mock_response(
            json_data=[{"id": 1}], link_header=next_link
        )

        data, next_url = self.client.get("courses")

        expected_data = [{"id": 1}]
        expected_next = f"{FAKE_BASE_URL}/api/v1/courses?page=2"

        assert data == expected_data
        assert next_url == expected_next

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_success_no_next_page(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[{"id": 1}])

        data, next_url = self.client.get("courses")

        assert data == [{"id": 1}]
        assert next_url is None

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_raises_on_error_status(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(403, {})

        with pytest.raises(OnyxError) as exc_info:
            self.client.get("courses")

        assert exc_info.value.status_code == 403

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_raises_on_404(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(404, {})

        with pytest.raises(OnyxError) as exc_info:
            self.client.get("courses")

        assert exc_info.value.status_code == 404

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_raises_on_429(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(429, {})

        with pytest.raises(OnyxError) as exc_info:
            self.client.get("courses")

        assert exc_info.value.status_code == 429

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_skips_params_when_using_full_url(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[])
        full = f"{FAKE_BASE_URL}/api/v1/courses?page=2"

        self.client.get(params={"per_page": "100"}, full_url=full)

        _, kwargs = mock_requests.get.call_args
        assert kwargs["params"] is None

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_error_extracts_message_from_error_dict(
        self, mock_requests: MagicMock
    ) -> None:
        """Shape 1: {"error": {"message": "Not authorized"}}"""
        mock_requests.get.return_value = _mock_response(
            403, {"error": {"message": "Not authorized"}}
        )

        with pytest.raises(OnyxError) as exc_info:
            self.client.get("courses")

        result = exc_info.value.detail
        expected = "Not authorized"

        assert result == expected

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_error_extracts_message_from_error_string(
        self, mock_requests: MagicMock
    ) -> None:
        """Shape 2: {"error": "Invalid access token"}"""
        mock_requests.get.return_value = _mock_response(
            401, {"error": "Invalid access token"}
        )

        with pytest.raises(OnyxError) as exc_info:
            self.client.get("courses")

        result = exc_info.value.detail
        expected = "Invalid access token"

        assert result == expected

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_error_extracts_message_from_errors_list(
        self, mock_requests: MagicMock
    ) -> None:
        """Shape 3: {"errors": [{"message": "Invalid query"}]}"""
        mock_requests.get.return_value = _mock_response(
            400, {"errors": [{"message": "Invalid query"}]}
        )

        with pytest.raises(OnyxError) as exc_info:
            self.client.get("courses")

        result = exc_info.value.detail
        expected = "Invalid query"

        assert result == expected

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_error_dict_takes_priority_over_errors_list(
        self, mock_requests: MagicMock
    ) -> None:
        """When both error shapes are present, error dict wins."""
        mock_requests.get.return_value = _mock_response(
            403, {"error": "Specific error", "errors": [{"message": "Generic"}]}
        )

        with pytest.raises(OnyxError) as exc_info:
            self.client.get("courses")

        result = exc_info.value.detail
        expected = "Specific error"

        assert result == expected

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_error_falls_back_to_reason_when_no_json_message(
        self, mock_requests: MagicMock
    ) -> None:
        """Empty error body falls back to response.reason."""
        mock_requests.get.return_value = _mock_response(500, {})

        with pytest.raises(OnyxError) as exc_info:
            self.client.get("courses")

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

        with pytest.raises(OnyxError, match="Invalid JSON"):
            self.client.get("courses")

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

        with pytest.raises(OnyxError) as exc_info:
            self.client.get("courses")

        result = exc_info.value.detail
        expected = "Internal Server Error"

        assert result == expected


# ---------------------------------------------------------------------------
# CanvasApiClient.paginate tests
# ---------------------------------------------------------------------------


class TestPaginate:
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_single_page(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(
            json_data=[{"id": 1}, {"id": 2}]
        )
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        pages = list(client.paginate("courses"))

        assert len(pages) == 1
        assert pages[0] == [{"id": 1}, {"id": 2}]

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_two_pages(self, mock_requests: MagicMock) -> None:
        next_link = f'<{FAKE_BASE_URL}/api/v1/courses?page=2>; rel="next"'
        page1 = _mock_response(json_data=[{"id": 1}], link_header=next_link)
        page2 = _mock_response(json_data=[{"id": 2}])
        mock_requests.get.side_effect = [page1, page2]
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        pages = list(client.paginate("courses"))

        assert len(pages) == 2
        assert pages[0] == [{"id": 1}]
        assert pages[1] == [{"id": 2}]

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_empty_response(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[])
        client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url=FAKE_BASE_URL,
        )

        pages = list(client.paginate("courses"))

        assert pages == []

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
    def setup_method(self) -> None:
        self.client = CanvasApiClient(
            bearer_token=FAKE_TOKEN,
            canvas_base_url="https://canvas.example.com",
        )

    def test_found(self) -> None:
        header = '<https://canvas.example.com/api/v1/courses?page=2>; rel="next"'

        result = self.client._parse_next_link(header)
        expected = "https://canvas.example.com/api/v1/courses?page=2"

        assert result == expected

    def test_not_found(self) -> None:
        header = '<https://canvas.example.com/api/v1/courses?page=1>; rel="current"'

        result = self.client._parse_next_link(header)

        assert result is None

    def test_empty(self) -> None:
        result = self.client._parse_next_link("")

        assert result is None

    def test_multiple_rels(self) -> None:
        header = (
            '<https://canvas.example.com/api/v1/courses?page=1>; rel="current", '
            '<https://canvas.example.com/api/v1/courses?page=2>; rel="next"'
        )

        result = self.client._parse_next_link(header)
        expected = "https://canvas.example.com/api/v1/courses?page=2"

        assert result == expected

    def test_rejects_host_mismatch(self) -> None:
        header = '<https://evil.example.com/api/v1/courses?page=2>; rel="next"'

        with pytest.raises(OnyxError, match="unexpected host"):
            self.client._parse_next_link(header)

    def test_rejects_non_https_link(self) -> None:
        header = '<http://canvas.example.com/api/v1/courses?page=2>; rel="next"'

        with pytest.raises(OnyxError, match="must use https"):
            self.client._parse_next_link(header)


# ---------------------------------------------------------------------------
# CanvasConnector — credential loading
# ---------------------------------------------------------------------------


class TestLoadCredentials:
    def _assert_load_credentials_raises(
        self,
        status_code: int,
        expected_error: type[Exception],
        mock_requests: MagicMock,
    ) -> None:
        """Helper: assert load_credentials raises expected_error for a given status."""
        mock_requests.get.return_value = _mock_response(status_code, {})
        connector = CanvasConnector(canvas_base_url=FAKE_BASE_URL)
        with pytest.raises(expected_error):
            connector.load_credentials({"canvas_access_token": FAKE_TOKEN})

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_load_credentials_success(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[_mock_course()])
        connector = CanvasConnector(canvas_base_url=FAKE_BASE_URL)

        result = connector.load_credentials({"canvas_access_token": FAKE_TOKEN})

        assert result is None
        assert connector._canvas_client is not None

    def test_canvas_client_raises_without_credentials(self) -> None:
        connector = CanvasConnector(canvas_base_url=FAKE_BASE_URL)

        with pytest.raises(ConnectorMissingCredentialError):
            _ = connector.canvas_client

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_load_credentials_invalid_token(self, mock_requests: MagicMock) -> None:
        self._assert_load_credentials_raises(401, CredentialExpiredError, mock_requests)

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_load_credentials_insufficient_permissions(
        self, mock_requests: MagicMock
    ) -> None:
        self._assert_load_credentials_raises(
            403, InsufficientPermissionsError, mock_requests
        )


# ---------------------------------------------------------------------------
# CanvasConnector — URL normalization
# ---------------------------------------------------------------------------


class TestConnectorUrlNormalization:
    def test_strips_api_v1_suffix(self) -> None:
        connector = _build_connector(base_url=f"{FAKE_BASE_URL}/api/v1")

        result = connector.canvas_base_url
        expected = FAKE_BASE_URL

        assert result == expected

    def test_strips_trailing_slash(self) -> None:
        connector = _build_connector(base_url=f"{FAKE_BASE_URL}/")

        result = connector.canvas_base_url
        expected = FAKE_BASE_URL

        assert result == expected

    def test_no_change_for_clean_url(self) -> None:
        connector = _build_connector(base_url=FAKE_BASE_URL)

        result = connector.canvas_base_url
        expected = FAKE_BASE_URL

        assert result == expected

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_load_credentials_insufficient_permissions(
        self, mock_requests: MagicMock
    ) -> None:
        mock_requests.get.return_value = _mock_response(403, {})
        connector = CanvasConnector(canvas_base_url=FAKE_BASE_URL)

        with pytest.raises(InsufficientPermissionsError):
            connector.load_credentials({"canvas_access_token": FAKE_TOKEN})


# ---------------------------------------------------------------------------
# CanvasConnector — URL normalization
# ---------------------------------------------------------------------------


class TestConnectorUrlNormalization:
    def test_strips_api_v1_suffix(self) -> None:
        connector = _build_connector(base_url=f"{FAKE_BASE_URL}/api/v1")

        result = connector.canvas_base_url
        expected = FAKE_BASE_URL

        assert result == expected

    def test_strips_trailing_slash(self) -> None:
        connector = _build_connector(base_url=f"{FAKE_BASE_URL}/")

        result = connector.canvas_base_url
        expected = FAKE_BASE_URL

        assert result == expected

    def test_no_change_for_clean_url(self) -> None:
        connector = _build_connector(base_url=FAKE_BASE_URL)

        result = connector.canvas_base_url
        expected = FAKE_BASE_URL

        assert result == expected


# ---------------------------------------------------------------------------
# CanvasConnector — document conversion
# ---------------------------------------------------------------------------


class TestDocumentConversion:
    def setup_method(self) -> None:
        self.connector = _build_connector()

    def test_convert_page_to_document(self) -> None:
        from onyx.connectors.canvas.connector import CanvasPage

        page = CanvasPage(
            page_id=10,
            url="syllabus",
            title="Syllabus",
            body="<p>Welcome</p>",
            created_at="2025-01-15T00:00:00Z",
            updated_at="2025-06-01T12:00:00Z",
            course_id=1,
        )

        doc = self.connector._convert_page_to_document(page)

        expected_id = "canvas-page-1-10"
        expected_metadata = {"course_id": "1", "type": "page"}
        expected_updated_at = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

        assert doc.id == expected_id
        assert doc.source == DocumentSource.CANVAS
        assert doc.semantic_identifier == "Syllabus"
        assert doc.metadata == expected_metadata
        assert doc.sections[0].link is not None
        assert f"{FAKE_BASE_URL}/courses/1/pages/syllabus" in doc.sections[0].link
        assert doc.doc_updated_at == expected_updated_at

    def test_convert_page_without_body(self) -> None:
        from onyx.connectors.canvas.connector import CanvasPage

        page = CanvasPage(
            page_id=11,
            url="empty-page",
            title="Empty Page",
            body=None,
            created_at="2025-01-15T00:00:00Z",
            updated_at="2025-06-01T12:00:00Z",
            course_id=1,
        )

        doc = self.connector._convert_page_to_document(page)
        section_text = doc.sections[0].text
        assert section_text is not None

        assert "Empty Page" in section_text
        assert "<p>" not in section_text

    def test_convert_assignment_to_document(self) -> None:
        from onyx.connectors.canvas.connector import CanvasAssignment

        assignment = CanvasAssignment(
            id=20,
            name="Homework 1",
            description="<p>Solve these</p>",
            html_url=f"{FAKE_BASE_URL}/courses/1/assignments/20",
            course_id=1,
            created_at="2025-01-20T00:00:00Z",
            updated_at="2025-06-01T12:00:00Z",
            due_at="2025-02-01T23:59:00Z",
        )

        doc = self.connector._convert_assignment_to_document(assignment)

        expected_id = "canvas-assignment-1-20"
        expected_due_text = "Due: February 01, 2025 23:59 UTC"

        assert doc.id == expected_id
        assert doc.source == DocumentSource.CANVAS
        assert doc.semantic_identifier == "Homework 1"
        assert doc.sections[0].text is not None
        assert expected_due_text in doc.sections[0].text

    def test_convert_assignment_without_description(self) -> None:
        from onyx.connectors.canvas.connector import CanvasAssignment

        assignment = CanvasAssignment(
            id=21,
            name="Quiz 1",
            description=None,
            html_url=f"{FAKE_BASE_URL}/courses/1/assignments/21",
            course_id=1,
            created_at="2025-01-20T00:00:00Z",
            updated_at="2025-06-01T12:00:00Z",
            due_at=None,
        )

        doc = self.connector._convert_assignment_to_document(assignment)
        section_text = doc.sections[0].text
        assert section_text is not None

        assert "Quiz 1" in section_text
        assert "Due:" not in section_text

    def test_convert_announcement_to_document(self) -> None:
        from onyx.connectors.canvas.connector import CanvasAnnouncement

        announcement = CanvasAnnouncement(
            id=30,
            title="Class Cancelled",
            message="<p>No class today</p>",
            html_url=f"{FAKE_BASE_URL}/courses/1/discussion_topics/30",
            posted_at="2025-06-01T12:00:00Z",
            course_id=1,
        )

        doc = self.connector._convert_announcement_to_document(announcement)

        expected_id = "canvas-announcement-1-30"
        expected_updated_at = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

        assert doc.id == expected_id
        assert doc.source == DocumentSource.CANVAS
        assert doc.semantic_identifier == "Class Cancelled"
        assert doc.doc_updated_at == expected_updated_at

    def test_convert_announcement_without_posted_at(self) -> None:
        from onyx.connectors.canvas.connector import CanvasAnnouncement

        announcement = CanvasAnnouncement(
            id=31,
            title="TBD Announcement",
            message=None,
            html_url=f"{FAKE_BASE_URL}/courses/1/discussion_topics/31",
            posted_at=None,
            course_id=1,
        )

        doc = self.connector._convert_announcement_to_document(announcement)

        assert doc.doc_updated_at is None


# ---------------------------------------------------------------------------
# CanvasConnector — validate_connector_settings
# ---------------------------------------------------------------------------


class TestValidateConnectorSettings:
    def _assert_validate_raises(
        self,
        status_code: int,
        expected_error: type[Exception],
        mock_requests: MagicMock,
    ) -> None:
        """Helper: assert validate_connector_settings raises expected_error."""
        success_resp = _mock_response(json_data=[_mock_course()])
        fail_resp = _mock_response(status_code, {})
        mock_requests.get.side_effect = [success_resp, fail_resp]
        connector = CanvasConnector(canvas_base_url=FAKE_BASE_URL)
        connector.load_credentials({"canvas_access_token": FAKE_TOKEN})
        with pytest.raises(expected_error):
            connector.validate_connector_settings()

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_validate_success(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[_mock_course()])
        connector = _build_connector()

        connector.validate_connector_settings()  # should not raise

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_validate_expired_credential(self, mock_requests: MagicMock) -> None:
        self._assert_validate_raises(401, CredentialExpiredError, mock_requests)

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_validate_insufficient_permissions(self, mock_requests: MagicMock) -> None:
        self._assert_validate_raises(403, InsufficientPermissionsError, mock_requests)

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_validate_insufficient_permissions(
        self, mock_requests: MagicMock
    ) -> None:
        success_resp = _mock_response(json_data=[_mock_course()])
        fail_resp = _mock_response(403, {})
        mock_requests.get.side_effect = [success_resp, fail_resp]
        connector = CanvasConnector(canvas_base_url=FAKE_BASE_URL)
        connector.load_credentials({"canvas_access_token": FAKE_TOKEN})

        with pytest.raises(InsufficientPermissionsError):
            connector.validate_connector_settings()

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_validate_rate_limited(self, mock_requests: MagicMock) -> None:
        self._assert_validate_raises(429, ConnectorValidationError, mock_requests)

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_validate_unexpected_error(self, mock_requests: MagicMock) -> None:
        self._assert_validate_raises(500, UnexpectedValidationError, mock_requests)


# ---------------------------------------------------------------------------
# _list_* pagination tests
# ---------------------------------------------------------------------------


class TestListCourses:
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_single_page(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(
            json_data=[_mock_course(1), _mock_course(2, "CS201", "Data Structures")]
        )
        connector = _build_connector()

        result = connector._list_courses()

        assert len(result) == 2
        assert result[0].id == 1
        assert result[1].id == 2

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_empty_response(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[])
        connector = _build_connector()

        result = connector._list_courses()

        assert result == []


class TestListPages:
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_single_page(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(
            json_data=[_mock_page(10), _mock_page(11, "Notes")]
        )
        connector = _build_connector()

        result = connector._list_pages(course_id=1)

        assert len(result) == 2
        assert result[0].page_id == 10
        assert result[1].page_id == 11

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_empty_response(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[])
        connector = _build_connector()

        result = connector._list_pages(course_id=1)

        assert result == []


class TestListAssignments:
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_single_page(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(
            json_data=[_mock_assignment(20), _mock_assignment(21, "Quiz 1")]
        )
        connector = _build_connector()

        result = connector._list_assignments(course_id=1)

        assert len(result) == 2
        assert result[0].id == 20
        assert result[1].id == 21

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_empty_response(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[])
        connector = _build_connector()

        result = connector._list_assignments(course_id=1)

        assert result == []


class TestListAnnouncements:
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_single_page(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(
            json_data=[_mock_announcement(30), _mock_announcement(31, "Update")]
        )
        connector = _build_connector()

        result = connector._list_announcements(course_id=1)

        assert len(result) == 2
        assert result[0].id == 30
        assert result[1].id == 31

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_empty_response(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[])
        connector = _build_connector()

        result = connector._list_announcements(course_id=1)

        assert result == []
class TestCheckpoint:
    def test_build_dummy_checkpoint(self) -> None:
        connector = _build_connector()

        cp = connector.build_dummy_checkpoint()

        assert cp.has_more is True
        assert cp.course_ids == []
        assert cp.current_course_index == 0
        assert cp.stage == "pages"

    def test_validate_checkpoint_json(self) -> None:
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True,
            course_ids=[1, 2],
            current_course_index=1,
            stage="assignments",
        )

        json_str = cp.model_dump_json()
        restored = connector.validate_checkpoint_json(json_str)

        assert restored.course_ids == [1, 2]
        assert restored.current_course_index == 1
        assert restored.stage == "assignments"
        assert restored.has_more is True


# ---------------------------------------------------------------------------
# load_from_checkpoint tests
# ---------------------------------------------------------------------------


class TestLoadFromCheckpoint:
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_first_call_materializes_courses(self, mock_requests: MagicMock) -> None:
        """First call should populate course_ids and yield no documents."""
        mock_requests.get.side_effect = _make_url_dispatcher(
            courses=[_mock_course(1), _mock_course(2, "Data Structures", "CS201")]
        )
        connector = _build_connector()
        cp = connector.build_dummy_checkpoint()

        items, new_cp = _run_checkpoint(connector, cp)

        assert items == []
        assert new_cp.course_ids == [1, 2]
        assert new_cp.current_course_index == 0
        assert new_cp.stage == "pages"
        assert new_cp.has_more is True

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_processes_pages_stage(self, mock_requests: MagicMock) -> None:
        """Pages stage yields page documents within the time window."""
        mock_requests.get.side_effect = _make_url_dispatcher(
            pages=[_mock_page(10, "Syllabus", "2025-06-15T12:00:00Z")]
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True,
            course_ids=[1],
            current_course_index=0,
            stage="pages",
        )
        start = datetime(2025, 6, 1, 0, 0, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, 0, 0, tzinfo=timezone.utc).timestamp()

        items, new_cp = _run_checkpoint(connector, cp, start, end)

        expected_count = 1
        expected_id = "canvas-page-1-10"
        expected_next_stage = "assignments"

        assert len(items) == expected_count
        assert isinstance(items[0], Document)
        assert items[0].id == expected_id
        assert new_cp.stage == expected_next_stage

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_advances_through_all_stages(self, mock_requests: MagicMock) -> None:
        """Calling checkpoint 3 times advances pages -> assignments -> announcements -> next course."""
        page = _mock_page(10, updated_at="2025-06-15T12:00:00Z")
        assignment = _mock_assignment(20, updated_at="2025-06-15T12:00:00Z")
        announcement = _mock_announcement(30, posted_at="2025-06-15T12:00:00Z")
        mock_requests.get.side_effect = _make_url_dispatcher(
            pages=[page], assignments=[assignment], announcements=[announcement]
        )
        connector = _build_connector()
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )

        # Stage 1: pages
        items1, cp = _run_checkpoint(connector, cp, start, end)

        assert cp.stage == "assignments"
        assert len(items1) == 1

        # Stage 2: assignments
        mock_requests.get.side_effect = _make_url_dispatcher(
            assignments=[assignment]
        )

        items2, cp = _run_checkpoint(connector, cp, start, end)

        assert cp.stage == "announcements"
        assert len(items2) == 1

        # Stage 3: announcements -> advances course index
        mock_requests.get.side_effect = _make_url_dispatcher(
            announcements=[announcement]
        )

        items3, cp = _run_checkpoint(connector, cp, start, end)

        assert cp.current_course_index == 1
        assert cp.stage == "pages"
        assert cp.has_more is False

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_filters_by_time_window(self, mock_requests: MagicMock) -> None:
        """Only documents within (start, end] are yielded."""
        old_page = _mock_page(10, updated_at="2025-01-01T00:00:00Z")
        new_page = _mock_page(11, title="New Page", updated_at="2025-06-15T12:00:00Z")
        mock_requests.get.side_effect = _make_url_dispatcher(
            pages=[old_page, new_page]
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        items, _ = _run_checkpoint(connector, cp, start, end)

        expected_count = 1
        expected_id = "canvas-page-1-11"

        assert len(items) == expected_count
        assert items[0].id == expected_id

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_skips_announcement_without_posted_at(self, mock_requests: MagicMock) -> None:
        announcement = _mock_announcement()
        announcement["posted_at"] = None
        mock_requests.get.side_effect = _make_url_dispatcher(
            announcements=[announcement]
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="announcements"
        )

        items, _ = _run_checkpoint(connector, cp)

        assert len(items) == 0

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_stage_failure_does_not_advance(self, mock_requests: MagicMock) -> None:
        """If listing fails, stage stays the same for retry."""
        mock_requests.get.side_effect = _make_url_dispatcher(page_error=True)
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )

        items, new_cp = _run_checkpoint(connector, cp)

        assert items == []
        assert new_cp.stage == "pages"
        assert new_cp.current_course_index == 0

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_per_document_conversion_failure_yields_connector_failure(
        self, mock_requests: MagicMock
    ) -> None:
        """Bad data for one page yields ConnectorFailure, doesn't stop processing."""
        bad_page = {"page_id": 10, "url": "test", "title": "Test", "body": None,
                     "created_at": "2025-06-15T12:00:00Z", "updated_at": "bad-date"}
        mock_requests.get.side_effect = _make_url_dispatcher(pages=[bad_page])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )

        items, new_cp = _run_checkpoint(connector, cp)

        assert len(items) == 1
        assert isinstance(items[0], ConnectorFailure)
        assert new_cp.stage == "assignments"

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_all_courses_done_sets_has_more_false(self, mock_requests: MagicMock) -> None:
        mock_requests.get.side_effect = _make_url_dispatcher()
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=1
        )

        items, new_cp = _run_checkpoint(connector, cp)

        assert items == []
        assert new_cp.has_more is False

    def test_invalid_stage_raises_value_error(self) -> None:
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )
        cp.stage = "invalid"  # type: ignore[assignment]

        with pytest.raises(ValueError, match="Invalid checkpoint stage"):
            _run_checkpoint(connector, cp)


# ---------------------------------------------------------------------------
# load_from_checkpoint_with_perm_sync tests
# ---------------------------------------------------------------------------


class TestLoadFromCheckpointWithPermSync:
    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_documents_have_external_access(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
        """load_from_checkpoint_with_perm_sync attaches ExternalAccess to documents."""
        expected_access = ExternalAccess(
            external_user_emails={"student@school.edu"},
            external_user_group_ids=set(),
            is_public=False,
        )
        mock_perms.return_value = expected_access
        mock_requests.get.side_effect = _make_url_dispatcher(
            pages=[_mock_page(10, "Syllabus", "2025-06-15T12:00:00Z")]
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        gen = connector.load_from_checkpoint_with_perm_sync(start, end, cp)
        items: list[Document | ConnectorFailure] = []
        try:
            while True:
                items.append(next(gen))
        except StopIteration as e:
            new_cp = e.value

        assert len(items) == 1
        assert isinstance(items[0], Document)
        assert items[0].external_access == expected_access
        assert new_cp.stage == "assignments"
        mock_perms.assert_called_once()
