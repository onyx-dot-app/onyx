from ee.onyx.external_permissions.jira.doc_sync import (
    jira_service_management_doc_sync,
)
from ee.onyx.external_permissions.jira.group_sync import jira_group_sync
from ee.onyx.external_permissions.sync_params import (
    check_if_valid_sync_source,
    get_all_cc_pair_agnostic_group_sync_sources,
    get_source_perm_sync_config,
    source_requires_doc_sync,
    source_requires_external_group_sync,
)
from onyx.configs.constants import DocumentSource


def test_jira_service_management_supports_permission_sync() -> None:
    source = DocumentSource.JIRA_SERVICE_MANAGEMENT

    assert check_if_valid_sync_source(source)
    assert source_requires_doc_sync(source)
    assert source_requires_external_group_sync(source)
    assert source in get_all_cc_pair_agnostic_group_sync_sources()


def test_jira_service_management_uses_its_own_doc_sync() -> None:
    """The doc sync must build Service Management document ids."""
    sync_config = get_source_perm_sync_config(
        DocumentSource.JIRA_SERVICE_MANAGEMENT,
    )

    assert sync_config is not None
    assert sync_config.doc_sync_config is not None
    assert sync_config.doc_sync_config.doc_sync_func is jira_service_management_doc_sync
    assert sync_config.group_sync_config is not None
    assert sync_config.group_sync_config.group_sync_func is jira_group_sync
