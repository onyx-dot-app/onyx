"""Tests for Canvas connector (checkpointed pattern + permission sync)."""

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
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
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


def _build_connector(base_url: str = FAKE_BASE_URL) -> CanvasConnector:
    """Build a connector with mocked credential validation."""
    with patch("onyx.connectors.canvas.client.rl_requests") as mock_req:
        mock_req.get.return_value = _mock_response(json_data=[_mock_course()])
        connector = CanvasConnector(canvas_base_url=base_url)
        connector.load_credentials({"canvas_access_token": FAKE_TOKEN})
    return connector


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


def _make_url_dispatcher(
    courses: list[dict[str, Any]] | None = None,
    pages: list[dict[str, Any]] | None = None,
    assignments: list[dict[str, Any]] | None = None,
    announcements: list[dict[str, Any]] | None = None,
    page_error: bool = False,
) -> Any:
    """Return a side_effect function for rl_requests.get that dispatches by URL."""

    def mock_get(url: str, **kwargs: Any) -> MagicMock:
        if "/courses" in url and "/pages" in url:
            if page_error:
                return _mock_response(500, {})
            return _mock_response(json_data=pages or [])
        elif "/assignments" in url:
            return _mock_response(json_data=assignments or [])
        elif "/announcements" in url:
            return _mock_response(json_data=announcements or [])
        elif "/courses" in url:
            return _mock_response(json_data=courses or [])
        return _mock_response(json_data=[])

    return mock_get


# Helper to exhaust a checkpoint generator and get the returned checkpoint
def _run_checkpoint(
    connector: CanvasConnector,
    checkpoint: CanvasConnectorCheckpoint,
    start: float = 0.0,
    end: float = 9999999999.0,
) -> tuple[list[Document | ConnectorFailure], CanvasConnectorCheckpoint]:
    """Run load_from_checkpoint, collect yielded items, return (items, checkpoint)."""
    gen = connector.load_from_checkpoint(start, end, checkpoint)
    items: list[Document | ConnectorFailure] = []
    try:
        while True:
            items.append(next(gen))
    except StopIteration as e:
        return items, e.value


# ---------------------------------------------------------------------------
# CanvasApiClient tests
# ---------------------------------------------------------------------------


class TestCanvasApiClient:
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
        header = '<https://canvas.example.com/api/v1/courses?page=2>; rel="next"'
        assert CanvasApiClient._parse_next_link(header) == (
            "https://canvas.example.com/api/v1/courses?page=2"
        )

    def test_parse_next_link_not_found(self) -> None:
        header = '<https://canvas.example.com/api/v1/courses?page=1>; rel="current"'
        assert CanvasApiClient._parse_next_link(header) is None

    def test_parse_next_link_empty(self) -> None:
        assert CanvasApiClient._parse_next_link("") is None

    def test_parse_next_link_multiple_rels(self) -> None:
        header = (
            '<https://canvas.example.com/api/v1/courses?page=1>; rel="current", '
            '<https://canvas.example.com/api/v1/courses?page=2>; rel="next"'
        )
        assert CanvasApiClient._parse_next_link(header) == (
            "https://canvas.example.com/api/v1/courses?page=2"
        )


# ---------------------------------------------------------------------------
# CanvasConnector — credential loading
# ---------------------------------------------------------------------------


class TestLoadCredentials:
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
        mock_requests.get.return_value = _mock_response(401, {})
        connector = CanvasConnector(canvas_base_url=FAKE_BASE_URL)
        with pytest.raises(CredentialExpiredError, match="invalid or expired"):
            connector.load_credentials({"canvas_access_token": "bad-token"})


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

        assert doc.id == "canvas-page-1-10"
        assert doc.source == DocumentSource.CANVAS
        assert doc.semantic_identifier == "Syllabus"
        assert doc.metadata == {"course_id": "1"}
        assert f"{FAKE_BASE_URL}/courses/1/pages/syllabus" in doc.sections[0].link
        assert doc.doc_updated_at == datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

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

        assert doc.id == "canvas-assignment-1-20"
        assert doc.source == DocumentSource.CANVAS
        assert doc.semantic_identifier == "Homework 1"
        assert "Due: 2025-02-01T23:59:00Z" in doc.sections[0].text

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

        assert doc.id == "canvas-announcement-1-30"
        assert doc.source == DocumentSource.CANVAS
        assert doc.semantic_identifier == "Class Cancelled"
        assert doc.doc_updated_at == datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

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
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_validate_success(self, mock_requests: MagicMock) -> None:
        mock_requests.get.return_value = _mock_response(json_data=[_mock_course()])
        connector = _build_connector()
        connector.validate_connector_settings()

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_validate_expired_credential(self, mock_requests: MagicMock) -> None:
        success_resp = _mock_response(json_data=[_mock_course()])
        fail_resp = _mock_response(401, {})
        mock_requests.get.side_effect = [success_resp, fail_resp]

        connector = CanvasConnector(canvas_base_url=FAKE_BASE_URL)
        connector.load_credentials({"canvas_access_token": FAKE_TOKEN})

        with pytest.raises(CredentialExpiredError):
            connector.validate_connector_settings()

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_validate_rate_limited(self, mock_requests: MagicMock) -> None:
        success_resp = _mock_response(json_data=[_mock_course()])
        fail_resp = _mock_response(429, {})
        mock_requests.get.side_effect = [success_resp, fail_resp]

        connector = CanvasConnector(canvas_base_url=FAKE_BASE_URL)
        connector.load_credentials({"canvas_access_token": FAKE_TOKEN})

        with pytest.raises(ConnectorValidationError):
            connector.validate_connector_settings()

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_validate_unexpected_error(self, mock_requests: MagicMock) -> None:
        success_resp = _mock_response(json_data=[_mock_course()])
        fail_resp = _mock_response(500, {})
        mock_requests.get.side_effect = [success_resp, fail_resp]

        connector = CanvasConnector(canvas_base_url=FAKE_BASE_URL)
        connector.load_credentials({"canvas_access_token": FAKE_TOKEN})

        with pytest.raises(UnexpectedValidationError):
            connector.validate_connector_settings()


# ---------------------------------------------------------------------------
# Checkpoint basics
# ---------------------------------------------------------------------------


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


