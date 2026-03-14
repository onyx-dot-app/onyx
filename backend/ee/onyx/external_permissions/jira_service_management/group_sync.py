from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.jira.group_sync import (
    _get_group_member_emails,
)
from onyx.connectors.jira.utils import build_jira_client
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def jira_service_management_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    """Sync Jira groups for a JSM connector.

    Reads ``jira_service_management_base_url`` from the connector config
    (instead of ``jira_base_url``) and delegates to the shared group-member
    fetching logic from the Jira module.
    """
    jira_base_url = cc_pair.connector.connector_specific_config.get("jira_service_management_base_url", "")
    scoped_token = cc_pair.connector.connector_specific_config.get("scoped_token", False)

    if not jira_base_url:
        raise ValueError("No jira_service_management_base_url found in connector config")

    credential_json = cc_pair.credential.credential_json.get_value(apply_mask=False) if cc_pair.credential.credential_json else {}
    jira_client = build_jira_client(
        credentials=credential_json,
        jira_base=jira_base_url,
        scoped_token=scoped_token,
    )

    group_names = jira_client.groups()
    if not group_names:
        raise ValueError(f"No groups found for cc_pair_id={cc_pair.id}")

    logger.info(f"Found {len(group_names)} groups in Jira Service Management")

    for group_name in group_names:
        if not group_name:
            continue

        member_emails = _get_group_member_emails(
            jira_client=jira_client,
            group_name=group_name,
        )
        if not member_emails:
            logger.debug(f"No members found for group {group_name}")
            continue

        logger.debug(f"Found {len(member_emails)} members for group {group_name}")
        yield ExternalUserGroup(
            id=group_name,
            user_emails=list(member_emails),
        )
