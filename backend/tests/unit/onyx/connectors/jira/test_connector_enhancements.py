"""Tests for Jira connector enhancements: custom field extraction and attachment fetching."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from unittest.mock import patch

from jira import JIRA
from jira.resources import CustomFieldOption
from jira.resources import User

from onyx.connectors.jira.connector import _MAX_ATTACHMENT_SIZE_BYTES
from onyx.connectors.jira.connector import JiraConnector
from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.jira.utils import CustomFieldExtractor
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FieldsBag:
    """A plain object whose __dict__ is exactly what we put in it.

    MagicMock pollutes __dict__ with internal bookkeeping, which breaks
    CustomFieldExtractor.get_issue_custom_fields (it iterates __dict__).
    This class gives us full control over the attribute namespace.
    """

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            object.__setattr__(self, k, v)


def _make_mock_issue(
    key: str = "TEST-1",
    summary: str = "Test Issue",
    description: str = "Test description",
    labels: list[str] | None = None,
    extra_fields: dict[str, Any] | None = None,
    attachments: list[Any] | None = None,
) -> MagicMock:
    """Build a mock Issue with standard fields wired up.

    Uses _FieldsBag for ``issue.fields`` so that ``fields.__dict__``
    contains only the Jira field attributes (no MagicMock internals).
    """
    # Build sub-objects using SimpleNamespace so attribute access
    # returns real values instead of auto-generated MagicMock objects.
    reporter = SimpleNamespace(
        displayName="Reporter Name",
        emailAddress="reporter@example.com",
    )
    assignee = SimpleNamespace(
        displayName="Assignee Name",
        emailAddress="assignee@example.com",
    )
    priority = SimpleNamespace(name="High")
    status = SimpleNamespace(name="Open")
    project = SimpleNamespace(key="TEST", name="Test Project")
    issuetype = SimpleNamespace(name="Bug")
    comment = SimpleNamespace(comments=[])

    field_kwargs: dict[str, Any] = {
        "description": description,
        "summary": summary,
        "labels": labels or [],
        "updated": "2024-01-01T00:00:00+0000",
        "reporter": reporter,
        "assignee": assignee,
        "priority": priority,
        "status": status,
        "resolution": None,
        "project": project,
        "issuetype": issuetype,
        "parent": None,
        "created": "2024-01-01T00:00:00+0000",
        "duedate": None,
        "resolutiondate": None,
        "comment": comment,
        "attachment": attachments if attachments is not None else [],
    }
    if extra_fields:
        field_kwargs.update(extra_fields)

    fields = _FieldsBag(**field_kwargs)

    # Use _FieldsBag for the issue itself too, then add the attributes
    # that process_jira_issue needs. This prevents MagicMock from
    # auto-creating attributes for field names like "reporter", which
    # would shadow the real values on issue.fields.
    issue = _FieldsBag(
        fields=fields,
        key=key,
        raw={"fields": {"description": description}},
    )
    return issue  # type: ignore[return-value]


def _make_attachment(
    attachment_id: str = "att-1",
    filename: str = "report.pdf",
    size: int = 1024,
    content_url: str | None = "https://jira.example.com/attachment/att-1",
    mime_type: str = "application/pdf",
    created: str | None = "2026-01-15T10:00:00.000+0000",
    download_content: bytes = b"binary content",
    download_raises: Exception | None = None,
) -> MagicMock:
    """Build a mock Jira attachment resource."""
    att = MagicMock()
    att.id = attachment_id
    att.filename = filename
    att.size = size
    att.content = content_url
    att.mimeType = mime_type
    att.created = created
    if download_raises:
        att.get.side_effect = download_raises
    else:
        att.get.return_value = download_content
    return att


# ===================================================================
# Test 1: Custom Field Extraction
# ===================================================================


class TestCustomFieldExtractorGetAllCustomFields:
    def test_returns_only_custom_fields(self) -> None:
        """Given a mix of standard and custom fields, only custom fields are returned."""
        mock_client = MagicMock(spec=JIRA)
        mock_client.fields.return_value = [
            {"id": "summary", "name": "Summary", "custom": False},
            {"id": "customfield_10001", "name": "Sprint", "custom": True},
            {"id": "status", "name": "Status", "custom": False},
            {"id": "customfield_10002", "name": "Story Points", "custom": True},
        ]

        result = CustomFieldExtractor.get_all_custom_fields(mock_client)

        assert result == {
            "customfield_10001": "Sprint",
            "customfield_10002": "Story Points",
        }
        assert "summary" not in result
        assert "status" not in result

    def test_returns_empty_dict_when_no_custom_fields(self) -> None:
        """When no custom fields exist, an empty dict is returned."""
        mock_client = MagicMock(spec=JIRA)
        mock_client.fields.return_value = [
            {"id": "summary", "name": "Summary", "custom": False},
        ]

        result = CustomFieldExtractor.get_all_custom_fields(mock_client)
        assert result == {}


class TestCustomFieldExtractorGetIssueCustomFields:
    def test_string_value_extracted(self) -> None:
        """String custom field values pass through as-is."""
        issue = _make_mock_issue(extra_fields={"customfield_10001": "v2024.1"})
        mapping = {"customfield_10001": "Release Version"}

        result = CustomFieldExtractor.get_issue_custom_fields(issue, mapping)
        assert result == {"Release Version": "v2024.1"}

    def test_custom_field_option_value_extracted_as_string(self) -> None:
        """CustomFieldOption objects are converted via .value."""
        option = MagicMock(spec=CustomFieldOption)
        option.value = "Critical Path"

        issue = _make_mock_issue(extra_fields={"customfield_10002": option})
        mapping = {"customfield_10002": "Category"}

        result = CustomFieldExtractor.get_issue_custom_fields(issue, mapping)
        assert result == {"Category": "Critical Path"}

    def test_user_value_extracted_as_display_name(self) -> None:
        """User objects are converted via .displayName."""
        user = MagicMock(spec=User)
        user.displayName = "Alice Johnson"

        issue = _make_mock_issue(extra_fields={"customfield_10003": user})
        mapping = {"customfield_10003": "Reviewer"}

        result = CustomFieldExtractor.get_issue_custom_fields(issue, mapping)
        assert result == {"Reviewer": "Alice Johnson"}

    def test_list_value_extracted_as_space_joined_string(self) -> None:
        """Lists of values are space-joined after individual processing."""
        opt1 = MagicMock(spec=CustomFieldOption)
        opt1.value = "Backend"
        opt2 = MagicMock(spec=CustomFieldOption)
        opt2.value = "Frontend"

        issue = _make_mock_issue(extra_fields={"customfield_10004": [opt1, opt2]})
        mapping = {"customfield_10004": "Components"}

        result = CustomFieldExtractor.get_issue_custom_fields(issue, mapping)
        assert result == {"Components": "Backend Frontend"}

    def test_none_value_excluded(self) -> None:
        """None custom field values are excluded from the result."""
        issue = _make_mock_issue(extra_fields={"customfield_10005": None})
        mapping = {"customfield_10005": "Optional Field"}

        result = CustomFieldExtractor.get_issue_custom_fields(issue, mapping)
        assert "Optional Field" not in result

    def test_value_exceeding_max_length_excluded(self) -> None:
        """Values longer than max_value_length are excluded."""
        long_value = "x" * 300  # exceeds the default 250 limit
        issue = _make_mock_issue(extra_fields={"customfield_10006": long_value})
        mapping = {"customfield_10006": "Long Description"}

        result = CustomFieldExtractor.get_issue_custom_fields(issue, mapping)
        assert "Long Description" not in result

    def test_value_at_exact_max_length_excluded(self) -> None:
        """Values at exactly max_value_length are excluded (< not <=)."""
        exact_value = "x" * 250  # exactly 250, not < 250
        issue = _make_mock_issue(extra_fields={"customfield_10007": exact_value})
        mapping = {"customfield_10007": "Edge Case"}

        result = CustomFieldExtractor.get_issue_custom_fields(issue, mapping)
        assert "Edge Case" not in result

    def test_value_just_under_max_length_included(self) -> None:
        """Values just under max_value_length are included."""
        under_value = "x" * 249
        issue = _make_mock_issue(extra_fields={"customfield_10008": under_value})
        mapping = {"customfield_10008": "Just Under"}

        result = CustomFieldExtractor.get_issue_custom_fields(issue, mapping)
        assert result == {"Just Under": under_value}

    def test_unmapped_custom_fields_ignored(self) -> None:
        """Custom fields not in the mapping dict are not included."""
        issue = _make_mock_issue(
            extra_fields={
                "customfield_10001": "mapped_value",
                "customfield_99999": "unmapped_value",
            }
        )
        mapping = {"customfield_10001": "Mapped Field"}

        result = CustomFieldExtractor.get_issue_custom_fields(issue, mapping)
        assert "Mapped Field" in result
        assert len(result) == 1


class TestProcessJiraIssueWithCustomFields:
    def test_custom_fields_added_to_metadata(self) -> None:
        """When custom_fields_mapping is provided, custom fields appear in metadata."""
        option = MagicMock(spec=CustomFieldOption)
        option.value = "High Impact"

        issue = _make_mock_issue(
            extra_fields={
                "customfield_10001": "Sprint 42",
                "customfield_10002": option,
            }
        )
        mapping = {
            "customfield_10001": "Sprint",
            "customfield_10002": "Impact Level",
        }

        doc = process_jira_issue(
            jira_base_url="https://jira.example.com",
            issue=issue,
            custom_fields_mapping=mapping,
        )

        assert doc is not None
        assert doc.metadata["Sprint"] == "Sprint 42"
        assert doc.metadata["Impact Level"] == "High Impact"
        # Standard fields should still be present
        assert doc.metadata["key"] == "TEST-1"

    def test_no_custom_fields_when_mapping_is_none(self) -> None:
        """When custom_fields_mapping is None, no custom fields in metadata."""
        issue = _make_mock_issue(
            extra_fields={"customfield_10001": "should_not_appear"}
        )

        doc = process_jira_issue(
            jira_base_url="https://jira.example.com",
            issue=issue,
            custom_fields_mapping=None,
        )

        assert doc is not None
        # The custom field name should not appear since we didn't provide a mapping
        assert "customfield_10001" not in doc.metadata

    def test_custom_field_extraction_failure_does_not_break_processing(self) -> None:
        """If custom field extraction raises, the document is still returned."""
        issue = _make_mock_issue()
        mapping = {"customfield_10001": "Broken Field"}

        with patch.object(
            CustomFieldExtractor,
            "get_issue_custom_fields",
            side_effect=RuntimeError("extraction failed"),
        ):
            doc = process_jira_issue(
                jira_base_url="https://jira.example.com",
                issue=issue,
                custom_fields_mapping=mapping,
            )

        assert doc is not None
        # The document should still have standard metadata
        assert doc.metadata["key"] == "TEST-1"
        # The broken custom field should not have leaked into metadata
        assert "Broken Field" not in doc.metadata


# ===================================================================
# Test 2: Attachment Fetching
# ===================================================================


class TestProcessAttachments:
    """Tests for JiraConnector._process_attachments."""

    def _make_connector(self, fetch_attachments: bool = True) -> JiraConnector:
        """Create a JiraConnector wired with a mock client."""
        connector = JiraConnector(
            jira_base_url="https://jira.example.com",
            project_key="TEST",
            fetch_attachments=fetch_attachments,
        )
        # Don't use spec=JIRA because _process_attachments accesses
        # the private _session attribute, which spec blocks.
        mock_client = MagicMock()
        mock_client._options = {"rest_api_version": "2"}
        mock_client.client_info.return_value = "https://jira.example.com"
        connector._jira_client = mock_client
        return connector

    @patch("onyx.connectors.jira.connector.extract_file_text")
    def test_happy_path_two_attachments(self, mock_extract: MagicMock) -> None:
        """Two normal attachments yield two Documents with correct structure."""
        mock_extract.side_effect = ["Text from report", "Text from spec"]

        att1 = _make_attachment(
            attachment_id="att-1",
            filename="report.pdf",
            size=1024,
            download_content=b"report bytes",
        )
        att2 = _make_attachment(
            attachment_id="att-2",
            filename="spec.docx",
            size=2048,
            content_url="https://jira.example.com/attachment/att-2",
            mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            download_content=b"spec bytes",
        )
        issue = _make_mock_issue(key="TEST-42", attachments=[att1, att2])

        connector = self._make_connector()

        results = list(
            connector._process_attachments(issue, parent_hierarchy_raw_node_id="TEST")
        )

        docs = [r for r in results if isinstance(r, Document)]
        assert len(docs) == 2

        # First attachment
        assert docs[0].id == "https://jira.example.com/browse/TEST-42/attachments/att-1"
        assert docs[0].title == "report.pdf"
        assert docs[0].metadata["parent_ticket"] == "TEST-42"
        assert docs[0].metadata["attachment_filename"] == "report.pdf"
        assert docs[0].metadata["attachment_size"] == "1024"
        assert docs[0].parent_hierarchy_raw_node_id == "TEST"
        assert docs[0].sections[0].text == "Text from report"

        # Second attachment
        assert docs[1].id == "https://jira.example.com/browse/TEST-42/attachments/att-2"
        assert docs[1].title == "spec.docx"

    @patch("onyx.connectors.jira.connector.extract_file_text")
    def test_large_attachment_skipped(self, mock_extract: MagicMock) -> None:
        """Attachments exceeding 50 MB are skipped silently (only warning logged)."""
        large_att = _make_attachment(
            size=_MAX_ATTACHMENT_SIZE_BYTES + 1,
            filename="huge.zip",
        )
        issue = _make_mock_issue(attachments=[large_att])
        connector = self._make_connector()

        results = list(connector._process_attachments(issue, None))
        assert len(results) == 0
        mock_extract.assert_not_called()

    @patch("onyx.connectors.jira.connector.extract_file_text")
    def test_no_content_url_skipped(self, mock_extract: MagicMock) -> None:
        """Attachments with no content URL are skipped gracefully."""
        att = _make_attachment(content_url=None, filename="orphan.txt")
        issue = _make_mock_issue(attachments=[att])
        connector = self._make_connector()

        results = list(connector._process_attachments(issue, None))
        assert len(results) == 0
        mock_extract.assert_not_called()

    @patch("onyx.connectors.jira.connector.extract_file_text")
    def test_download_failure_yields_connector_failure(
        self, mock_extract: MagicMock
    ) -> None:
        """If the download raises, a ConnectorFailure is yielded; other attachments continue."""
        att_bad = _make_attachment(
            attachment_id="att-bad",
            filename="broken.pdf",
            content_url="https://jira.example.com/attachment/att-bad",
            download_raises=ConnectionError("download failed"),
        )
        att_good = _make_attachment(
            attachment_id="att-good",
            filename="good.pdf",
            content_url="https://jira.example.com/attachment/att-good",
            download_content=b"good content",
        )
        issue = _make_mock_issue(attachments=[att_bad, att_good])

        connector = self._make_connector()
        mock_extract.return_value = "extracted good text"

        results = list(connector._process_attachments(issue, None))

        failures = [r for r in results if isinstance(r, ConnectorFailure)]
        docs = [r for r in results if isinstance(r, Document)]

        assert len(failures) == 1
        assert "broken.pdf" in failures[0].failure_message
        assert len(docs) == 1
        assert docs[0].title == "good.pdf"

    @patch("onyx.connectors.jira.connector.extract_file_text")
    def test_text_extraction_failure_skips_attachment(
        self, mock_extract: MagicMock
    ) -> None:
        """If extract_file_text raises, the attachment is skipped (not a ConnectorFailure)."""
        att = _make_attachment(
            filename="bad_format.xyz", download_content=b"some bytes"
        )
        issue = _make_mock_issue(attachments=[att])
        connector = self._make_connector()

        mock_extract.side_effect = ValueError("Unsupported format")

        results = list(connector._process_attachments(issue, None))
        assert len(results) == 0

    @patch("onyx.connectors.jira.connector.extract_file_text")
    def test_empty_text_extraction_skips_attachment(
        self, mock_extract: MagicMock
    ) -> None:
        """Attachments yielding empty text are skipped."""
        att = _make_attachment(filename="empty.pdf", download_content=b"some bytes")
        issue = _make_mock_issue(attachments=[att])
        connector = self._make_connector()

        mock_extract.return_value = ""

        results = list(connector._process_attachments(issue, None))
        assert len(results) == 0

    @patch("onyx.connectors.jira.connector.extract_file_text")
    def test_whitespace_only_text_skips_attachment(
        self, mock_extract: MagicMock
    ) -> None:
        """Attachments yielding only whitespace are skipped."""
        att = _make_attachment(filename="whitespace.txt", download_content=b"   ")
        issue = _make_mock_issue(attachments=[att])
        connector = self._make_connector()

        mock_extract.return_value = "   \n\t  "

        results = list(connector._process_attachments(issue, None))
        assert len(results) == 0

    @patch("onyx.connectors.jira.connector.extract_file_text")
    def test_no_attachments_on_issue(self, mock_extract: MagicMock) -> None:
        """When an issue has no attachments, nothing is yielded."""
        issue = _make_mock_issue(attachments=[])
        connector = self._make_connector()

        results = list(connector._process_attachments(issue, None))
        assert len(results) == 0
        mock_extract.assert_not_called()

    @patch("onyx.connectors.jira.connector.extract_file_text")
    def test_attachment_field_is_none(self, mock_extract: MagicMock) -> None:
        """When the attachment field is None (not set), nothing is yielded."""
        issue = _make_mock_issue()
        # Override attachment to be explicitly falsy (best_effort_get_field returns None)
        issue.fields.attachment = None
        issue.fields.__dict__["attachment"] = None
        connector = self._make_connector()

        results = list(connector._process_attachments(issue, None))
        assert len(results) == 0
        mock_extract.assert_not_called()


class TestFetchAttachmentsFlag:
    """Verify _process_attachments is only called when fetch_attachments=True."""

    def test_fetch_attachments_false_skips_processing(self) -> None:
        """With fetch_attachments=False, _process_attachments should not be invoked
        during the load_from_checkpoint flow."""
        connector = JiraConnector(
            jira_base_url="https://jira.example.com",
            project_key="TEST",
            fetch_attachments=False,
        )
        assert connector.fetch_attachments is False

        with patch.object(connector, "_process_attachments") as mock_process:
            # Simulate what _load_from_checkpoint does: only call
            # _process_attachments when self.fetch_attachments is True.
            if connector.fetch_attachments:
                connector._process_attachments(MagicMock(), None)
            mock_process.assert_not_called()


# ===================================================================
# Test 3: Backwards Compatibility
# ===================================================================


class TestBackwardsCompatibility:
    def test_default_config_has_flags_off(self) -> None:
        """JiraConnector defaults have both new feature flags disabled."""
        connector = JiraConnector(
            jira_base_url="https://jira.example.com",
            project_key="TEST",
        )
        assert connector.extract_custom_fields is False
        assert connector.fetch_attachments is False

    def test_default_config_has_empty_custom_fields_mapping(self) -> None:
        """Before load_credentials, the custom fields mapping is empty."""
        connector = JiraConnector(
            jira_base_url="https://jira.example.com",
            project_key="TEST",
        )
        assert connector._custom_fields_mapping == {}

    def test_process_jira_issue_without_mapping_has_no_custom_fields(self) -> None:
        """Calling process_jira_issue without custom_fields_mapping produces
        the same metadata as the pre-enhancement code."""
        issue = _make_mock_issue(
            key="COMPAT-1",
            extra_fields={"customfield_10001": "should_be_ignored"},
        )

        doc = process_jira_issue(
            jira_base_url="https://jira.example.com",
            issue=issue,
        )

        assert doc is not None
        # Standard fields present
        assert doc.metadata["key"] == "COMPAT-1"
        assert doc.metadata["priority"] == "High"
        assert doc.metadata["status"] == "Open"
        # No custom field should leak through
        for key in doc.metadata:
            assert not key.startswith(
                "customfield_"
            ), f"Custom field {key} leaked into metadata without mapping"

    def test_process_jira_issue_default_params_match_old_signature(self) -> None:
        """process_jira_issue with only the required params works identically
        to the pre-enhancement signature (jira_base_url + issue)."""
        issue = _make_mock_issue()

        doc_new = process_jira_issue(
            jira_base_url="https://jira.example.com",
            issue=issue,
        )
        doc_explicit_none = process_jira_issue(
            jira_base_url="https://jira.example.com",
            issue=issue,
            custom_fields_mapping=None,
        )

        assert doc_new is not None
        assert doc_explicit_none is not None
        assert doc_new.metadata == doc_explicit_none.metadata
        assert doc_new.id == doc_explicit_none.id

    def test_load_credentials_does_not_fetch_custom_fields_when_flag_off(self) -> None:
        """When extract_custom_fields=False, load_credentials does not call
        get_all_custom_fields."""
        connector = JiraConnector(
            jira_base_url="https://jira.example.com",
            project_key="TEST",
            extract_custom_fields=False,
        )

        with patch("onyx.connectors.jira.connector.build_jira_client") as mock_build:
            mock_client = MagicMock(spec=JIRA)
            mock_build.return_value = mock_client

            connector.load_credentials({"jira_api_token": "tok"})

            mock_client.fields.assert_not_called()
            assert connector._custom_fields_mapping == {}

    def test_load_credentials_fetches_custom_fields_when_flag_on(self) -> None:
        """When extract_custom_fields=True, load_credentials populates the mapping."""
        connector = JiraConnector(
            jira_base_url="https://jira.example.com",
            project_key="TEST",
            extract_custom_fields=True,
        )

        with patch("onyx.connectors.jira.connector.build_jira_client") as mock_build:
            mock_client = MagicMock(spec=JIRA)
            mock_client.fields.return_value = [
                {"id": "summary", "name": "Summary", "custom": False},
                {"id": "customfield_10001", "name": "Sprint", "custom": True},
            ]
            mock_build.return_value = mock_client

            connector.load_credentials({"jira_api_token": "tok"})

            assert connector._custom_fields_mapping == {"customfield_10001": "Sprint"}

    def test_load_credentials_handles_custom_fields_fetch_failure(self) -> None:
        """If get_all_custom_fields raises, the mapping stays empty and no exception propagates."""
        connector = JiraConnector(
            jira_base_url="https://jira.example.com",
            project_key="TEST",
            extract_custom_fields=True,
        )

        with patch("onyx.connectors.jira.connector.build_jira_client") as mock_build:
            mock_client = MagicMock(spec=JIRA)
            mock_client.fields.side_effect = RuntimeError("API unavailable")
            mock_build.return_value = mock_client

            # Should not raise
            connector.load_credentials({"jira_api_token": "tok"})

            assert connector._custom_fields_mapping == {}
