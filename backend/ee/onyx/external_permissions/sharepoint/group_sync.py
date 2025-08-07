from collections.abc import Generator

from office365.sharepoint.client_context import ClientContext  # type: ignore[import-untyped]

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.sharepoint.permission_utils import (
    get_sharepoint_external_groups,
)
from onyx.connectors.sharepoint.connector import acquire_token_for_rest
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def sharepoint_group_sync(
    tenant_id: str,
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    """Sync SharePoint groups and their members"""

    # Get site URLs from connector config
    connector_config = cc_pair.connector.connector_specific_config

    # Create SharePoint connector instance and load credentials
    connector = SharepointConnector(**connector_config)
    connector.load_credentials(cc_pair.credential.credential_json)

    if not connector.msal_app:
        raise RuntimeError("MSAL app not initialized in connector")

    if not connector.sp_tenant_domain:
        raise RuntimeError("Tenant domain not initialized in connector")

    # Get site descriptors from connector (either configured sites or all sites)
    site_descriptors = connector.site_descriptors or connector.fetch_sites()

    if not site_descriptors:
        raise RuntimeError("No SharePoint sites found for group sync")

    logger.info(f"Processing {len(site_descriptors)} sites for group sync")

    msal_app = connector.msal_app
    sp_tenant_domain = connector.sp_tenant_domain
    # Process each site
    for site_descriptor in site_descriptors:
        logger.debug(f"Processing site: {site_descriptor.url}")

        # Create client context for the site using connector's MSAL app
        ctx = ClientContext(site_descriptor.url).with_access_token(
            lambda: acquire_token_for_rest(msal_app, sp_tenant_domain)
        )

        # Get external groups for this site
        external_groups = get_sharepoint_external_groups(ctx, connector.graph_client)

        # Yield each group
        for group in external_groups:
            logger.debug(
                f"Found group: {group.id} with {len(group.user_emails)} members"
            )
            yield group
