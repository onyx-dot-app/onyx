from types import SimpleNamespace
from unittest.mock import MagicMock

from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
    JiraServiceManagementConnectorCheckpoint,
    process_jira_issue,
)
from onyx.connectors.jira_service_management.utils import (
    build_jira_url,
    extract_text_from_adf,
    get_comment_strs,
)
from onyx.connectors.registry import CONNECTOR_CLASS_MAP


def _make_mock_issue(
    key: str = "JSM-101",
    summary: str = "VPN access request",
    description: object = "User needs corporate VPN access.",
    updated: str = "2026-11-20T12:00:00.000+0000",
    project_key: str = "JSM",
    status_name: str = "Waiting for support",
    labels: list[str] | None = None,
    comments: list[tuple[str, object]] | None = None,
) -> SimpleNamespace:
    comment_objs = []
    for email, body in comments or []:
        comment_objs.append(
            SimpleNamespace(
                author=SimpleNamespace(emailAddress=email),
                body=body,
            )
        )
    return SimpleNamespace(
        key=key,
        fields=SimpleNamespace(
            summary=summary,
            description=description,
            updated=updated,
            project=SimpleNamespace(key=project_key),
            status=SimpleNamespace(name=status_name),
            issuetype=SimpleNamespace(name="Service Request"),
            priority=SimpleNamespace(name="High"),
            creator=SimpleNamespace(
                displayName="Alice Requester",
                emailAddress="alice@example.com",
            ),
            labels=labels or [],
            comment=SimpleNamespace(comments=comment_objs),
        ),
    )


def test_registry_registers_jira_service_management() -> None:
    mapping = CONNECTOR_CLASS_MAP[DocumentSource.JIRA_SERVICE_MANAGEMENT]
    assert (
        mapping.module_path
        == "onyx.connectors.jira_service_management.connector"
    )
    assert mapping.class_name == "JiraServiceManagementConnector"
    assert mapping.config_class is JiraServiceManagementConnectorConfig


def test_extract_text_from_adf_and_comments() -> None:
    adf = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "text", "text": "Service Desk"},
                ],
            }
        ],
    }
    assert extract_text_from_adf(adf) == "Hello Service Desk"

    issue = _make_mock_issue(
        description=adf,
        comments=[
            ("bot@example.com", "Automated triage"),
            ("agent@example.com", {"type": "doc", "content": [{"type": "text", "text": "Resolved VPN profile"}]}),
        ],
    )
    filtered = get_comment_strs(issue, comment_email_blacklist=["bot@example.com"])
    assert filtered == ["Resolved VPN profile"]


def test_process_jira_issue_and_label_skip() -> None:
    issue = _make_mock_issue(labels=["internal-secret"])
    assert (
        process_jira_issue(
            "https://acme.atlassian.net",
            issue,  # type: ignore[arg-type]
            labels_to_skip=["internal-secret"],
        )
        is None
    )

    doc = process_jira_issue(
        "https://acme.atlassian.net",
        _make_mock_issue(comments=[("agent@example.com", "Ticket assigned")]),  # type: ignore[arg-type]
        labels_to_skip=[],
    )
    assert doc is not None
    assert doc.source == DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert doc.id == "https://acme.atlassian.net/browse/JSM-101"
    assert "User needs corporate VPN access." in doc.sections[0].text
    assert "Comment: Ticket assigned" in doc.sections[0].text
    assert doc.metadata["project"] == "JSM"
    assert doc.metadata["status"] == "Waiting for support"


def test_connector_checkpoint_loading_and_slim_docs() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://acme.atlassian.net/",
        project_key="JSM",
        batch_size=2,
        labels_to_skip=["skip-me"],
    )
    mock_client = MagicMock()
    mock_client.search_issues.return_value = [
        _make_mock_issue(key="JSM-1", summary="First request"),
        _make_mock_issue(key="JSM-2", summary="Skipped request", labels=["skip-me"]),
    ]
    connector._jira_client = mock_client

    checkpoint = JiraServiceManagementConnectorCheckpoint(offset=0, has_more=True)
    gen = connector.load_from_checkpoint(1700000000, 1700003600, checkpoint)
    yielded = []
    try:
        while True:
            yielded.append(next(gen))
    except StopIteration as stop:
        next_cp = stop.value

    assert len(yielded) == 1
    assert yielded[0].id == build_jira_url("https://acme.atlassian.net", "JSM-1")
    assert next_cp.offset == 2
    assert next_cp.has_more is True

    slim_batches = list(connector.retrieve_all_slim_docs_perm_sync())
    assert len(slim_batches) == 1
    assert [d.id for d in slim_batches[0]] == [
        "https://acme.atlassian.net/browse/JSM-1"
    ]
