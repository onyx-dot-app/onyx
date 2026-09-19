from collections.abc import Generator

from box_sdk_gen import BoxClient

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.utils import credential_json
from onyx.connectors.box.connector import (
    BOX_ENTERPRISE_ID_CREDENTIAL_KEY,
    BoxConnector,
    box_all_enterprise_users_group_id,
    box_group_id,
    iter_box_enterprise_users,
    normalize_box_login,
)
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PAGE_SIZE = 1000
# Box's offset-paginated list endpoints reject offsets past ~10k with HTTP 400.
_MAX_OFFSET = 10_000


class BoxGroupTooLargeError(Exception):
    """A group has more members than Box's offset pagination can enumerate, so
    it can't be synced completely."""


def _fetch_group_member_emails(client: BoxClient, group_id: str) -> set[str]:
    # The Box group-memberships endpoint only supports offset pagination.
    emails: set[str] = set()
    offset = 0
    for _ in range(_MAX_OFFSET):
        memberships = client.memberships.get_group_memberships(
            group_id=group_id, limit=_PAGE_SIZE, offset=offset
        )
        entries = memberships.entries or []
        for membership in entries:
            if membership.user is not None and membership.user.login:
                emails.add(normalize_box_login(membership.user.login))
        offset += len(entries)
        total = memberships.total_count
        if not entries or (total is not None and offset >= total):
            return emails
        if offset >= _MAX_OFFSET:
            # Yielding the first 10k as a "complete" group would make the sync
            # replace membership and revoke access for everyone omitted, so treat
            # it as unpageable and let the caller preserve prior membership.
            raise BoxGroupTooLargeError(group_id)
    raise RuntimeError(f"Box group-membership pagination did not terminate: {group_id}")


def box_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    creds = credential_json(cc_pair)
    enterprise_id = creds[BOX_ENTERPRISE_ID_CREDENTIAL_KEY]
    connector = BoxConnector(**cc_pair.connector.connector_specific_config)
    connector.load_credentials(creds)
    client = connector.enterprise_client

    offset = 0
    for _ in range(_MAX_OFFSET):
        groups = client.groups.get_groups(limit=_PAGE_SIZE, offset=offset)
        entries = groups.entries or []
        for group in entries:
            try:
                member_emails = _fetch_group_member_emails(client, group.id)
            except BoxGroupTooLargeError:
                # Skip (don't yield) so the group keeps its prior membership
                # instead of being replaced by a partial set (which would revoke
                # access for members past the offset ceiling).
                logger.warning(
                    "Box group %s exceeds the %d-member pagination ceiling; "
                    "skipping to preserve its existing membership.",
                    group.id,
                    _MAX_OFFSET,
                )
                continue
            if not member_emails:
                logger.info("Box group %s has no members with logins", group.id)
            yield ExternalUserGroup(
                id=box_group_id(group.id),
                user_emails=list(member_emails),
            )
        offset += len(entries)
        total = groups.total_count
        if not entries or (total is not None and offset >= total):
            break
        if offset >= _MAX_OFFSET:
            raise RuntimeError(
                "Box enterprise exceeds the group-listing offset ceiling "
                f"of {_MAX_OFFSET}"
            )
    else:
        raise RuntimeError("Box group pagination did not terminate")

    # Backs "company"-scope shared links: every logged-in enterprise user.
    yield ExternalUserGroup(
        id=box_all_enterprise_users_group_id(enterprise_id),
        user_emails=list(
            {
                normalize_box_login(user.login)
                for user in iter_box_enterprise_users(client)
                if user.login
            }
        ),
    )
