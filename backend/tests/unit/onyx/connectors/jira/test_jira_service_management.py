from typing import Any

from onyx.connectors.jira.connector import process_jira_issue
from onyx.connectors.jira.utils import get_jsm_request_type


def _issue(jsm: bool = True) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "description": "Printer is broken",
        "summary": "Printer",
        "created": "2024-01-01T00:00:00.000+0000",
        "updated": "2024-01-02T00:00:00.000+0000",
        "status": {
            "name": "Waiting for support",
            "statusCategory": {"name": "In Progress"},
        },
        "project": {"key": "HELP", "name": "Help"},
        "comment": {
            "comments": [
                {"body": "public reply", "jsdPublic": True},
                {"body": "internal note", "jsdPublic": False},
                {"body": "plain jira comment"},
            ]
        },
    }
    if jsm:
        fields["customfield_10010"] = {
            "requestType": {"name": "Get IT help"},
            "currentStatus": {"status": "Waiting for support"},
        }
        fields["customfield_10011"] = "unrelated"
    return {"key": "HELP-1", "fields": fields}


def test_jsm_issue_has_request_type_and_status_category() -> None:
    doc = process_jira_issue("https://x.atlassian.net", _issue())
    assert doc is not None
    assert doc.metadata["request_type"] == "Get IT help"
    assert doc.metadata["status_category"] == "In Progress"


def test_plain_jira_issue_has_no_request_type() -> None:
    issue = _issue(jsm=False)
    assert get_jsm_request_type(issue) is None
    doc = process_jira_issue("https://x.atlassian.net", issue)
    assert doc is not None
    assert "request_type" not in doc.metadata


def test_internal_comments_included_by_default() -> None:
    doc = process_jira_issue("https://x.atlassian.net", _issue())
    assert doc is not None
    text = doc.sections[0].text or ""
    assert "internal note" in text
    assert "public reply" in text


def test_internal_comments_excluded_when_flag_on() -> None:
    doc = process_jira_issue(
        "https://x.atlassian.net", _issue(), exclude_internal_comments=True
    )
    assert doc is not None
    text = doc.sections[0].text or ""
    assert "internal note" not in text
    assert "public reply" in text
    assert "plain jira comment" in text
