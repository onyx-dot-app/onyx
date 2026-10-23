"""A thread names the group of its channel's members, and a channel file the
SharePoint groups of its channel site, which are expanded the way the
SharePoint connector expands them."""

from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.sharepoint.permission_utils import (
    get_sharepoint_external_groups,
)
from ee.onyx.external_permissions.utils import credential_json
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.teams.connector import TeamsConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def teams_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    connector = TeamsConnector(
        **build_connector_kwargs(
            cc_pair.connector.source, cc_pair.connector.connector_specific_config
        )
    )
    connector.load_credentials(credential_json(cc_pair))
    if connector.graph_client is None:
        raise RuntimeError("Graph client not initialized in connector")

    for group_id, emails in connector.channel_member_groups():
        logger.info("Group %s has %s members", group_id, len(emails))
        yield ExternalUserGroup(id=group_id, user_emails=emails)

    # Only channel files name the groups of a site.
    if not connector.include_attachments:
        return

    reader = connector.permission_reader()
    for site_url in connector.channel_site_urls():
        groups = get_sharepoint_external_groups(reader, site_url)
        logger.info("Channel site %s grants %s groups", site_url, len(groups))
        yield from groups
