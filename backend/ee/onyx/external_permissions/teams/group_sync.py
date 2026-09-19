"""Channel files carry the SharePoint groups of their channel sites, so those
groups are expanded the way the SharePoint connector expands them."""

from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.sharepoint.permission_utils import (
    get_sharepoint_external_groups,
)
from ee.onyx.external_permissions.utils import credential_json
from onyx.connectors.teams.connector import TeamsConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def teams_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    connector = TeamsConnector(**cc_pair.connector.connector_specific_config)
    connector.load_credentials(credential_json(cc_pair))
    # Only channel files name groups: threads are read by their members.
    if not connector.include_attachments:
        return
    if connector.graph_client is None:
        raise RuntimeError("Graph client not initialized in connector")

    for site_url in connector.channel_site_urls():
        groups = get_sharepoint_external_groups(
            connector.rest_context(site_url), connector.graph_client
        )
        logger.info("Channel site %s grants %s groups", site_url, len(groups))
        yield from groups
