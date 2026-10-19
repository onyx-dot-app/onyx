from typing import Any
from unittest.mock import create_autospec, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.credentials_provider import OnyxStaticCredentialsProvider
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.source_operations import JiraApiError, JiraSourceOperations
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
    connector._source_operations = create_autospec(JiraSourceOperations, instance=True)
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
    assert jsm_connector._source_operations is not None
    gateway: Any = jsm_connector._source_operations
    gateway.get_request_comments.side_effect = [
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
    issue: dict[str, Any] = {"key": "SUP-1"}

    assert jsm_connector._get_public_comment_texts(issue) == [
        "Public reply",
        "ADF reply",
    ]

    first_call, second_call = gateway.get_request_comments.call_args_list
    assert first_call.kwargs == {"issue_key": "SUP-1", "start": 0, "limit": 50}
    assert second_call.kwargs == {"issue_key": "SUP-1", "start": 2, "limit": 50}


def test_fallback_only_accepts_comments_explicitly_marked_public(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._source_operations is not None
    gateway: Any = jsm_connector._source_operations
    gateway.get_request_comments.side_effect = JiraApiError(
        "Synthetic response", text=None, status_code=404
    )

    issue = {
        "key": "SUP-2",
        "fields": {
            "comment": {
                "comments": [
                    {
                        "jsdPublic": True,
                        "body": "Public fallback",
                        "author": {"emailAddress": "customer@example.com"},
                    },
                    {"jsdPublic": False, "body": "Internal fallback"},
                    {"body": "Unknown visibility"},
                ]
            }
        },
    }

    assert jsm_connector._get_public_comment_texts(issue) == ["Public fallback"]


def test_public_fallback_handles_hidden_author_email_and_adf(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._source_operations is not None
    gateway: Any = jsm_connector._source_operations
    gateway.get_request_comments.side_effect = JiraApiError(
        "Synthetic response", text=None, status_code=404
    )
    issue: dict[str, Any] = {
        "key": "SUP-4",
        "fields": {
            "comment": {
                "comments": [
                    {
                        "self": "https://jira.example.com/rest/api/2/issue/SUP-4/comment/1",
                        "jsdPublic": True,
                        "body": "Public reply with hidden email",
                        "author": {"accountId": "customer", "displayName": "Customer"},
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
    }

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
    assert jsm_connector._source_operations is not None
    gateway: Any = jsm_connector._source_operations
    error = JiraApiError("Synthetic response", text=None, status_code=status_code)
    responses: list[Any] = []
    if after_first_page:
        responses.append(
            {
                "values": [{"public": True, "body": "First page reply"}],
                "isLastPage": False,
            }
        )
    responses.append(error)
    gateway.get_request_comments.side_effect = responses
    issue: dict[str, Any] = {"key": "SUP-5"}

    with pytest.raises(JiraApiError) as raised:
        jsm_connector._get_public_comment_texts(issue)
    assert raised.value is error


def test_later_page_not_found_does_not_use_fallback(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._source_operations is not None
    gateway: Any = jsm_connector._source_operations
    error = JiraApiError("Synthetic response", text=None, status_code=404)
    gateway.get_request_comments.side_effect = [
        {
            "values": [{"public": True, "body": "First page reply"}],
            "isLastPage": False,
        },
        error,
    ]
    issue: dict[str, Any] = {"key": "SUP-6"}

    with pytest.raises(JiraApiError) as raised:
        jsm_connector._get_public_comment_texts(issue)
    assert raised.value is error


@pytest.mark.parametrize("response", [None, {"unexpected": []}])
def test_malformed_comment_response_is_not_an_empty_success(
    jsm_connector: JiraServiceManagementConnector, response: Any
) -> None:
    assert jsm_connector._source_operations is not None
    gateway: Any = jsm_connector._source_operations
    gateway.get_request_comments.return_value = response
    issue: dict[str, Any] = {"key": "SUP-7"}

    with pytest.raises(ValueError, match="JSM comment response"):
        jsm_connector._get_public_comment_texts(issue)


def test_process_issue_uses_jira_service_management_source_and_public_comments(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._source_operations is not None
    gateway: Any = jsm_connector._source_operations
    gateway.get_request_comments.return_value = {
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
    issue: dict[str, Any] = {
        "key": "SUP-3",
        "fields": {
            "summary": "Cannot sign in",
            "description": "The customer cannot sign in.",
            "labels": [],
            "created": "2026-09-01T00:00:00.000+0000",
            "updated": "2026-09-01T01:00:00.000+0000",
            "project": {"key": "SUP", "name": "Support"},
            "comment": {"comments": [{"body": "Unfiltered private comment"}]},
        },
    }

    document = jsm_connector._process_issue(issue)

    assert document is not None
    assert document.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    text = document.sections[0].text
    assert text is not None
    assert "Customer reply" in text
    assert "Private agent note" not in text
    assert "Unfiltered private comment" not in text
    assert document.title == "SUP-3 Cannot sign in"
    assert document.doc_updated_at is not None


def test_validation_rejects_a_non_service_desk_project(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._source_operations is not None
    gateway: Any = jsm_connector._source_operations
    gateway.get_project.return_value = {"projectTypeKey": "software"}

    with pytest.raises(ConnectorValidationError, match="not a Jira Service Management"):
        jsm_connector.validate_connector_settings()


def test_validation_requires_a_service_desk_project_key() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com",
        project_key="",
    )
    connector._source_operations = create_autospec(JiraSourceOperations, instance=True)

    with pytest.raises(ConnectorValidationError, match="project key is required"):
        connector.validate_connector_settings()


def test_empty_public_comments_do_not_fall_back_to_raw_jira_comments(
    jsm_connector: JiraServiceManagementConnector,
) -> None:
    assert jsm_connector._source_operations is not None
    gateway: Any = jsm_connector._source_operations
    gateway.get_request_comments.return_value = {"values": [], "isLastPage": True}
    issue: dict[str, Any] = {
        "key": "SUP-8",
        "fields": {
            "summary": "Private ticket",
            "description": "Customer report",
            "labels": [],
            "updated": "2026-09-01T01:00:00.000+0000",
            "created": "2026-09-01T00:00:00.000+0000",
            "project": {"key": "SUP", "name": "Support"},
            "comment": {"comments": [{"body": "Private raw Jira comment"}]},
        },
    }
    document = jsm_connector._process_issue(issue)
    assert document is not None
    assert "Private raw Jira comment" not in (document.sections[0].text or "")


def test_load_credentials_uses_jsm_source_and_shared_gateway() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://jira.example.com/", project_key="SUP", scoped_token=True
    )
    credentials = {"jira_user_email": "test@example.com", "jira_api_token": "synthetic"}
    with patch(
        "onyx.connectors.jira_service_management.connector.OnyxStaticCredentialsProvider",
        wraps=OnyxStaticCredentialsProvider,
    ) as provider_factory:
        connector.load_credentials(credentials)
    provider_factory.assert_called_once_with(
        None, DocumentSource.JIRA_SERVICE_MANAGEMENT.value, credentials
    )
    gateway = connector.source_operations
    assert isinstance(gateway, JiraSourceOperations)
    assert gateway.credentials_provider.get_credentials() == credentials
    assert gateway.connector_specific_config == {
        "jira_base_url": "https://jira.example.com",
        "scoped_token": True,
    }
