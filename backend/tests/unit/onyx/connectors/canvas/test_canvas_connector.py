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

        assert len(items) == 1
        assert isinstance(items[0], Document)
        assert items[0].id == "canvas-page-1-10"
        assert new_cp.stage == "assignments"

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

        assert len(items) == 1
        assert items[0].id == "canvas-page-1-11"

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
        assert new_cp.stage == "pages"  # did NOT advance
        assert new_cp.current_course_index == 0

    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_per_document_conversion_failure_yields_connector_failure(
        self, mock_requests: MagicMock
    ) -> None:
        """Bad data for one page yields ConnectorFailure, doesn't stop processing."""
        # page_id missing will cause KeyError in CanvasPage construction
        bad_page = {"page_id": 10, "url": "test", "title": "Test", "body": None,
                     "created_at": "2025-06-15T12:00:00Z", "updated_at": "bad-date"}

        mock_requests.get.side_effect = _make_url_dispatcher(pages=[bad_page])

        connector = _build_connector()
        cp = CanvasConnectorCheckpoint(
            has_more=True, course_ids=[1], current_course_index=0, stage="pages"
        )

        # The bad date will cause an exception during conversion
        items, new_cp = _run_checkpoint(connector, cp)

        # Should have one ConnectorFailure
        assert len(items) == 1
        assert isinstance(items[0], ConnectorFailure)
        assert new_cp.stage == "assignments"  # stage still advanced

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
        # Force an invalid stage
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

        all_docs = [doc for batch in batches for doc in batch]
        doc_ids = {doc.id for doc in all_docs if isinstance(doc, SlimDocument)}

        assert "canvas-page-1-10" in doc_ids
        assert "canvas-assignment-1-20" in doc_ids
        assert "canvas-announcement-1-30" in doc_ids

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

        all_docs = [doc for batch in batches for doc in batch]
        assert len(all_docs) == 1
        slim_doc = all_docs[0]
        assert isinstance(slim_doc, SlimDocument)
        assert slim_doc.external_access == expected_access

    @patch("onyx.connectors.canvas.connector.get_course_permissions")
    @patch("onyx.connectors.canvas.client.rl_requests")
    def test_batching(
        self, mock_requests: MagicMock, mock_perms: MagicMock
    ) -> None:
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

        # 3 docs with batch_size=2 means 2 batches (2 + 1)
        assert len(batches) == 2
        assert len(batches[0]) == 2
        assert len(batches[1]) == 1


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
        # Should only have been called once due to caching
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
                _mock_enrollment("prof@school.edu", enrollment_type="TeacherEnrollment"),
                _mock_enrollment("student@school.edu", enrollment_type="StudentEnrollment"),
            ],
            None,  # no next page
        )

        result = get_course_permissions(client, course_id=1)

        assert result.external_user_emails == {"prof@school.edu", "student@school.edu"}
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
        assert result.external_user_emails == {"fallback@school.edu"}

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
        assert result.external_user_emails == {"valid@school.edu"}

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
        assert result.external_user_emails == {"same@school.edu"}

    def test_paginates_via_next_url(self) -> None:
        """Follows pagination links to collect all enrollments."""
        from ee.onyx.external_permissions.canvas.access import get_course_permissions

        client = MagicMock(spec=CanvasApiClient)
        client.get.side_effect = [
            ([_mock_enrollment("page1@school.edu")], "https://canvas.example.com/api/v1/next"),
            ([_mock_enrollment("page2@school.edu")], None),
        ]

        result = get_course_permissions(client, course_id=1)
        assert result.external_user_emails == {"page1@school.edu", "page2@school.edu"}
        assert client.get.call_count == 2
        # Second call should use full_url
        _, kwargs = client.get.call_args
        assert kwargs.get("full_url") == "https://canvas.example.com/api/v1/next"

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
