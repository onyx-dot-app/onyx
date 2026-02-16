from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.sharepoint.permission_utils import (
    get_sharepoint_external_groups,
)
from onyx.connectors.sharepoint.connector import SharepointConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def sharepoint_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    """Sync SharePoint groups and their members"""

    # Get site URLs from connector config
    connector_config = cc_pair.connector.connector_specific_config

    # Create SharePoint connector instance and load credentials
    connector = SharepointConnector(**connector_config)
    credential_json = (
        cc_pair.credential.credential_json.get_value(apply_mask=False)
        if cc_pair.credential.credential_json
        else {}
    )
    connector.load_credentials(credential_json)

    if not connector.msal_app:
        raise RuntimeError("MSAL app not initialized in connector")

    if not connector.sp_tenant_domain:
        raise RuntimeError("Tenant domain not initialized in connector")

    # Get site descriptors from connector (either configured sites or all sites)
    site_descriptors = connector.site_descriptors or connector.fetch_sites()

    if not site_descriptors:
        raise RuntimeError("No SharePoint sites found for group sync")

    logger.info(f"Processing {len(site_descriptors)} sites for group sync")

    # Process each site
    for site_descriptor in site_descriptors:
        logger.debug(f"Processing site: {site_descriptor.url}")

        ctx = connector._create_rest_client_context(site_descriptor.url)

        # Get external groups for this site
        external_groups = get_sharepoint_external_groups(ctx, connector.graph_client)

        # Yield each group
        for group in external_groups:
            logger.debug(
                f"Found group: {group.id} with {len(group.user_emails)} members"
            )
            yield group
