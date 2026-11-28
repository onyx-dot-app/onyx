"""A thread names the group of its channel's members, and a channel file the
SharePoint groups of its channel site, which are expanded the way the
SharePoint connector expands them. A file with permissions of its own can also
name an Entra group that no site role assignment names; those come from the
access the pair has stored."""

import re
from collections.abc import Generator

from ee.onyx.db.external_perm import (
    ExternalUserGroup,
    fetch_referenced_external_group_ids_for_cc_pair,
)
from ee.onyx.external_permissions.microsoft_utils.sharepoint_permissions import (
    get_entra_external_groups,
    get_sharepoint_external_groups,
)
from ee.onyx.external_permissions.utils import credential_json
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.factory import build_connector_kwargs
from onyx.connectors.microsoft_utils.sharepoint_principals import GUID_RE
from onyx.connectors.teams.connector import TeamsConnector
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _stored_entra_group_ids(cc_pair: ConnectorCredentialPair) -> set[str]:
    """The Entra group ids that the pair's documents and nodes grant access to."""
    source_prefix = build_ext_group_name_for_onyx("", DocumentSource.TEAMS)
    with get_session_with_current_tenant() as db_session:
        stored_ids = fetch_referenced_external_group_ids_for_cc_pair(
            db_session, cc_pair, source_prefix
        )
    return {
        group_id
        for stored_id in stored_ids
        if re.fullmatch(GUID_RE, group_id := stored_id.removeprefix(source_prefix))
    }


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
    yielded: set[str] = set()
    for site_url in connector.channel_site_urls():
        groups = get_sharepoint_external_groups(reader, site_url)
        logger.info("Channel site %s grants %s groups", site_url, len(groups))
        for group in groups:
            yielded.add(group.id.lower())
            yield group

    file_only_group_ids = _stored_entra_group_ids(cc_pair) - yielded
    logger.info("Files name %s Entra groups no site grants", len(file_only_group_ids))
    for group in get_entra_external_groups(reader, file_only_group_ids):
        if group.id.lower() not in yielded:
            yield group
