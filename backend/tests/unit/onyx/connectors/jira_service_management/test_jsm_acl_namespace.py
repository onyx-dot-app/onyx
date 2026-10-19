"""Full-index JSM attachment ACLs match the source namespace used by sync."""

from unittest.mock import patch

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.connectors.jira_service_management.connector import (
    JiraServiceManagementConnector,
)


def test_jsm_prefixed_groups_match_permission_sync_namespace() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net", project_key="HELP"
    )
    access = ExternalAccess(
        external_user_emails={"worker@example.com"},
        external_user_group_ids={"OnCall"},
        is_public=False,
    )
    with patch(
        "onyx.connectors.jira.connector.JiraConnector._get_project_permissions",
        return_value=access,
    ) as original:
        prefixed = connector._get_project_permissions("HELP", add_prefix=True)
        plain = connector._get_project_permissions("HELP", add_prefix=False)

    assert prefixed is not None
    assert prefixed.external_user_group_ids == {"jira_service_management_oncall"}
    assert prefixed.external_user_emails == {"worker@example.com"}
    assert not prefixed.is_public
    assert plain == access
    assert original.call_count == 2
    original.assert_any_call("HELP", add_prefix=False)
    assert connector.document_source == DocumentSource.JIRA_SERVICE_MANAGEMENT


def test_jsm_missing_ee_access_is_preserved_as_missing() -> None:
    connector = JiraServiceManagementConnector(
        jira_base_url="https://example.atlassian.net", project_key="HELP"
    )
    with patch(
        "onyx.connectors.jira.connector.JiraConnector._get_project_permissions",
        return_value=None,
    ):
        assert connector._get_project_permissions("HELP", add_prefix=True) is None
