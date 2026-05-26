"""Tests for Canvas connector — client, credentials, conversion."""

from datetime import datetime
from datetime import timezone
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.canvas.client import CanvasApiClient
from onyx.connectors.canvas.connector import CanvasConnector
from onyx.connectors.canvas.connector import CanvasConnectorCheckpoint
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import HierarchyNode
from onyx.connectors.models import SlimDocument
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


def _build_connector(
    base_url: str = FAKE_BASE_URL,
    credentials: dict[str, Any] | None = None,
) -> CanvasConnector:
    """Build a connector with mocked credential validation."""
    with patch("onyx.connectors.canvas.client.rl_requests") as mock_req:
        mock_req.get.return_value = _mock_response(json_data=[_mock_course()])
        connector = CanvasConnector(canvas_base_url=base_url)
        connector.load_credentials(
            {"canvas_access_token": FAKE_TOKEN, **(credentials or {})}
        )
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


def _mock_file(
    file_id: int = 40,
    display_name: str = "slides_week1.pdf",
    updated_at: str = "2025-06-01T12:00:00Z",
) -> dict[str, Any]:
    return {
        "id": file_id,
        "display_name": display_name,
        "filename": display_name,
        "url": f"https://files.instructure.com/{file_id}/download",
        "content-type": "application/pdf",
        "size": 1024,
        "created_at": "2025-01-15T00:00:00Z",
        "updated_at": updated_at,
    }


def _mock_quiz(
    quiz_id: int = 50,
    title: str = "Quiz 1",
    course_id: int = 1,
    updated_at: str = "2025-06-01T12:00:00Z",
) -> dict[str, Any]:
    return {
        "id": quiz_id,
        "title": title,
        "description": "<p>Test your knowledge</p>",
        "html_url": f"{FAKE_BASE_URL}/courses/{course_id}/quizzes/{quiz_id}",
        "quiz_type": "assignment",
        "question_count": 10,
        "published": True,
        "created_at": "2025-01-20T00:00:00Z",
        "updated_at": updated_at,
    }


def _mock_discussion(
    discussion_id: int = 60,
    title: str = "Week 1 Discussion",
    course_id: int = 1,
    posted_at: str = "2025-06-01T12:00:00Z",
) -> dict[str, Any]:
    return {
        "id": discussion_id,
        "title": title,
        "message": "<p>Discuss the readings</p>",
        "html_url": f"{FAKE_BASE_URL}/courses/{course_id}/discussion_topics/{discussion_id}",
        "posted_at": posted_at,
        "published": True,
    }


def _mock_module(
    module_id: int = 70,
    name: str = "Module 1: Variables",
) -> dict[str, Any]:
    return {
        "id": module_id,
        "name": name,
        "position": 1,
        "published": True,
    }


def _make_url_dispatcher(
    courses: list[dict[str, Any]] | None = None,
    pages: list[dict[str, Any]] | None = None,
    assignments: list[dict[str, Any]] | None = None,
    announcements: list[dict[str, Any]] | None = None,
    files: list[dict[str, Any]] | None = None,
    modules: list[dict[str, Any]] | None = None,
    module_items: list[dict[str, Any]] | None = None,
    quizzes: list[dict[str, Any]] | None = None,
    discussions: list[dict[str, Any]] | None = None,
    syllabus_body: str | None = None,
    page_error: bool = False,
) -> Any:
    """Return a side_effect function that dispatches by URL path.

    When the mock ``rl_requests.get`` is called, this inspects the URL to
    decide which data to return.  This mirrors how the real connector calls
    different Canvas API endpoints during a single checkpoint iteration.
    """
    if courses is None:
        courses = [_mock_course(1)]
    if pages is None:
        pages = []
    if assignments is None:
        assignments = []
    if announcements is None:
        announcements = []
    if files is None:
        files = []
    if modules is None:
        modules = []
    if module_items is None:
        module_items = []
    if quizzes is None:
        quizzes = []
    if discussions is None:
        discussions = []

    def _dispatch(url: str, **kwargs: Any) -> MagicMock:
        params = kwargs.get("params") or {}

        if page_error and "/pages" in url:
            return _mock_response(500, {"error": "Internal Server Error"})

        # Syllabus: check params before generic /courses match
        if "include[]" in params and params["include[]"] == "syllabus_body":
            return _mock_response(
                json_data={"syllabus_body": syllabus_body} if syllabus_body else {}
            )
        if "/modules/" in url and "/items" in url:
            return _mock_response(json_data=module_items)
        elif "/modules" in url:
            return _mock_response(json_data=modules)
        elif "/pages" in url:
            return _mock_response(json_data=pages)
        elif "/assignments" in url:
            return _mock_response(json_data=assignments)
        elif "announcements" in url:
            return _mock_response(json_data=announcements)
        elif "/files" in url:
            return _mock_response(json_data=files)
        elif "/quizzes" in url:
            return _mock_response(json_data=quizzes)
        elif "/discussion_topics" in url:
            return _mock_response(json_data=discussions)
        elif "/courses" in url:
            return _mock_response(json_data=courses)
        return _mock_response(json_data=[])

    return _dispatch


def _run_checkpoint(
    connector: CanvasConnector,
    checkpoint: CanvasConnectorCheckpoint,
    start: float = 0,
    end: float = datetime(2099, 1, 1, tzinfo=timezone.utc).timestamp(),
    include_hierarchy: bool = False,
) -> tuple[
    list[Document | ConnectorFailure | HierarchyNode], CanvasConnectorCheckpoint
]:
    """Drive one load_from_checkpoint call, collecting yielded items.

    Filters HierarchyNode out by default — most tests assert on document
    counts. Pass include_hierarchy=True to retain them.
    """
    gen = connector.load_from_checkpoint(start, end, checkpoint)
    items: list[Document | ConnectorFailure | HierarchyNode] = []
    try:
        while True:
            item = next(gen)
            if not include_hierarchy and isinstance(item, HierarchyNode):
                continue
            items.append(item)
    except StopIteration as e:
        new_cp: CanvasConnectorCheckpoint = e.value
    return items, new_cp


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
    def test_error_extracts_message_from_error_dict(
        self, mock_requests: MagicMock
    ) -> None:
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
    def test_error_extracts_message_from_error_string(
        self, mock_requests: MagicMock
    ) -> None:
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
    def test_error_extracts_message_from_errors_list(
        self, mock_requests: MagicMock
    ) -> None:
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
    def test_error_dict_takes_priority_over_errors_list(
        self, mock_requests: MagicMock
    ) -> None:
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
        """Calling checkpoint through all stages advances to next course."""
        page = _mock_page(10, updated_at="2025-06-15T12:00:00Z")
        assignment = _mock_assignment(20, updated_at="2025-06-15T12:00:00Z")
        announcement = _mock_announcement(30, posted_at="2025-06-15T12:00:00Z")
        file = _mock_file(40, updated_at="2025-06-15T12:00:00Z")
        quiz = _mock_quiz(50, updated_at="2025-06-15T12:00:00Z")
        discussion = _mock_discussion(60, posted_at="2025-06-15T12:00:00Z")
        dispatcher = _make_url_dispatcher(
            pages=[page],
            assignments=[assignment],
            announcements=[announcement],
            files=[file],
            quizzes=[quiz],
            discussions=[discussion],
        )
        mock_requests.get.side_effect = dispatcher
        connector = _build_connector()
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )

        # Stage 1: pages -> assignments
        items1, cp = _run_checkpoint(connector, cp, start, end)
        assert cp.stage == "assignments"
        assert len(items1) == 1

        # Stage 2: assignments -> announcements
        mock_requests.get.side_effect = dispatcher
        items2, cp = _run_checkpoint(connector, cp, start, end)
        assert cp.stage == "announcements"
        assert len(items2) == 1

        # Stage 3: announcements -> files
        mock_requests.get.side_effect = dispatcher
        items3, cp = _run_checkpoint(connector, cp, start, end)
        assert cp.stage == "files"

        # Stage 4: files -> modules
        mock_requests.get.side_effect = dispatcher
        items4, cp = _run_checkpoint(connector, cp, start, end)
        assert cp.stage == "modules"

        # Stage 5: modules -> quizzes (modules is a pass-through stage)
        mock_requests.get.side_effect = dispatcher
        items5, cp = _run_checkpoint(connector, cp, start, end)
        assert cp.stage == "quizzes"

        # Stage 6: quizzes -> discussions
        mock_requests.get.side_effect = dispatcher
        items6, cp = _run_checkpoint(connector, cp, start, end)
        assert cp.stage == "discussions"

        # Stage 7: discussions -> syllabus
        mock_requests.get.side_effect = dispatcher
        items7, cp = _run_checkpoint(connector, cp, start, end)
        assert cp.stage == "syllabus"

        # Stage 8: syllabus -> advance course
        mock_requests.get.side_effect = dispatcher
        items8, cp = _run_checkpoint(connector, cp, start, end)
        assert cp.current_course_index == 1
        assert cp.stage == "pages"
        assert cp.has_more is False

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_filters_by_time_window(self, mock_requests: MagicMock) -> None:
        """Only documents within (start, end] are yielded."""
        old_page = _mock_page(10, updated_at="2025-01-01T00:00:00Z")
        new_page = _mock_page(11, title="New Page", updated_at="2025-06-15T12:00:00Z")
        mock_requests.get.side_effect = _make_url_dispatcher(pages=[old_page, new_page])
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
    def test_skips_announcement_without_posted_at(
        self, mock_requests: MagicMock
    ) -> None:
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
        bad_page = {
            "page_id": 10,
            "url": "test",
            "title": "Test",
            "body": None,
            "created_at": "2025-06-15T12:00:00Z",
            "updated_at": "bad-date",
        }
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
    def test_all_courses_done_sets_has_more_false(
        self, mock_requests: MagicMock
    ) -> None:
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
        items: list[Document | ConnectorFailure | HierarchyNode] = []
        try:
            while True:
                items.append(next(gen))
        except StopIteration as e:
            new_cp = e.value

        docs = [i for i in items if isinstance(i, Document)]
        assert len(docs) == 1
        assert docs[0].external_access == expected_access
        assert new_cp.stage == "assignments"
        # Permissions are looked up once per course and cached. The hierarchy
        # emission path also consults them, so we just assert it was called.
        mock_perms.assert_called()

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_per_document_conversion_failure_yields_connector_failure(
        self, mock_requests: MagicMock
    ) -> None:
        """Bad data for one page yields ConnectorFailure, doesn't stop processing."""
        bad_page = {
            "page_id": 10,
            "url": "test",
            "title": "Test",
            "body": None,
            "created_at": "2025-06-15T12:00:00Z",
            "updated_at": "bad-date",
        }
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
    def test_all_courses_done_sets_has_more_false(
        self, mock_requests: MagicMock
    ) -> None:
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
# retrieve_all_slim_docs_perm_sync tests
# ---------------------------------------------------------------------------


class TestRetrieveAllSlimDocsPermSync:
    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_yields_slim_documents_with_ids(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
        mock_perms.return_value = ExternalAccess(
            external_user_emails={"prof@school.edu"},
            external_user_group_ids=set(),
            is_public=False,
        )
        mock_requests.get.side_effect = _make_url_dispatcher(
            courses=[_mock_course(1)],
            pages=[_mock_page(10)],
            assignments=[_mock_assignment(20)],
            announcements=[_mock_announcement(30)],
        )
        connector = _build_connector()

        batches = list(connector.retrieve_all_slim_docs_perm_sync())
        all_items = [item for batch in batches for item in batch]
        result_ids = {doc.id for doc in all_items if isinstance(doc, SlimDocument)}
        hierarchy_ids = {
            node.raw_node_id for node in all_items if isinstance(node, HierarchyNode)
        }

        expected_ids = {
            "canvas-page-1-10",
            "canvas-assignment-1-20",
            "canvas-announcement-1-30",
        }

        assert result_ids == expected_ids
        assert "canvas-course-1" in hierarchy_ids

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_slim_docs_have_external_access(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
        expected_access = ExternalAccess(
            external_user_emails={"prof@school.edu", "ta@school.edu"},
            external_user_group_ids=set(),
            is_public=False,
        )
        mock_perms.return_value = expected_access
        mock_requests.get.side_effect = _make_url_dispatcher(
            courses=[_mock_course(1)],
            pages=[_mock_page(10)],
            assignments=[],
            announcements=[],
        )
        connector = _build_connector()

        batches = list(connector.retrieve_all_slim_docs_perm_sync())
        all_items = [item for batch in batches for item in batch]
        slim_docs = [d for d in all_items if isinstance(d, SlimDocument)]

        assert len(slim_docs) == 1
        assert slim_docs[0].external_access == expected_access

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_batching(self, mock_requests: MagicMock, mock_perms: MagicMock) -> None:
        mock_perms.return_value = ExternalAccess(
            external_user_emails={"prof@school.edu"},
            external_user_group_ids=set(),
            is_public=False,
        )
        mock_requests.get.side_effect = _make_url_dispatcher(
            courses=[_mock_course(1)],
            pages=[_mock_page(10), _mock_page(11, "Page 2"), _mock_page(12, "Page 3")],
            assignments=[],
            announcements=[],
        )
        connector = _build_connector()
        connector.batch_size = 2

        batches = list(connector.retrieve_all_slim_docs_perm_sync())
        all_items = [item for batch in batches for item in batch]

        # 1 course node + 1 course-level "Pages" type folder + 3 page slim
        # docs = 5 items total. With batch_size=2: batches of [2, 2, 1].
        assert len(all_items) == 5
        assert len(batches[0]) == 2


# ---------------------------------------------------------------------------
# Permission cache tests
# ---------------------------------------------------------------------------


class TestGetCoursePermissions:
    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    def test_permissions_cached(self, mock_perms: MagicMock) -> None:
        mock_perms.return_value = ExternalAccess(
            external_user_emails={"prof@school.edu"},
            external_user_group_ids=set(),
            is_public=False,
        )
        connector = _build_connector()

        result1 = connector._get_course_permissions(1)
        result2 = connector._get_course_permissions(1)

        assert result1 == result2
        mock_perms.assert_called_once()

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    def test_returns_none_when_ce(self, mock_perms: MagicMock) -> None:
        """When not EE, get_course_permissions returns None."""
        mock_perms.return_value = None
        connector = _build_connector()

        result = connector._get_course_permissions(1)

        assert result is None


# ---------------------------------------------------------------------------
# EE access — get_course_permissions (enrollment API)
# ---------------------------------------------------------------------------


def _mock_enrollment(
    login_id: str = "student@school.edu",
    email: str | None = None,
    enrollment_type: str = "StudentEnrollment",
) -> dict[str, Any]:
    """Create a mock Canvas enrollment API response entry."""
    user: dict[str, Any] = {"login_id": login_id}
    if email is not None:
        user["email"] = email
    return {
        "type": enrollment_type,
        "user": user,
    }


@pytest.mark.usefixtures("enable_ee")
class TestEEGetCoursePermissions:
    def test_extracts_emails_from_login_id(self) -> None:
        """Emails are extracted from user.login_id."""
        from ee.onyx.external_permissions.canvas.access import get_course_permissions

        client = MagicMock(spec=CanvasApiClient)
        client.get.return_value = (
            [
                _mock_enrollment(
                    "prof@school.edu", enrollment_type="TeacherEnrollment"
                ),
                _mock_enrollment(
                    "student@school.edu", enrollment_type="StudentEnrollment"
                ),
            ],
            None,
        )

        result = get_course_permissions(client, course_id=1)

        expected_emails = {"prof@school.edu", "student@school.edu"}

        assert result.external_user_emails == expected_emails
        assert result.is_public is False
        assert result.external_user_group_ids == set()

    def test_falls_back_to_email_field(self) -> None:
        """If login_id is missing, falls back to user.email."""
        from ee.onyx.external_permissions.canvas.access import get_course_permissions

        client = MagicMock(spec=CanvasApiClient)
        client.get.return_value = (
            [{"type": "StudentEnrollment", "user": {"email": "fallback@school.edu"}}],
            None,
        )

        result = get_course_permissions(client, course_id=1)

        expected_emails = {"fallback@school.edu"}

        assert result.external_user_emails == expected_emails

    def test_skips_users_without_email(self) -> None:
        """Users with no login_id or email are skipped."""
        from ee.onyx.external_permissions.canvas.access import get_course_permissions

        client = MagicMock(spec=CanvasApiClient)
        client.get.return_value = (
            [
                _mock_enrollment("valid@school.edu"),
                {"type": "StudentEnrollment", "user": {}},
            ],
            None,
        )

        result = get_course_permissions(client, course_id=1)

        expected_emails = {"valid@school.edu"}

        assert result.external_user_emails == expected_emails

    def test_deduplicates_emails(self) -> None:
        """Same email appearing twice is deduplicated."""
        from ee.onyx.external_permissions.canvas.access import get_course_permissions

        client = MagicMock(spec=CanvasApiClient)
        client.get.return_value = (
            [
                _mock_enrollment("same@school.edu"),
                _mock_enrollment("same@school.edu", enrollment_type="TaEnrollment"),
            ],
            None,
        )

        result = get_course_permissions(client, course_id=1)

        expected_emails = {"same@school.edu"}

        assert result.external_user_emails == expected_emails

    def test_paginates_via_next_url(self) -> None:
        """Follows pagination links to collect all enrollments."""
        from ee.onyx.external_permissions.canvas.access import get_course_permissions

        client = MagicMock(spec=CanvasApiClient)
        client.get.side_effect = [
            (
                [_mock_enrollment("page1@school.edu")],
                "https://canvas.example.com/api/v1/next",
            ),
            ([_mock_enrollment("page2@school.edu")], None),
        ]

        result = get_course_permissions(client, course_id=1)

        expected_emails = {"page1@school.edu", "page2@school.edu"}

        assert result.external_user_emails == expected_emails
        assert client.get.call_count == 2

    def test_empty_enrollments_returns_empty_access(self) -> None:
        """No enrollments returns ExternalAccess.empty()."""
        from ee.onyx.external_permissions.canvas.access import get_course_permissions

        client = MagicMock(spec=CanvasApiClient)
        client.get.return_value = ([], None)

        result = get_course_permissions(client, course_id=1)

        assert result == ExternalAccess.empty()

    def test_api_error_returns_empty_access(self) -> None:
        """API failure returns ExternalAccess.empty() (safe fallback)."""
        from ee.onyx.external_permissions.canvas.access import get_course_permissions

        client = MagicMock(spec=CanvasApiClient)
        client.get.side_effect = Exception("Canvas API down")

        result = get_course_permissions(client, course_id=1)

        assert result == ExternalAccess.empty()


# ---------------------------------------------------------------------------
# New content type tests — files, quizzes, discussions, modules, syllabus
# ---------------------------------------------------------------------------


class TestDocumentConversionNewTypes:
    """Test document conversion for files, quizzes, discussions, syllabus."""

    def test_convert_file_to_document(self) -> None:
        from onyx.connectors.canvas.connector import CanvasFile

        connector = _build_connector()
        file = CanvasFile(
            id=40,
            display_name="slides_week1.pdf",
            filename="slides_week1.pdf",
            url="https://files.instructure.com/40/download",
            content_type="application/pdf",
            size=1024,
            updated_at="2025-06-01T12:00:00Z",
            course_id=1,
        )
        doc = connector._convert_file_to_document(file)

        assert doc.id == "canvas-file-1-40"
        assert doc.semantic_identifier == "slides_week1.pdf"
        assert doc.metadata["type"] == "file"
        assert doc.metadata["course_id"] == "1"
        assert "slides_week1.pdf" in doc.sections[0].text
        assert doc.parent_hierarchy_raw_node_id == "canvas-type-course-1-file"

    def test_convert_quiz_to_document(self) -> None:
        from onyx.connectors.canvas.connector import CanvasQuiz

        connector = _build_connector()
        quiz = CanvasQuiz(
            id=50,
            title="Midterm Review",
            description="<p>Practice for the midterm</p>",
            html_url=f"{FAKE_BASE_URL}/courses/1/quizzes/50",
            quiz_type="practice_quiz",
            question_count=20,
            published=True,
            course_id=1,
            updated_at="2025-06-01T12:00:00Z",
        )
        doc = connector._convert_quiz_to_document(quiz)

        assert doc.id == "canvas-quiz-1-50"
        assert doc.semantic_identifier == "Midterm Review"
        assert doc.metadata["type"] == "quiz"
        text = doc.sections[0].text
        assert "Midterm Review" in text
        assert "Practice for the midterm" in text
        assert "Questions: 20" in text
        assert doc.parent_hierarchy_raw_node_id == "canvas-type-course-1-quiz"

    def test_convert_discussion_to_document(self) -> None:
        from onyx.connectors.canvas.connector import CanvasDiscussion

        connector = _build_connector()
        disc = CanvasDiscussion(
            id=60,
            title="Week 1 Discussion",
            message="<p>Discuss the readings</p>",
            html_url=f"{FAKE_BASE_URL}/courses/1/discussion_topics/60",
            posted_at="2025-06-01T12:00:00Z",
            course_id=1,
        )
        doc = connector._convert_discussion_to_document(disc)

        assert doc.id == "canvas-discussion-1-60"
        assert doc.semantic_identifier == "Week 1 Discussion"
        assert doc.metadata["type"] == "discussion"
        text = doc.sections[0].text
        assert "Week 1 Discussion" in text
        assert "Discuss the readings" in text
        assert doc.parent_hierarchy_raw_node_id == "canvas-type-course-1-discussion"

    def test_convert_syllabus_to_document(self) -> None:
        connector = _build_connector()
        doc = connector._convert_syllabus_to_document(
            course_id=1,
            syllabus_body="<h1>Course Syllabus</h1><p>Welcome to CS 101</p>",
        )

        assert doc.id == "canvas-syllabus-1"
        assert doc.semantic_identifier == "Syllabus"
        assert doc.metadata["type"] == "syllabus"
        text = doc.sections[0].text
        assert "Syllabus" in text
        assert "Welcome to CS 101" in text
        assert doc.parent_hierarchy_raw_node_id == "canvas-type-course-1-syllabus"


class TestCheckpointNewStages:
    """Test checkpoint processing for new content types."""

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_files_stage_yields_file_documents(self, mock_requests: MagicMock) -> None:
        file = _mock_file(40, updated_at="2025-06-15T12:00:00Z")
        mock_requests.get.side_effect = _make_url_dispatcher(files=[file])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="files"
        )
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        items, new_cp = _run_checkpoint(connector, cp, start, end)

        assert len(items) == 1
        assert isinstance(items[0], Document)
        assert items[0].id == "canvas-file-1-40"
        assert new_cp.stage == "modules"

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_quizzes_stage_yields_quiz_documents(
        self, mock_requests: MagicMock
    ) -> None:
        quiz = _mock_quiz(50, updated_at="2025-06-15T12:00:00Z")
        mock_requests.get.side_effect = _make_url_dispatcher(quizzes=[quiz])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="quizzes"
        )
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        items, new_cp = _run_checkpoint(connector, cp, start, end)

        assert len(items) == 1
        assert isinstance(items[0], Document)
        assert items[0].id == "canvas-quiz-1-50"
        assert new_cp.stage == "discussions"

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_quizzes_stage_skips_unpublished(self, mock_requests: MagicMock) -> None:
        quiz = _mock_quiz(50, updated_at="2025-06-15T12:00:00Z")
        quiz["published"] = False
        mock_requests.get.side_effect = _make_url_dispatcher(quizzes=[quiz])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="quizzes"
        )
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        items, new_cp = _run_checkpoint(connector, cp, start, end)

        assert len(items) == 0

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_discussions_stage_yields_discussion_documents(
        self, mock_requests: MagicMock
    ) -> None:
        disc = _mock_discussion(60, posted_at="2025-06-15T12:00:00Z")
        mock_requests.get.side_effect = _make_url_dispatcher(discussions=[disc])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="discussions"
        )
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        items, new_cp = _run_checkpoint(connector, cp, start, end)

        assert len(items) == 1
        assert isinstance(items[0], Document)
        assert items[0].id == "canvas-discussion-1-60"
        assert new_cp.stage == "syllabus"

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_discussions_stage_skips_announcements(
        self, mock_requests: MagicMock
    ) -> None:
        disc = _mock_discussion(60, posted_at="2025-06-15T12:00:00Z")
        disc["is_announcement"] = True
        mock_requests.get.side_effect = _make_url_dispatcher(discussions=[disc])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="discussions"
        )
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        items, _ = _run_checkpoint(connector, cp, start, end)

        assert len(items) == 0

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_syllabus_stage_yields_document_and_advances_course(
        self, mock_requests: MagicMock
    ) -> None:
        mock_requests.get.side_effect = _make_url_dispatcher(
            syllabus_body="<p>Course overview</p>"
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="syllabus"
        )

        items, new_cp = _run_checkpoint(connector, cp)

        assert len(items) == 1
        assert isinstance(items[0], Document)
        assert items[0].id == "canvas-syllabus-1"
        assert new_cp.current_course_index == 1
        assert new_cp.stage == "pages"
        assert new_cp.has_more is False

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_syllabus_stage_skips_when_empty(self, mock_requests: MagicMock) -> None:
        mock_requests.get.side_effect = _make_url_dispatcher(syllabus_body=None)
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="syllabus"
        )

        items, new_cp = _run_checkpoint(connector, cp)

        assert len(items) == 0
        assert new_cp.current_course_index == 1

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_modules_stage_advances_to_quizzes(self, mock_requests: MagicMock) -> None:
        module = _mock_module(70, "Module 1")
        mock_requests.get.side_effect = _make_url_dispatcher(modules=[module])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="modules"
        )

        items, new_cp = _run_checkpoint(connector, cp)

        assert new_cp.stage == "quizzes"

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_files_stage_filters_by_time_window(self, mock_requests: MagicMock) -> None:
        old_file = _mock_file(40, updated_at="2025-01-01T00:00:00Z")
        new_file = _mock_file(
            41, display_name="new.pdf", updated_at="2025-06-15T12:00:00Z"
        )
        mock_requests.get.side_effect = _make_url_dispatcher(files=[old_file, new_file])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="files"
        )
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        items, _ = _run_checkpoint(connector, cp, start, end)

        assert len(items) == 1
        assert items[0].id == "canvas-file-1-41"


class TestReleasedMaterialsFiltering:
    """Released-material filters must match between full-doc and slim-doc paths."""

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_page_with_future_unlock_at_is_excluded(
        self, mock_requests: MagicMock
    ) -> None:
        page = _mock_page(10, updated_at="2025-06-15T12:00:00Z")
        page["published"] = True
        page["unlock_at"] = "2099-01-01T00:00:00Z"
        mock_requests.get.side_effect = _make_url_dispatcher(pages=[page])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )

        items, _ = _run_checkpoint(connector, cp)

        assert [item for item in items if isinstance(item, Document)] == []

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_page_with_past_unlock_at_is_included(
        self, mock_requests: MagicMock
    ) -> None:
        page = _mock_page(10, updated_at="2025-06-15T12:00:00Z")
        page["published"] = True
        page["unlock_at"] = "2025-01-01T00:00:00Z"
        mock_requests.get.side_effect = _make_url_dispatcher(pages=[page])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )

        items, _ = _run_checkpoint(connector, cp)

        docs = [item for item in items if isinstance(item, Document)]
        assert len(docs) == 1
        assert docs[0].id == "canvas-page-1-10"

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_page_with_past_lock_at_is_excluded(self, mock_requests: MagicMock) -> None:
        page = _mock_page(10, updated_at="2025-06-15T12:00:00Z")
        page["published"] = True
        page["lock_at"] = "2025-01-01T00:00:00Z"
        mock_requests.get.side_effect = _make_url_dispatcher(pages=[page])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )

        items, _ = _run_checkpoint(connector, cp)

        assert [item for item in items if isinstance(item, Document)] == []

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_unpublished_assignment_is_excluded(self, mock_requests: MagicMock) -> None:
        assignment = _mock_assignment(20, updated_at="2025-06-15T12:00:00Z")
        assignment["published"] = False
        mock_requests.get.side_effect = _make_url_dispatcher(assignments=[assignment])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="assignments"
        )

        items, _ = _run_checkpoint(connector, cp)

        assert [item for item in items if isinstance(item, Document)] == []

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_hidden_and_locked_files_are_excluded(
        self, mock_requests: MagicMock
    ) -> None:
        hidden_file = _mock_file(40, updated_at="2025-06-15T12:00:00Z")
        hidden_file["hidden"] = True
        locked_file = _mock_file(41, "locked.pdf", updated_at="2025-06-15T12:00:00Z")
        locked_file["locked"] = True
        mock_requests.get.side_effect = _make_url_dispatcher(
            files=[hidden_file, locked_file]
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="files"
        )

        items, _ = _run_checkpoint(connector, cp)

        assert [item for item in items if isinstance(item, Document)] == []

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_page_in_unpublished_module_is_excluded(
        self, mock_requests: MagicMock
    ) -> None:
        module = _mock_module(70, "Draft Module")
        module["published"] = False
        mock_requests.get.side_effect = _make_url_dispatcher(
            pages=[_mock_page(10, updated_at="2025-06-15T12:00:00Z")],
            modules=[module],
            module_items=[
                {"id": 500, "title": "Welcome", "type": "Page", "content_id": 10}
            ],
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )

        items, _ = _run_checkpoint(connector, cp)

        assert [item for item in items if isinstance(item, Document)] == []

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_page_in_future_locked_module_is_excluded(
        self, mock_requests: MagicMock
    ) -> None:
        module = _mock_module(70, "Future Module")
        module["unlock_at"] = "2099-01-01T00:00:00Z"
        mock_requests.get.side_effect = _make_url_dispatcher(
            pages=[_mock_page(10, updated_at="2025-06-15T12:00:00Z")],
            modules=[module],
            module_items=[
                {"id": 500, "title": "Welcome", "type": "Page", "content_id": 10}
            ],
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )

        items, _ = _run_checkpoint(connector, cp)

        assert [item for item in items if isinstance(item, Document)] == []

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_delayed_announcement_is_excluded(self, mock_requests: MagicMock) -> None:
        announcement = _mock_announcement(30, posted_at="2025-06-15T12:00:00Z")
        announcement["delayed_post_at"] = "2099-01-01T00:00:00Z"
        mock_requests.get.side_effect = _make_url_dispatcher(
            announcements=[announcement]
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="announcements"
        )

        items, _ = _run_checkpoint(connector, cp)

        assert [item for item in items if isinstance(item, Document)] == []

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_quiz_with_past_lock_at_is_excluded(self, mock_requests: MagicMock) -> None:
        quiz = _mock_quiz(50, updated_at="2025-06-15T12:00:00Z")
        quiz["lock_at"] = "2025-01-01T00:00:00Z"
        mock_requests.get.side_effect = _make_url_dispatcher(quizzes=[quiz])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="quizzes"
        )

        items, _ = _run_checkpoint(connector, cp)

        assert [item for item in items if isinstance(item, Document)] == []

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_delayed_discussion_is_excluded(self, mock_requests: MagicMock) -> None:
        discussion = _mock_discussion(60, posted_at="2025-06-15T12:00:00Z")
        discussion["delayed_post_at"] = "2099-01-01T00:00:00Z"
        mock_requests.get.side_effect = _make_url_dispatcher(discussions=[discussion])
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="discussions"
        )

        items, _ = _run_checkpoint(connector, cp)

        assert [item for item in items if isinstance(item, Document)] == []

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_slim_docs_skip_page_in_unpublished_module(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
        mock_perms.return_value = None
        module = _mock_module(70, "Draft Module")
        module["published"] = False
        mock_requests.get.side_effect = _make_url_dispatcher(
            courses=[_mock_course(1)],
            pages=[_mock_page(10)],
            modules=[module],
            module_items=[
                {"id": 500, "title": "Welcome", "type": "Page", "content_id": 10}
            ],
        )
        connector = _build_connector()

        batches = list(connector.retrieve_all_slim_docs_perm_sync())
        all_items = [item for batch in batches for item in batch]
        slim_ids = {doc.id for doc in all_items if isinstance(doc, SlimDocument)}

        assert "canvas-page-1-10" not in slim_ids

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_slim_docs_skip_future_locked_page(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
        mock_perms.return_value = None
        page = _mock_page(10)
        page["published"] = True
        page["unlock_at"] = "2099-01-01T00:00:00Z"
        mock_requests.get.side_effect = _make_url_dispatcher(
            courses=[_mock_course(1)],
            pages=[page],
        )
        connector = _build_connector()

        batches = list(connector.retrieve_all_slim_docs_perm_sync())
        all_items = [item for batch in batches for item in batch]
        slim_ids = {doc.id for doc in all_items if isinstance(doc, SlimDocument)}

        assert "canvas-page-1-10" not in slim_ids

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_respect_release_dates_false_ignores_dates(
        self, mock_requests: MagicMock
    ) -> None:
        page = _mock_page(10, updated_at="2025-06-15T12:00:00Z")
        page["published"] = True
        page["unlock_at"] = "2099-01-01T00:00:00Z"
        mock_requests.get.side_effect = _make_url_dispatcher(pages=[page])
        connector = _build_connector(credentials={"respect_release_dates": False})
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )

        items, _ = _run_checkpoint(connector, cp)

        docs = [item for item in items if isinstance(item, Document)]
        assert len(docs) == 1
        assert docs[0].id == "canvas-page-1-10"


class TestSlimDocsNewTypes:
    """Test retrieve_all_slim_docs_perm_sync includes new content types."""

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_includes_files_quizzes_discussions_in_slim_docs(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
        mock_perms.return_value = ExternalAccess(
            external_user_emails={"prof@school.edu"},
            external_user_group_ids=set(),
            is_public=False,
        )
        mock_requests.get.side_effect = _make_url_dispatcher(
            courses=[_mock_course(1)],
            pages=[],
            assignments=[],
            announcements=[],
            files=[_mock_file(40)],
            quizzes=[_mock_quiz(50)],
            discussions=[_mock_discussion(60)],
            syllabus_body="<p>Syllabus content</p>",
        )
        connector = _build_connector()

        batches = list(connector.retrieve_all_slim_docs_perm_sync())
        all_items = [item for batch in batches for item in batch]
        slim_ids = {doc.id for doc in all_items if isinstance(doc, SlimDocument)}

        assert "canvas-file-1-40" in slim_ids
        assert "canvas-quiz-1-50" in slim_ids
        assert "canvas-discussion-1-60" in slim_ids
        assert "canvas-syllabus-1" in slim_ids

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_emits_course_and_module_hierarchy_nodes(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
        mock_perms.return_value = ExternalAccess(
            external_user_emails={"prof@school.edu"},
            external_user_group_ids=set(),
            is_public=False,
        )
        mock_requests.get.side_effect = _make_url_dispatcher(
            courses=[_mock_course(1)],
            pages=[],
            assignments=[],
            announcements=[],
            modules=[_mock_module(70, "Module 1")],
        )
        connector = _build_connector()

        batches = list(connector.retrieve_all_slim_docs_perm_sync())
        all_items = [item for batch in batches for item in batch]
        hierarchy_nodes = [n for n in all_items if isinstance(n, HierarchyNode)]

        node_ids = {n.raw_node_id for n in hierarchy_nodes}
        assert "canvas-course-1" in node_ids
        assert "canvas-module-1-70" in node_ids

        # Verify parent relationships
        course_node = next(
            n for n in hierarchy_nodes if n.raw_node_id == "canvas-course-1"
        )
        module_node = next(
            n for n in hierarchy_nodes if n.raw_node_id == "canvas-module-1-70"
        )
        assert course_node.raw_parent_id is None
        assert module_node.raw_parent_id == "canvas-course-1"

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_slim_docs_have_parent_hierarchy(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
        mock_perms.return_value = None
        mock_requests.get.side_effect = _make_url_dispatcher(
            courses=[_mock_course(1)],
            pages=[_mock_page(10)],
            assignments=[],
            announcements=[],
        )
        connector = _build_connector()

        batches = list(connector.retrieve_all_slim_docs_perm_sync())
        all_items = [item for batch in batches for item in batch]
        slim_docs = [d for d in all_items if isinstance(d, SlimDocument)]

        assert len(slim_docs) == 1
        assert slim_docs[0].parent_hierarchy_raw_node_id == "canvas-type-course-1-page"


# ---------------------------------------------------------------------------
# Module membership routing — type folders under courses & modules
# ---------------------------------------------------------------------------


class TestModuleTypeFolders:
    """Type folder routing: items in a module land under that module's
    type folder; otherwise under the course's type folder."""

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_page_in_module_routes_to_module_type_folder(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
        mock_perms.return_value = None
        mock_requests.get.side_effect = _make_url_dispatcher(
            courses=[_mock_course(1)],
            pages=[_mock_page(10)],
            modules=[_mock_module(70, "Module 1")],
            module_items=[
                {
                    "id": 500,
                    "title": "Welcome",
                    "type": "Page",
                    "content_id": 10,
                }
            ],
        )
        connector = _build_connector()

        batches = list(connector.retrieve_all_slim_docs_perm_sync())
        all_items = [item for batch in batches for item in batch]
        slim_docs = [d for d in all_items if isinstance(d, SlimDocument)]
        hierarchy_nodes = [n for n in all_items if isinstance(n, HierarchyNode)]

        assert len(slim_docs) == 1
        assert (
            slim_docs[0].parent_hierarchy_raw_node_id == "canvas-type-module-1-70-page"
        )

        # The module-level Pages folder must be emitted with the module
        # as its parent.
        module_type_folder = next(
            n
            for n in hierarchy_nodes
            if n.raw_node_id == "canvas-type-module-1-70-page"
        )
        assert module_type_folder.raw_parent_id == "canvas-module-1-70"
        assert module_type_folder.display_name == "Pages"

        # No course-level Pages folder should be emitted, since no page
        # landed under the course.
        node_ids = {n.raw_node_id for n in hierarchy_nodes}
        assert "canvas-type-course-1-page" not in node_ids

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_announcement_always_routes_to_course_folder(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
        # Announcements aren't part of modules in Canvas — they always
        # hang off the course-level Announcements folder regardless of
        # what modules exist.
        mock_perms.return_value = None
        mock_requests.get.side_effect = _make_url_dispatcher(
            courses=[_mock_course(1)],
            announcements=[_mock_announcement(30)],
            modules=[_mock_module(70, "Module 1")],
        )
        connector = _build_connector()

        batches = list(connector.retrieve_all_slim_docs_perm_sync())
        all_items = [item for batch in batches for item in batch]
        slim_docs = [d for d in all_items if isinstance(d, SlimDocument)]

        assert len(slim_docs) == 1
        assert (
            slim_docs[0].parent_hierarchy_raw_node_id
            == "canvas-type-course-1-announcement"
        )

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_full_doc_uses_module_type_folder_parent(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
        # Full Document path (load_from_checkpoint) also routes through
        # the membership map.
        mock_perms.return_value = None
        mock_requests.get.side_effect = _make_url_dispatcher(
            pages=[_mock_page(10, updated_at="2025-06-15T12:00:00Z")],
            modules=[_mock_module(70, "Module 1")],
            module_items=[
                {
                    "id": 500,
                    "title": "Welcome",
                    "type": "Page",
                    "content_id": 10,
                }
            ],
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        items, _new_cp = _run_checkpoint(connector, cp, start, end)

        docs = [i for i in items if isinstance(i, Document)]
        assert len(docs) == 1
        assert docs[0].parent_hierarchy_raw_node_id == "canvas-type-module-1-70-page"


# ---------------------------------------------------------------------------
# Hierarchy emission from load_from_checkpoint (regular indexing)
# ---------------------------------------------------------------------------


class TestHierarchyEmissionInIndexing:
    """The regular indexing flow (load_from_checkpoint) must yield Course +
    Module + module-level type folder HierarchyNode objects so that
    PUBLIC connectors (which never run perm sync) still get their hierarchy
    populated."""

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_starter_hierarchy_emitted_at_start_of_course(
        self, mock_requests: MagicMock
    ) -> None:
        mock_requests.get.side_effect = _make_url_dispatcher(
            pages=[_mock_page(10, updated_at="2025-06-15T12:00:00Z")],
            modules=[_mock_module(70, "Module 1")],
            module_items=[
                {"id": 500, "title": "Welcome", "type": "Page", "content_id": 10}
            ],
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        items, _ = _run_checkpoint(connector, cp, start, end, include_hierarchy=True)

        nodes = [i for i in items if isinstance(i, HierarchyNode)]
        node_ids = {n.raw_node_id for n in nodes}

        assert "canvas-course-1" in node_ids
        assert "canvas-module-1-70" in node_ids
        # Module-level Pages folder must exist (has an item)
        assert "canvas-type-module-1-70-page" in node_ids

        # Parent relationships
        course_node = next(n for n in nodes if n.raw_node_id == "canvas-course-1")
        module_node = next(n for n in nodes if n.raw_node_id == "canvas-module-1-70")
        module_pages_folder = next(
            n for n in nodes if n.raw_node_id == "canvas-type-module-1-70-page"
        )
        assert course_node.raw_parent_id is None
        assert module_node.raw_parent_id == "canvas-course-1"
        assert module_pages_folder.raw_parent_id == "canvas-module-1-70"

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_course_level_type_folder_emitted_lazily_before_doc(
        self, mock_requests: MagicMock
    ) -> None:
        # Page is NOT in any module — its parent is a course-level type
        # folder, which must be emitted before the doc itself.
        mock_requests.get.side_effect = _make_url_dispatcher(
            pages=[_mock_page(10, updated_at="2025-06-15T12:00:00Z")],
            modules=[],
        )
        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        items, _ = _run_checkpoint(connector, cp, start, end, include_hierarchy=True)

        # Find the Pages course-level folder and the page doc.
        folder_idx = next(
            i
            for i, item in enumerate(items)
            if isinstance(item, HierarchyNode)
            and item.raw_node_id == "canvas-type-course-1-page"
        )
        doc_idx = next(
            i
            for i, item in enumerate(items)
            if isinstance(item, Document) and item.id == "canvas-page-1-10"
        )
        # Folder must be yielded before the doc that depends on it.
        assert folder_idx < doc_idx

        folder = items[folder_idx]
        assert isinstance(folder, HierarchyNode)
        assert folder.raw_parent_id == "canvas-course-1"
        assert folder.display_name == "Pages"

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_starter_hierarchy_only_emitted_once_per_course(
        self, mock_requests: MagicMock
    ) -> None:
        # Drive multiple stages on the same course and verify the course
        # node is yielded only the first time, not on every stage call.
        mock_requests.get.side_effect = _make_url_dispatcher(
            pages=[_mock_page(10, updated_at="2025-06-15T12:00:00Z")],
            assignments=[_mock_assignment(20, updated_at="2025-06-15T12:00:00Z")],
        )
        connector = _build_connector()
        start = datetime(2025, 6, 1, tzinfo=timezone.utc).timestamp()
        end = datetime(2025, 6, 30, tzinfo=timezone.utc).timestamp()

        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )
        items_pages, cp = _run_checkpoint(
            connector, cp, start, end, include_hierarchy=True
        )
        items_assignments, _ = _run_checkpoint(
            connector, cp, start, end, include_hierarchy=True
        )

        course_nodes_pages = [
            n
            for n in items_pages
            if isinstance(n, HierarchyNode) and n.raw_node_id == "canvas-course-1"
        ]
        course_nodes_assignments = [
            n
            for n in items_assignments
            if isinstance(n, HierarchyNode) and n.raw_node_id == "canvas-course-1"
        ]
        assert len(course_nodes_pages) == 1
        assert len(course_nodes_assignments) == 0
