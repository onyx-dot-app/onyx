"""Unit tests for the Jira Service Management (JSM) connector."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    JSMConnectorCheckpoint,
)
from onyx.connectors.models import ConnectorFailure, Document


def _mock_response(payload: dict[str, Any], status_code: int = 200) -> MagicMock:
    """Build a mocked ``requests.Response`` returning the supplied JSON dict."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _consume_checkpoint_step(
    connector: JiraServiceManagementConnector,
    start: float,
    end: float,
    checkpoint: JSMConnectorCheckpoint,
) -> tuple[list[Any], JSMConnectorCheckpoint]:
    """Consume one ``load_from_checkpoint`` generator call and capture its return value."""
    gen = connector.load_from_checkpoint(start=start, end=end, checkpoint=checkpoint)
    items: list[Any] = []
    while True:
        try:
            items.append(next(gen))
        except StopIteration as stop:
            return items, stop.value


def test_jsm_issue_to_document_parses_adf_and_comments() -> None:
    """Verify ADF body extraction, embedded comments, source, and ticket metadata."""
    connector = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key="ITSM",
    )
    sample_issue = {
        "key": "ITSM-42",
        "fields": {
            "summary": "VPN gateway unreachable from Huntsville enclave",
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "Users cannot connect to VPN."}
                        ],
                    }
                ],
            },
            "status": {"name": "In Progress"},
            "priority": {"name": "High"},
            "customfield_10010": {"requestType": {"name": "Incident"}},
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "SecOps Engineer"},
                        "body": "Restarted wireguard interface wg0.",
                    }
                ],
                "startAt": 0,
                "total": 1,
            },
            "updated": "2026-11-08T18:00:00.000+0000",
        },
    }
    doc = connector._issue_to_document(sample_issue)
    assert doc.id == "jsm:ITSM-42"
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert "VPN gateway unreachable" in doc.semantic_identifier
    assert "Description:\nUsers cannot connect to VPN." in doc.sections[0].text
    assert "Restarted wireguard interface wg0." in doc.sections[0].text
    assert doc.metadata["status"] == "In Progress"
    assert doc.metadata["request_type"] == "Incident"
    assert doc.metadata["priority"] == "High"


def test_jsm_validate_checkpoint_json_roundtrip() -> None:
    """Verify ``validate_checkpoint_json`` deserializes persisted checkpoint state."""
    connector = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key="ITSM",
    )
    initial = JSMConnectorCheckpoint(
        has_more=True,
        next_page_token="token-page-2",
        seen_issue_keys=["ITSM-1"],
    )
    restored = connector.validate_checkpoint_json(initial.model_dump_json())
    assert restored == initial


def test_jsm_build_jql_escapes_project_key_and_uses_epoch_ms() -> None:
    """Verify JQL string-literal escaping and epoch-millisecond window bounds."""
    connector = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key='IT"SM\\OPS',
    )
    jql = connector._build_jql(start=1700000000.25, end=1700003600.75)
    assert jql == (
        'project = "IT\\"SM\\\\OPS" '
        "AND updated >= 1700000000250 "
        "AND updated <= 1700003600750 "
        "ORDER BY updated ASC"
    )


def test_jsm_rejects_empty_project_scope() -> None:
    """Verify empty ``project_key`` and ``service_desk_id`` are rejected."""
    connector = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key="   ",
    )
    with pytest.raises(ConnectorValidationError, match="project_key"):
        connector.validate_connector_settings()
    with pytest.raises(ConnectorValidationError, match="project_key"):
        connector._build_jql(start=100.0, end=200.0)


@patch("onyx.connectors.jira_service_management.connector.requests.get")
def test_jsm_resolves_project_key_from_service_desk_id(mock_get: MagicMock) -> None:
    """Verify ``service_desk_id`` scope resolves its backing Jira ``projectKey``."""
    mock_get.side_effect = [
        _mock_response({"version": "1001.0.0"}),
        _mock_response({"id": "7", "projectKey": "DESK"}),
    ]
    connector = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        service_desk_id="7",
    )
    connector.load_credentials(
        {"jira_user_email": "ops@example.com", "jira_api_token": "tok"}
    )
    connector.validate_connector_settings()
    assert connector._build_jql() == 'project = "DESK" ORDER BY updated ASC'


@patch("onyx.connectors.jira_service_management.connector.requests.get")
def test_jsm_load_from_checkpoint_paginates_and_yields_document_failure(
    mock_get: MagicMock,
) -> None:
    """Verify ``/rest/api/3/search/jql`` pagination, dedup, and ``ConnectorFailure``."""
    mock_get.side_effect = [
        _mock_response(
            {
                "issues": [
                    {
                        "key": "ITSM-1",
                        "fields": {
                            "summary": "Printer offline",
                            "description": "Floor 2 printer offline.",
                            "status": {"name": "Open"},
                            "priority": {"name": "Low"},
                        },
                    },
                    {
                        "key": "ITSM-BAD",
                        "fields": None,
                    },
                ],
                "nextPageToken": "cursor-2",
            }
        ),
        _mock_response(
            {
                "issues": [
                    {
                        "key": "ITSM-1",
                        "fields": {
                            "summary": "Duplicate across page boundary",
                            "description": "Should be deduplicated.",
                        },
                    },
                    {
                        "key": "ITSM-2",
                        "fields": {
                            "summary": "Laptop provisioning",
                            "description": "New hire laptop request.",
                            "status": {"name": "Resolved"},
                            "priority": {"name": "Medium"},
                        },
                    },
                ],
            }
        ),
    ]

    connector = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key="ITSM",
        batch_size=2,
    )
    connector.load_credentials(
        {"jira_user_email": "ops@example.com", "jira_api_token": "tok"}
    )

    page1_items, cp1 = _consume_checkpoint_step(
        connector,
        start=1700000000.0,
        end=1700000600.0,
        checkpoint=connector.build_dummy_checkpoint(),
    )
    assert mock_get.call_args_list[0].args[0] == (
        "https://example.atlassian.net/rest/api/3/search/jql"
    )
    assert cp1.has_more is True
    assert cp1.next_page_token == "cursor-2"
    assert len(page1_items) == 2
    assert isinstance(page1_items[0], Document)
    assert page1_items[0].id == "jsm:ITSM-1"

    failure = page1_items[1]
    assert isinstance(failure, ConnectorFailure)
    assert failure.failed_document is not None
    assert failure.failed_document.document_id == "jsm:ITSM-BAD"
    assert (
        failure.failed_document.document_link
        == "https://example.atlassian.net/browse/ITSM-BAD"
    )
    assert failure.exception is not None

    page2_items, cp2 = _consume_checkpoint_step(
        connector,
        start=1700000000.0,
        end=1700000600.0,
        checkpoint=cp1,
    )
    assert mock_get.call_args_list[1].kwargs["params"]["nextPageToken"] == "cursor-2"
    assert cp2.has_more is False
    assert cp2.next_page_token is None
    assert len(page2_items) == 1
    assert isinstance(page2_items[0], Document)
    assert page2_items[0].id == "jsm:ITSM-2"


@patch("onyx.connectors.jira_service_management.connector.requests.get")
def test_jsm_issue_comments_pagination_fetches_all_pages(mock_get: MagicMock) -> None:
    """Verify truncated embedded comments trigger paginated comment API fetches."""
    mock_get.side_effect = [
        _mock_response(
            {
                "comments": [
                    {"author": {"displayName": "Alice"}, "body": "First comment"},
                    {"author": {"displayName": "Bob"}, "body": "Second comment"},
                ],
                "total": 3,
            }
        ),
        _mock_response(
            {
                "comments": [
                    {"author": {"displayName": "Charlie"}, "body": "Third comment"},
                ],
                "total": 3,
            }
        ),
    ]
    connector = JiraServiceManagementConnector(
        base_url="https://example.atlassian.net",
        project_key="ITSM",
    )
    issue = {
        "key": "ITSM-77",
        "fields": {
            "summary": "Multi-comment incident",
            "description": "Initial report.",
            "comment": {
                "comments": [
                    {"author": {"displayName": "Alice"}, "body": "First comment"}
                ],
                "startAt": 0,
                "total": 3,
            },
        },
    }
    doc = connector._issue_to_document(issue)
    assert "Comment (Alice): First comment" in doc.sections[0].text
    assert "Comment (Bob): Second comment" in doc.sections[0].text
    assert "Comment (Charlie): Third comment" in doc.sections[0].text
    assert mock_get.call_count == 2


def test_jsm_config_matches_connector_init() -> None:
    """Verify ``JiraServiceManagementConnectorConfig`` validates connector kwargs."""
    cfg = JiraServiceManagementConnectorConfig(
        base_url="https://example.atlassian.net",
        project_key="ITSM",
    )
    assert cfg.batch_size == 50
    assert cfg.include_comments is True
    assert cfg.credential_binding_class() is None


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "ftp://example.atlassian.net",
        "https://user:pass@example.atlassian.net",
        "https://example.atlassian.net?foo=bar",
    ],
)
def test_jsm_rejects_invalid_base_url(bad_url: str) -> None:
    """Verify non-HTTP(S) or malformed base URLs raise ``ConnectorValidationError``."""
    connector = JiraServiceManagementConnector(
        base_url=bad_url,
        project_key="ITSM",
    )
    with pytest.raises(ConnectorValidationError, match="base_url"):
        connector.validate_connector_settings()
