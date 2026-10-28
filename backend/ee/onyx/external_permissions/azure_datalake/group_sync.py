"""The groups the doc sync names: every Entra group with its users, nested
groups included, the tenant-everyone group that stands for the ACL ``other``
class, and the exclusion groups the cc-pair's stored access names. Group ids
are bare: the source prefix is added when the groups are stored."""

import time
from collections.abc import Generator

from ee.onyx.db.external_perm import (
    ExternalUserGroup,
    fetch_referenced_external_group_ids_for_cc_pair,
)
from ee.onyx.external_permissions.azure_datalake.connector import (
    azure_datalake_connector,
)
from ee.onyx.external_permissions.azure_datalake.directory import (
    GraphDirectory,
    GroupMembersUnreadableError,
    entra_tenant_id,
    everyone_group_id,
)
from ee.onyx.external_permissions.azure_datalake.exclusion_groups import (
    EXCLUSION_GROUP_PREFIX,
    exclusion_group_members,
    parse_exclusion_group_id,
)
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.app_configs import PERMISSION_SYNC_TIMEOUT
from onyx.configs.constants import DocumentSource
from onyx.connectors.azure_datalake.connector import AzureDataLakeConnector
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeSourceOperations,
)
from onyx.connectors.microsoft_utils.entra import iter_entra_items
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _emails(directory: GraphDirectory, user_ids: frozenset[str]) -> list[str]:
    return sorted(
        {
            email
            for user_id in user_ids
            if (email := directory.user_email(user_id)) is not None
        }
    )


def _exclusion_groups(
    ops: AzureDataLakeSourceOperations,
    directory: GraphDirectory,
    exclusion_group_ids: set[str],
) -> Generator[ExternalUserGroup, None, None]:
    tenant_id: str = entra_tenant_id(ops)
    for group_id in sorted(exclusion_group_ids):
        term = parse_exclusion_group_id(group_id, tenant_id)
        if term is None:
            logger.warning("Azure Data Lake exclusion group %s is unknown", group_id)
            continue
        try:
            members: frozenset[str] = exclusion_group_members(term, directory)
        except GroupMembersUnreadableError as e:
            # Synced empty, the group grants nothing.
            logger.warning("%s", e)
            members = frozenset()
        yield ExternalUserGroup(id=group_id, user_emails=_emails(directory, members))


def tenant_groups(
    ops: AzureDataLakeSourceOperations,
    exclusion_group_ids: set[str],
) -> Generator[ExternalUserGroup, None, None]:
    directory = GraphDirectory(ops)
    yield from _exclusion_groups(ops, directory, exclusion_group_ids)
    yield ExternalUserGroup(
        id=everyone_group_id(ops),
        user_emails=_emails(directory, directory.all_users()),
    )
    # The caller checks its deadline only per yielded group, and one large
    # group's member pages can take long, so the walk checks it too.
    deadline: float = time.monotonic() + PERMISSION_SYNC_TIMEOUT
    for group in iter_entra_items(
        lambda next_link: ops.list_groups(next_link=next_link),
        "Entra group listing",
    ):
        if time.monotonic() > deadline:
            raise RuntimeError(
                f"Azure Data Lake group sync passed its {PERMISSION_SYNC_TIMEOUT}s "
                "timeout"
            )
        try:
            members: frozenset[str] = directory.group_members(group.id)
        except GroupMembersUnreadableError as e:
            # Synced empty, the group grants nothing.
            logger.warning("%s", e)
            members = frozenset()
        yield ExternalUserGroup(id=group.id, user_emails=_emails(directory, members))


def azure_datalake_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    connector: AzureDataLakeConnector = azure_datalake_connector(cc_pair)
    # An app that lost its Graph permissions would read no members, and the
    # sync would then empty every group without an error.
    connector.validate_perm_sync()
    source_prefix: str = build_ext_group_name_for_onyx(
        "", DocumentSource.AZURE_DATALAKE
    )
    with get_session_with_current_tenant() as db_session:
        stored_ids: set[str] = fetch_referenced_external_group_ids_for_cc_pair(
            db_session,
            cc_pair,
            f"{source_prefix}{EXCLUSION_GROUP_PREFIX}:",
        )
    yield from tenant_groups(
        connector.ops,
        {group_id.removeprefix(source_prefix) for group_id in stored_ids},
    )
