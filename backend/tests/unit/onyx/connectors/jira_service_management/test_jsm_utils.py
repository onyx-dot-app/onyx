from unittest.mock import MagicMock

from jira import JIRA

from onyx.connectors.jira_service_management.utils import (
    JsmFieldMap,
    build_jsm_attachment_doc_id,
    build_jsm_metadata,
    discover_jsm_fields,
    get_jsm_comment_strs,
    is_jsm_attachment_admissible,
)
from tests.unit.onyx.connectors.jira_service_management.conftest import (
    create_mock_attachment,
    create_mock_comment,
)


def _mock_issue_with_fields(raw_fields: dict) -> MagicMock:
    issue = MagicMock()
    issue.raw = {"fields": raw_fields}
    return issue


def test_discover_jsm_fields_maps_by_display_name() -> None:
    jira_client = MagicMock(spec=JIRA)
    jira_client.fields.return_value = [
        {"id": "customfield_10010", "name": "Customer Request Type"},
        {"id": "customfield_10002", "name": "Organizations"},
        {"id": "customfield_10003", "name": "Request participants"},
        {"id": "customfield_10999", "name": "Time to resolution"},
        {"id": "customfield_1", "name": "Sprint"},
    ]

    field_map = discover_jsm_fields(jira_client)

    assert field_map.customer_request_type == "customfield_10010"
    assert field_map.organizations == "customfield_10002"
    assert field_map.request_participants == "customfield_10003"


def test_discover_jsm_fields_server_names() -> None:
    # JSM Server/DC calls the customer request type field "Request Type"
    jira_client = MagicMock(spec=JIRA)
    jira_client.fields.return_value = [
        {"id": "customfield_10100", "name": "Request Type"},
    ]

    field_map = discover_jsm_fields(jira_client)

    assert field_map.customer_request_type == "customfield_10100"


def test_discover_jsm_fields_failure_returns_empty() -> None:
    jira_client = MagicMock(spec=JIRA)
    jira_client.fields.side_effect = RuntimeError("no perms")

    field_map = discover_jsm_fields(jira_client)

    assert field_map == JsmFieldMap()


def test_build_jsm_metadata_full() -> None:
    field_map = JsmFieldMap(
        customer_request_type="customfield_10010",
        organizations="customfield_10002",
        request_participants="customfield_10003",
    )
    issue = _mock_issue_with_fields(
        {
            "customfield_10010": {
                "requestType": {"id": "37", "name": "Get IT help"},
                "serviceDeskId": "1",
            },
            "customfield_10002": [
                {"id": "5", "name": "Acme Corp"},
                {"id": "6", "name": "Globex"},
            ],
            "customfield_10003": [
                {"accountId": "abc", "displayName": "Jane Customer"},
                {"accountId": "def", "displayName": "John Watcher"},
            ],
            "customfield_10999": {
                "id": "2",
                "name": "Time to resolution",
                "ongoingCycle": {"breached": True},
            },
            "customfield_10998": {
                "id": "1",
                "name": "Time to first response",
                "completedCycles": [{"breached": False}],
            },
        }
    )

    metadata = build_jsm_metadata(issue, field_map)

    assert metadata["customer_request_type"] == "Get IT help"
    assert metadata["organizations"] == ["Acme Corp", "Globex"]
    assert metadata["request_participants"] == ["Jane Customer", "John Watcher"]
    assert metadata["sla_status"] == [
        "Time to resolution: Breached",
        "Time to first response: Met",
    ]


def test_build_jsm_metadata_request_type_string_form() -> None:
    # Non-expanded JSM payloads carry the request type as
    # "serviceDeskId/requestTypeId"
    field_map = JsmFieldMap(customer_request_type="customfield_10010")
    issue = _mock_issue_with_fields({"customfield_10010": "1/37"})

    metadata = build_jsm_metadata(issue, field_map)

    assert metadata["customer_request_type"] == "1/37"


def test_build_jsm_metadata_missing_fields() -> None:
    field_map = JsmFieldMap(
        customer_request_type="customfield_10010",
        organizations="customfield_10002",
    )
    issue = _mock_issue_with_fields({})

    assert build_jsm_metadata(issue, field_map) == {}


def test_build_jsm_metadata_without_discovery() -> None:
    # Without discovered ids, SLA fields are still detected structurally
    issue = _mock_issue_with_fields(
        {
            "customfield_99999": {
                "name": "Resolution SLA",
                "ongoingCycle": {"breached": False},
            },
        }
    )

    metadata = build_jsm_metadata(issue, JsmFieldMap())

    assert metadata["sla_status"] == ["Resolution SLA: In Progress"]


def test_jsm_comments_exclude_internal_by_default() -> None:
    comments = [
        create_mock_comment("public reply", jsd_public=True),
        create_mock_comment("agent-only note", jsd_public=False),
        create_mock_comment("no flag behaves as public"),
    ]
    issue = MagicMock()
    issue.fields.comment.comments = comments

    result = get_jsm_comment_strs(issue)

    assert result == ["public reply", "no flag behaves as public"]


def test_jsm_comments_include_internal_when_enabled() -> None:
    comments = [
        create_mock_comment("public reply", jsd_public=True),
        create_mock_comment("agent-only note", jsd_public=False),
    ]
    issue = MagicMock()
    issue.fields.comment.comments = comments

    result = get_jsm_comment_strs(issue, include_internal_comments=True)

    assert result == ["public reply", "[Internal Note] agent-only note"]


def test_jsm_comments_server_internal_property() -> None:
    comment = create_mock_comment("dc internal note")
    comment.raw = {
        "body": "dc internal note",
        "properties": [{"key": "sd.public.comment", "value": {"internal": True}}],
    }
    issue = MagicMock()
    issue.fields.comment.comments = [comment]

    assert get_jsm_comment_strs(issue) == []
    assert get_jsm_comment_strs(issue, include_internal_comments=True) == [
        "[Internal Note] dc internal note"
    ]


def test_jsm_comments_email_blacklist() -> None:
    comments = [
        create_mock_comment("keep", author_email="a@example.com"),
        create_mock_comment("drop", author_email="blacklist@example.com"),
    ]
    issue = MagicMock()
    issue.fields.comment.comments = comments

    result = get_jsm_comment_strs(
        issue, comment_email_blacklist=("blacklist@example.com",)
    )

    assert result == ["keep"]


def test_jsm_attachment_admissible() -> None:
    assert is_jsm_attachment_admissible(
        create_mock_attachment(filename="report.pdf"), allow_images=False
    )
    assert is_jsm_attachment_admissible(
        create_mock_attachment(filename="data.csv", mime_type="text/csv"),
        allow_images=False,
    )
    # images require allow_images
    assert not is_jsm_attachment_admissible(
        create_mock_attachment(filename="screenshot.png", mime_type="image/png"),
        allow_images=False,
    )
    assert is_jsm_attachment_admissible(
        create_mock_attachment(filename="screenshot.png", mime_type="image/png"),
        allow_images=True,
    )
    # unsupported types rejected
    assert not is_jsm_attachment_admissible(
        create_mock_attachment(
            filename="virus.exe", mime_type="application/octet-stream"
        ),
        allow_images=True,
    )
    # oversized rejected
    assert not is_jsm_attachment_admissible(
        create_mock_attachment(size=100 * 1024 * 1024), allow_images=False
    )
    # missing filename rejected
    assert not is_jsm_attachment_admissible(
        {"id": "1", "mimeType": "application/pdf", "size": 10},
        allow_images=False,
    )


def test_build_jsm_attachment_doc_id() -> None:
    attachment = create_mock_attachment(attachment_id="12345")
    assert (
        build_jsm_attachment_doc_id("https://jira.example.com", attachment)
        == "https://jira.example.com/rest/api/3/attachment/content/12345"
    )

    attachment_no_content = {"id": "999", "filename": "f.pdf"}
    assert (
        build_jsm_attachment_doc_id("https://jira.example.com", attachment_no_content)
        == "https://jira.example.com/secure/attachment/999/"
    )

    assert (
        build_jsm_attachment_doc_id("https://jira.example.com", {"filename": "f.pdf"})
        is None
    )
