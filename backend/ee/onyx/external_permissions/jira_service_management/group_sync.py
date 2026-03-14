from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.jira.group_sync import (
    _jira_group_sync_impl,
)
from onyx.db.models import ConnectorCredentialPair


def jira_service_management_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    """Sync Jira groups for a JSM connector.

    Reads ``jira_service_management_base_url`` from the connector config
    and delegates to the shared group-sync implementation.
    """
    jira_base_url = cc_pair.connector.connector_specific_config.get(
        "jira_service_management_base_url", ""
    )
    if not jira_base_url:
        raise ValueError(
            "No jira_service_management_base_url found in connector config"
        )

    yield from _jira_group_sync_impl(cc_pair, jira_base_url)
