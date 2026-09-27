from typing import Any
from unittest.mock import MagicMock

import pytest
from jira import JIRA
from jira.exceptions import JIRAError
from jira.resources import Issue

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


@pytest.fixture
def jsm_connector() -> JiraServiceManagementConnector:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="SUP",
        jql_query="status = Open",
        comment_email_blacklist=["skip@example.com"],
        labels_to_skip=[],
    )
    connector._jira_client = MagicMock(spec=JIRA)
    return connector


def test_jql_filter_cannot_expand_past_selected_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    query = jsm_connector._get_jql_query(1, 2)

    assert query == (
        'project = "SUP" AND (status = Open) AND updated >= 1000 AND updated <= 2000'
    )


def test_public_comments_use_jira_service_management_api_and_paginate(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._jira_client is not None
    jira_client: Any = jsm_connector._jira_client
    jira_client._get_json.side_effect = [
        {
            "values": [
                {
                    "public": True,
                    "body": "Public reply",
                    "author": {"emailAddress": "customer@example.com"},
                },
                {"public": False, "body": "Internal note"},
            ],
            "isLastPage": False,
        },
        {
            "values": [
                {
                    "public": True,
                    "body": "Filtered reply",
                    "author": {"emailAddress": "skip@example.com"},
                },
                {
                    "public": True,
                    "body": {
                        "type": "doc",
                        "content": [
                            {
                                "type": "paragraph",
                                "content": [{"type": "text", "text": "ADF reply"}],
                            }
                        ],
                    },
                },
            ],
            "isLastPage": True,
        },
    ]
    issue = MagicMock()
    issue.key = "SUP-1"

    assert jsm_connector._get_public_comment_texts(issue) == [
        "Public reply",
        "ADF reply",
    ]

    first_call, second_call = jira_client._get_json.call_args_list
    assert first_call.kwargs["path"] == "request/SUP-1/comment"
    assert first_call.kwargs["base"] == "{server}/rest/servicedeskapi/{path}"
    assert first_call.kwargs["params"] == {
        "public": True,
        "start": 0,
        "limit": 50,
    }
    assert second_call.kwargs["params"]["start"] == 2


def test_fallback_only_accepts_comments_explicitly_marked_public(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._jira_client is not None
    jira_client: Any = jsm_connector._jira_client
    jira_client._get_json.side_effect = JIRAError(status_code=404)

    issue = MagicMock(spec=Issue)
    issue.key = "SUP-2"
    issue.fields = MagicMock()
    public_comment = MagicMock()
    public_comment.raw = {"jsdPublic": True, "body": "Public fallback"}
    public_comment.body = "Public fallback"
    public_comment.author.emailAddress = "customer@example.com"
    internal_comment = MagicMock()
    internal_comment.raw = {"jsdPublic": False}
    internal_comment.body = "Internal fallback"
    internal_comment.author.emailAddress = "agent@example.com"
    unknown_visibility_comment = MagicMock()
    unknown_visibility_comment.raw = {}
    unknown_visibility_comment.body = "Unknown visibility"
    unknown_visibility_comment.author.emailAddress = "agent@example.com"
    issue.fields.comment.comments = [
        public_comment,
        internal_comment,
        unknown_visibility_comment,
    ]

    assert jsm_connector._get_public_comment_texts(issue) == ["Public fallback"]


def test_public_fallback_handles_hidden_author_email_and_adf(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._jira_client is not None
    jira_client: Any = jsm_connector._jira_client
    jira_client._get_json.side_effect = JIRAError(status_code=404)
    issue = Issue(
        options={"server": "https://jira.example.com", "rest_api_version": "2"},
        session=MagicMock(),
        raw={
            "key": "SUP-4",
            "fields": {
                "comment": {
                    "comments": [
                        {
                            "self": "https://jira.example.com/rest/api/2/issue/SUP-4/comment/1",
                            "jsdPublic": True,
                            "body": "Public reply with hidden email",
                            "author": {
                                "accountId": "customer",
                                "displayName": "Customer",
                            },
                        },
                        {
                            "self": "https://jira.example.com/rest/api/2/issue/SUP-4/comment/2",
                            "jsdPublic": True,
                            "body": "Public reply without author",
                        },
                        {
                            "self": "https://jira.example.com/rest/api/2/issue/SUP-4/comment/3",
                            "jsdPublic": True,
                            "body": "Blocked author",
                            "author": {"emailAddress": "skip@example.com"},
                        },
                        {
                            "self": "https://jira.example.com/rest/api/2/issue/SUP-4/comment/4",
                            "jsdPublic": False,
                            "body": "Internal note",
                        },
                        {
                            "self": "https://jira.example.com/rest/api/2/issue/SUP-4/comment/5",
                            "body": "Unknown visibility",
                        },
                        {
                            "self": "https://jira.example.com/rest/api/2/issue/SUP-4/comment/6",
                            "jsdPublic": "true",
                            "body": "Invalid visibility",
                        },
                        {
                            "self": "https://jira.example.com/rest/api/2/issue/SUP-4/comment/7",
                            "jsdPublic": True,
                            "body": {
                                "type": "doc",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {"type": "text", "text": "Public ADF reply"}
                                        ],
                                    }
                                ],
                            },
                        },
                    ]
                }
            },
        },
    )

    assert jsm_connector._get_public_comment_texts(issue) == [
        "Public reply with hidden email",
        "Public reply without author",
        "Public ADF reply",
    ]


@pytest.mark.parametrize("status_code", [401, 403, 429, 500, 503])
@pytest.mark.parametrize("after_first_page", [False, True])
def test_comment_api_failure_does_not_return_incomplete_comments(
    jsm_connector: JiraServiceManagementConnector,
    status_code: int,
    after_first_page: bool,
) -> None:
    assert jsm_connector._jira_client is not None
    jira_client: Any = jsm_connector._jira_client
    error = JIRAError(status_code=status_code)
    responses: list[Any] = []
    if after_first_page:
        responses.append(
            {
                "values": [{"public": True, "body": "First page reply"}],
                "isLastPage": False,
            }
        )
    responses.append(error)
    jira_client._get_json.side_effect = responses
    issue = MagicMock(spec=Issue)
    issue.key = "SUP-5"

    with pytest.raises(JIRAError) as raised:
        jsm_connector._get_public_comment_texts(issue)
    assert raised.value is error


def test_later_page_not_found_does_not_use_fallback(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._jira_client is not None
    jira_client: Any = jsm_connector._jira_client
    error = JIRAError(status_code=404)
    jira_client._get_json.side_effect = [
        {
            "values": [{"public": True, "body": "First page reply"}],
            "isLastPage": False,
        },
        error,
    ]
    issue = MagicMock(spec=Issue)
    issue.key = "SUP-6"

    with pytest.raises(JIRAError) as raised:
        jsm_connector._get_public_comment_texts(issue)
    assert raised.value is error


@pytest.mark.parametrize("response", [None, {"unexpected": []}])
def test_malformed_comment_response_is_not_an_empty_success(
    jsm_connector: JiraServiceManagementConnector, response: Any
) -> None:
    assert jsm_connector._jira_client is not None
    jira_client: Any = jsm_connector._jira_client
    jira_client._get_json.return_value = response
    issue = MagicMock(spec=Issue)
    issue.key = "SUP-7"

    with pytest.raises(ValueError, match="JSM comment response"):
        jsm_connector._get_public_comment_texts(issue)


def test_process_issue_uses_jira_service_management_source_and_public_comments(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._jira_client is not None
    jira_client: Any = jsm_connector._jira_client
    jira_client._get_json.return_value = {
        "values": [
            {
                "public": True,
                "body": "Customer reply",
            },
            {
                "public": False,
                "body": "Private agent note",
            },
        ],
        "isLastPage": True,
    }
    issue = MagicMock(spec=Issue)
    issue.key = "SUP-3"
    issue.fields = MagicMock()
    issue.fields.summary = "Cannot sign in"
    issue.fields.description = "The customer cannot sign in."
    issue.fields.labels = []
    issue.fields.created = "2026-09-01T00:00:00.000+0000"
    issue.fields.updated = "2026-09-01T01:00:00.000+0000"
    issue.fields.project.key = "SUP"
    issue.fields.project.name = "Support"
    issue.fields.parent = None
    issue.fields.reporter = None
    issue.fields.assignee = None
    issue.fields.priority = None
    issue.fields.status = None
    issue.fields.resolution = None
    issue.fields.duedate = None
    issue.fields.issuetype = None
    issue.fields.resolutiondate = None

    document = jsm_connector._process_issue(issue)

    assert document is not None
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    text = document.sections[0].text
    assert text is not None
    assert "Customer reply" in text
    assert "Private agent note" not in text


def test_validation_rejects_a_non_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._jira_client is not None
    jira_client: Any = jsm_connector._jira_client
    jira_client.project.return_value.raw = {"projectTypeKey": "software"}

    with pytest.raises(ConnectorValidationError, match="not a Jira Service Management"):
        jsm_connector.validate_connector_settings()


def test_validation_requires_a_service_desk_project_key() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="",
    )
    connector._jira_client = MagicMock(spec=JIRA)

    with pytest.raises(ConnectorValidationError, match="project key is required"):
        connector.validate_connector_settings()
