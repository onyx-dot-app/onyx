"""Group sync for Jira Service Management.

JSM uses the same Jira groups for permissions, so this is a thin alias of the
Jira group sync, keeping a source-specific import path like the other EE
permission modules.
"""

from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.jira.group_sync import jira_group_sync
from onyx.db.models import ConnectorCredentialPair


def jira_service_management_group_sync(
    tenant_id: str,
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    yield from jira_group_sync(tenant_id, cc_pair)
