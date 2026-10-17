"""Regression tests for JiraSourceOperations raw-JSON issue payloads."""

from onyx.connectors.jira_service_management.utils import (
    JsmFieldMap,
    build_jsm_metadata,
    get_jsm_comment_strs,
)

REQUEST_FIELD = "customfield_10010"
ORGANIZATIONS_FIELD = "customfield_10001"


def _raw_issue() -> dict:
    return {
        "key": "HELP-101",
        "fields": {
            REQUEST_FIELD: {"requestType": {"name": "Get IT help"}},
            ORGANIZATIONS_FIELD: [
                {"id": "1", "name": "Example Org"},
            ],
            "customfield_10020": {
                "name": "Time to first response",
                "completedCycles": [{"breached": False}],
            },
            "comment": {
                "comments": [
                    {
                        "author": {"emailAddress": "customer@example.com"},
                        "body": "Public question",
                        "jsdPublic": True,
                    },
                    {
                        "author": {"emailAddress": "agent@example.com"},
                        "body": "Private escalation",
                        "jsdPublic": False,
                    },
                    {
                        "author": {"emailAddress": "ignored@example.com"},
                        "body": "Ignore me",
                        "jsdPublic": True,
                    },
                ]
            },
        },
    }


def test_raw_issue_jsm_metadata() -> None:
    metadata = build_jsm_metadata(
        _raw_issue(),
        JsmFieldMap(
            customer_request_type=REQUEST_FIELD,
            organizations=ORGANIZATIONS_FIELD,
        ),
    )
    assert metadata["customer_request_type"] == "Get IT help"
    assert metadata["organizations"] == ["Example Org"]
    assert metadata["sla_status"] == ["Time to first response: Met"]


def test_raw_issue_excludes_internal_notes_by_default() -> None:
    comments = get_jsm_comment_strs(
        _raw_issue(), comment_email_blacklist=("ignored@example.com",)
    )
    assert comments == ["Public question"]


def test_raw_issue_includes_labeled_internal_notes_only_when_enabled() -> None:
    comments = get_jsm_comment_strs(
        _raw_issue(),
        comment_email_blacklist=("ignored@example.com",),
        include_internal_comments=True,
    )
    assert comments == ["Public question", "[Internal Note] Private escalation"]


def test_raw_issue_malformed_comments_fail_closed() -> None:
    malformed = {"fields": {"comment": {"comments": "not a list"}}}
    assert get_jsm_comment_strs(malformed) == []
    assert get_jsm_comment_strs({"fields": None}) == []
