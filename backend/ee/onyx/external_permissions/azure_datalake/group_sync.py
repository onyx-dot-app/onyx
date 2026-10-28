"""The groups the doc sync names: every Entra group with its users, nested
groups included, and the tenant-everyone group that stands for the ACL
``other`` class. Group ids are bare object ids: the source prefix is added
when the groups are stored."""

import time
from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.azure_datalake.connector import (
    azure_datalake_connector,
)
from ee.onyx.external_permissions.azure_datalake.directory import (
    GraphDirectory,
    GroupMembersUnreadableError,
    everyone_group_id,
)
from onyx.configs.app_configs import PERMISSION_SYNC_TIMEOUT
from onyx.connectors.azure_datalake.connector import AzureDataLakeConnector
from onyx.connectors.azure_datalake.source_operations import (
    AzureDataLakeSourceOperations,
)
from onyx.connectors.microsoft_utils.entra import iter_entra_items
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


def tenant_groups(
    ops: AzureDataLakeSourceOperations,
) -> Generator[ExternalUserGroup, None, None]:
    directory = GraphDirectory(ops)
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
    yield from tenant_groups(connector.ops)
