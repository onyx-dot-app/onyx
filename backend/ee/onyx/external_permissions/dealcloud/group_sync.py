import math
import time
from collections.abc import Generator

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.dealcloud.access import (
    entry_type_group_id,
    reads_every_entry,
)
from ee.onyx.external_permissions.dealcloud.connector import dealcloud_connector
from ee.onyx.external_permissions.utils import instance_key
from onyx.configs.app_configs import PERMISSION_SYNC_TIMEOUT
from onyx.connectors.dealcloud.connector import (
    DealCloudConnector,
    indexed_entry_types,
)
from onyx.connectors.dealcloud.models import DealCloudUserGroup
from onyx.connectors.dealcloud.source_operations import DealCloudSourceOperations
from onyx.db.models import ConnectorCredentialPair


def dealcloud_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    # One deadline for the whole sync. The caller checks its own only per
    # yielded group, and every read here happens before the first one.
    yield from entry_type_groups(
        dealcloud_connector(cc_pair), time.monotonic() + PERMISSION_SYNC_TIMEOUT
    )


def _raise_if_past(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise RuntimeError(
            f"DealCloud group sync passed its {PERMISSION_SYNC_TIMEOUT}s timeout "
            "while it read the users and groups"
        )


def read_user_groups(
    ops: DealCloudSourceOperations, deadline: float = math.inf
) -> list[DealCloudUserGroup]:
    """Every user group with its members, one request per group."""
    groups: list[DealCloudUserGroup] = []
    for ref in ops.list_user_groups():
        _raise_if_past(deadline)
        groups.append(ops.get_user_group(group_id=ref.id))
    _raise_if_past(deadline)
    return groups


def reader_emails(ops: DealCloudSourceOperations, deadline: float) -> list[str]:
    _raise_if_past(deadline)
    emails: dict[int, str] = {
        user.id: user.email.strip().lower()
        for user in ops.list_active_users()
        if user.email and user.email.strip()
    }
    reader_ids: set[int] = {
        user_id
        for group in read_user_groups(ops, deadline)
        if reads_every_entry(group)
        for user_id in group.users
    }
    return sorted({emails[user_id] for user_id in reader_ids if user_id in emails})


def entry_type_groups(
    connector: DealCloudConnector, deadline: float
) -> Generator[ExternalUserGroup, None, None]:
    ops: DealCloudSourceOperations = connector.ops
    instance: str = instance_key(connector.base_url)
    emails: list[str] = reader_emails(ops, deadline)
    for entry_type in indexed_entry_types(ops, connector.entry_types):
        yield ExternalUserGroup(
            id=entry_type_group_id(instance, entry_type.id), user_emails=emails
        )
