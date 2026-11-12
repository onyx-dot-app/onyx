"""The groups that Egnyte folder access names: the default groups, built from
each active user's type, and every custom group with its active members."""

import time
from collections.abc import Generator

from ee.onyx.connectors.perm_sync_valid import validate_egnyte_group_sync
from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.egnyte.access import (
    active_users,
    custom_group_id,
    default_groups,
)
from ee.onyx.external_permissions.egnyte.connector import egnyte_connector
from onyx.configs.app_configs import PERMISSION_SYNC_TIMEOUT
from onyx.connectors.egnyte.connector import EgnyteConnector
from onyx.connectors.egnyte.models import EgnyteUser
from onyx.connectors.egnyte.source_operations import EgnyteApiError
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()


def egnyte_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    connector: EgnyteConnector = egnyte_connector(cc_pair)
    # A token whose user is no longer an administrator lists fewer users, and
    # the sync would then drop them from every group without an error.
    validate_egnyte_group_sync(connector)
    yield from egnyte_groups(connector)


def egnyte_groups(
    connector: EgnyteConnector,
) -> Generator[ExternalUserGroup, None, None]:
    ops = connector.ops
    users: list[EgnyteUser] = active_users(ops)
    yield from default_groups(connector.domain, users)

    emails: dict[str, str] = {
        user.user_name: user.email.strip().lower() for user in users
    }
    # The caller checks its deadline only per yielded group, and each group
    # costs a call that Egnyte may hold back, so the walk checks it too.
    deadline: float = time.monotonic() + PERMISSION_SYNC_TIMEOUT
    for group_ref in ops.list_groups():
        if time.monotonic() > deadline:
            raise RuntimeError(
                f"Egnyte group sync passed its {PERMISSION_SYNC_TIMEOUT}s timeout"
            )
        try:
            group = ops.get_group(group_id=group_ref.id)
        except EgnyteApiError as e:
            if e.status_code != 404:
                raise
            # Deleted after the listing: it grants nothing any more.
            logger.info("Egnyte group %s was deleted during the sync", group_ref.id)
            continue
        yield ExternalUserGroup(
            id=custom_group_id(connector.domain, group.id),
            user_emails=sorted(
                {emails[m.username] for m in group.members if m.username in emails}
            ),
        )
