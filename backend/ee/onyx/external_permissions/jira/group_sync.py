from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.db.models import ConnectorCredentialPair


def jira_group_sync(
    tenant_id: str,
    cc_pair: ConnectorCredentialPair,
) -> list[ExternalUserGroup]: ...
