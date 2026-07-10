from collections.abc import Generator

from box_sdk_gen import BoxClient

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.utils import credential_json
from onyx.connectors.box.connector import box_all_enterprise_users_group_id
from onyx.connectors.box.connector import box_group_id
from onyx.connectors.box.connector import BoxConnector
from onyx.db.models import ConnectorCredentialPair
from onyx.utils.logger import setup_logger

logger = setup_logger()

_PAGE_SIZE = 1000
# Box's offset-paginated list endpoints reject offsets past ~10k with HTTP 400.
# Stop there (loudly) rather than let the 400 abort the whole sync.
_MAX_OFFSET = 10_000


def _fetch_group_member_emails(client: BoxClient, group_id: str) -> set[str]:
    emails: set[str] = set()
    offset = 0
    while True:
        memberships = client.memberships.get_group_memberships(
            group_id=group_id, limit=_PAGE_SIZE, offset=offset
        )
        entries = memberships.entries or []
        for membership in entries:
            if membership.user is not None and membership.user.login:
                emails.add(membership.user.login)
        offset += len(entries)
        total = memberships.total_count
        if not entries or (total is not None and offset >= total):
            return emails
        if offset >= _MAX_OFFSET:
            logger.warning(
                "Box group %s has more than %d members; syncing only the first "
                "%d (Box offset-pagination ceiling).",
                group_id,
                _MAX_OFFSET,
                offset,
            )
            return emails


def _fetch_all_enterprise_user_emails(client: BoxClient) -> set[str]:
    # The users listing is marker-paginated, so it has no offset ceiling.
    emails: set[str] = set()
    marker: str | None = None
    while True:
        users = client.users.get_users(
            fields=["login"], limit=_PAGE_SIZE, usemarker=True, marker=marker
        )
        for user in users.entries or []:
            if user.login:
                emails.add(user.login)
        marker = users.next_marker
        if not marker:
            return emails


def box_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    creds = credential_json(cc_pair)
    enterprise_id = creds["box_enterprise_id"]
    connector = BoxConnector(**cc_pair.connector.connector_specific_config)
    # Group sync only uses the enterprise client; drop the impersonation email so
    # a deactivated/renamed impersonation user can't fail the whole sync.
    connector.load_credentials(
        {k: v for k, v in creds.items() if k != "box_user_email"}
    )
    client = connector.enterprise_client

    offset = 0
    while True:
        groups = client.groups.get_groups(limit=_PAGE_SIZE, offset=offset)
        entries = groups.entries or []
        for group in entries:
            try:
                member_emails = _fetch_group_member_emails(client, group.id)
            except Exception:
                # Skip (don't yield) on failure: one bad group must not abort the
                # sync, and yielding it empty would wipe its last-synced members.
                logger.exception(
                    "Failed to fetch members for Box group %s; skipping", group.id
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
            logger.warning(
                "Box enterprise has more than %d groups; syncing only the first "
                "%d (Box offset-pagination ceiling).",
                _MAX_OFFSET,
                offset,
            )
            break

    # Backs "company"-scope shared links: every logged-in enterprise user.
    yield ExternalUserGroup(
        id=box_all_enterprise_users_group_id(enterprise_id),
        user_emails=list(_fetch_all_enterprise_user_emails(client)),
    )
