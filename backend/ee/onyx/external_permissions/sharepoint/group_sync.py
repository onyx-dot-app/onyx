from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.sharepoint.permission_utils import (
    get_sharepoint_external_groups,
)
from ee.onyx.external_permissions.utils import credential_json
from onyx.connectors.factory import build_connector_kwargs
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
    connector = SharepointConnector(
        **build_connector_kwargs(cc_pair.connector.source, connector_config)
    )
    connector.load_credentials(credential_json(cc_pair))

    # Get site descriptors from connector (either configured sites or all sites)
    site_descriptors = connector.site_descriptors or connector.fetch_sites()

    if not site_descriptors:
        raise RuntimeError("No SharePoint sites found for group sync")

    logger.info("Processing %s sites for group sync", len(site_descriptors))

    # The gateway refuses a site host outside the tenant the REST token is
    # minted for.
    reader = connector.ops
    for site_descriptor in site_descriptors:
        logger.debug("Processing site: %s", site_descriptor.url)

        external_groups = get_sharepoint_external_groups(
            reader,
            site_descriptor.url,
            enumerate_all_ad_groups=connector.exhaustive_ad_enumeration,
        )

        # Yield each group
        for group in external_groups:
            logger.debug(
                "Found group: %s with %s members", group.id, len(group.user_emails)
            )
            yield group
