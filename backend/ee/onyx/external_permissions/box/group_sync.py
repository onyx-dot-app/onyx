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


def _fetch_all_enterprise_user_emails(client: BoxClient) -> set[str]:
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
    connector = BoxConnector(**cc_pair.connector.connector_specific_config)
    connector.load_credentials(credential_json(cc_pair))
    client = connector.enterprise_client

    offset = 0
    while True:
        groups = client.groups.get_groups(limit=_PAGE_SIZE, offset=offset)
        entries = groups.entries or []
        for group in entries:
            member_emails = _fetch_group_member_emails(client, group.id)
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

    # Backs "company"-scope shared links, which grant read access to every
    # logged-in user in the Box enterprise.
    yield ExternalUserGroup(
        id=box_all_enterprise_users_group_id(),
        user_emails=list(_fetch_all_enterprise_user_emails(client)),
    )
