"""JSM permissions must use JSM sources, not inherit plain Jira IDs."""

from unittest.mock import MagicMock, patch

from ee.onyx.external_permissions.jira_service_management.doc_sync import (
    jsm_doc_sync,
)
from ee.onyx.external_permissions.sync_params import (
    get_source_perm_sync_config,
    source_requires_doc_sync,
    source_requires_external_group_sync,
    source_should_fetch_permissions_during_indexing,
)
from onyx.configs.constants import DocumentSource


def test_jsm_has_durable_doc_and_group_sync_registration() -> None:
    source = DocumentSource.JIRA_SERVICE_MANAGEMENT
    assert source_requires_doc_sync(source)
    assert source_requires_external_group_sync(source)
    assert source_should_fetch_permissions_during_indexing(source)
    config = get_source_perm_sync_config(source)
    assert config is not None
    assert config.doc_sync_config is not None
    assert config.doc_sync_config.initial_index_should_sync
    assert config.group_sync_config is not None


def test_jsm_doc_sync_uses_jsm_connector_and_correct_source() -> None:
    cc_pair = MagicMock()
    cc_pair.connector.source = DocumentSource.JIRA_SERVICE_MANAGEMENT
    cc_pair.connector.connector_specific_config = {
        "jira_base_url": "https://example.atlassian.net",
        "project_key": "HELP",
        "include_attachments": True,
    }
    with (
        patch(
            "ee.onyx.external_permissions.jira_service_management.doc_sync."
            "JiraServiceManagementConnector"
        ) as connector_class,
        patch(
            "ee.onyx.external_permissions.jira_service_management.doc_sync."
            "build_connector_kwargs",
            return_value=cc_pair.connector.connector_specific_config,
        ) as build_kwargs,
        patch(
            "ee.onyx.external_permissions.jira_service_management.doc_sync."
            "credential_json",
            return_value={"jira_api_token": "secret"},
        ),
        patch(
            "ee.onyx.external_permissions.jira_service_management.doc_sync."
            "generic_doc_sync",
            return_value=iter(["synthetic-result"]),
        ) as generic,
    ):
        assert list(jsm_doc_sync(cc_pair, MagicMock(), MagicMock())) == [
            "synthetic-result"
        ]

    connector_class.assert_called_once_with(
        jira_base_url="https://example.atlassian.net",
        project_key="HELP",
        include_attachments=True,
    )
    build_kwargs.assert_called_once_with(
        DocumentSource.JIRA_SERVICE_MANAGEMENT,
        cc_pair.connector.connector_specific_config,
    )
    connector_class.return_value.load_credentials.assert_called_once_with(
        {"jira_api_token": "secret"}
    )
    assert (
        generic.call_args.kwargs["doc_source"] == DocumentSource.JIRA_SERVICE_MANAGEMENT
    )
    assert generic.call_args.kwargs["slim_connector"] == connector_class.return_value
