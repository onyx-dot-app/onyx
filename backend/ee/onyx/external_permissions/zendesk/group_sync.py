"""The groups the Zendesk access rules name, for the connector's content type.

Articles: every signed-in user, Guide managers, and each user segment's
members. Zendesk does not list segment members, so the rules are evaluated
here: filter types combine with AND, `or_tags` match any tag, and
`added_user_ids` join whatever the filters say (checked live against
Zendesk's own per-user evaluation).

Tickets: admins, agents by their role's ticket access, and, with
grant_end_users, the end users of organizations that share their tickets.
"""

import time
from collections import defaultdict
from collections.abc import Generator, Iterable

from ee.onyx.db.external_perm import ExternalUserGroup
from ee.onyx.external_permissions.zendesk.access import (
    account_key,
    admins_group_id,
    all_tickets_group_id,
    all_users_group_id,
    guide_managers_group_id,
    org_agents_group_id,
    org_end_users_group_id,
    public_groups_group_id,
    segment_group_id,
    ticket_group_group_id,
)
from ee.onyx.external_permissions.zendesk.connector import zendesk_connector
from onyx.configs.app_configs import PERMISSION_SYNC_TIMEOUT
from onyx.connectors.zendesk.config import ZendeskContentType
from onyx.connectors.zendesk.connector import ZendeskConnector
from onyx.connectors.zendesk.models import (
    ZendeskCustomRole,
    ZendeskMembership,
    ZendeskOrganization,
    ZendeskRole,
    ZendeskTicketAccess,
    ZendeskUser,
    ZendeskUserSegment,
)
from onyx.connectors.zendesk.source_operations import ZendeskSourceOperations
from onyx.db.models import ConnectorCredentialPair

# ticket_restriction values for agents without a custom role.
_RESTRICTION_ACCESS: dict[str | None, ZendeskTicketAccess] = {
    None: ZendeskTicketAccess.ALL,
    # Fails closed: the user does not say whether public groups are included.
    "groups": ZendeskTicketAccess.GROUPS,
    "organization": ZendeskTicketAccess.ORGANIZATION,
    "assigned": ZendeskTicketAccess.ASSIGNED,
}
_GUIDE_MANAGER_FORUM_ACCESS: str = "full"


class _Deadline:
    """The caller checks its deadline only per yielded group, and the user
    walk yields none, so the walk checks the same deadline itself."""

    def __init__(self) -> None:
        self._end: float = time.monotonic() + PERMISSION_SYNC_TIMEOUT

    def check(self, step: str) -> None:
        if time.monotonic() > self._end:
            raise RuntimeError(
                f"Zendesk group sync passed its {PERMISSION_SYNC_TIMEOUT}s timeout "
                f"while reading {step}"
            )


def zendesk_group_sync(
    tenant_id: str,  # noqa: ARG001
    cc_pair: ConnectorCredentialPair,
) -> Generator[ExternalUserGroup, None, None]:
    connector: ZendeskConnector = zendesk_connector(cc_pair)
    # A token that lost admin access reads fewer users and memberships, and
    # the sync would then shrink every group without an error.
    connector.validate_perm_sync()
    yield from zendesk_groups(connector)


def zendesk_groups(
    connector: ZendeskConnector,
) -> Generator[ExternalUserGroup, None, None]:
    ops: ZendeskSourceOperations = connector.ops
    account: str = account_key(connector.subdomain)
    deadline = _Deadline()
    custom_roles: dict[int, ZendeskCustomRole] = {
        role.id: role for role in ops.list_custom_roles() or []
    }
    group_members: dict[int, set[int]] = _memberships(
        ops.iterate_group_memberships(), deadline, "group memberships"
    )
    if connector.content_type == ZendeskContentType.ARTICLES:
        # Segments can name any user, by tag or organization.
        yield from _article_groups(
            account,
            _users(ops.iterate_users(), deadline, "users"),
            custom_roles,
            _memberships(
                ops.iterate_organization_memberships(),
                deadline,
                "organization memberships",
            ),
            group_members,
            _organizations(ops, deadline),
            ops.list_user_segments(),
        )
        return
    staff: list[ZendeskUser] = _users(
        ops.iterate_users(staff_only=True), deadline, "users"
    )
    yield from _ticket_groups(
        ops, account, staff, custom_roles, group_members, deadline
    )
    if connector.grant_end_users:
        yield from _shared_organization_groups(ops, account, deadline)


def _users(
    pages: Iterable[list[ZendeskUser]], deadline: _Deadline, step: str
) -> list[ZendeskUser]:
    """Users who can sign in and have an email."""
    users: list[ZendeskUser] = []
    for page in pages:
        deadline.check(step)
        users.extend(user for user in page if user.grantable_email is not None)
    return users


def _organizations(
    ops: ZendeskSourceOperations, deadline: _Deadline
) -> list[ZendeskOrganization]:
    organizations: list[ZendeskOrganization] = []
    for page in ops.iterate_organizations():
        deadline.check("organizations")
        organizations.extend(page)
    return organizations


def _memberships(
    pages: Iterable[list[ZendeskMembership]], deadline: _Deadline, step: str
) -> dict[int, set[int]]:
    """Each user's containers (groups or organizations)."""
    containers: dict[int, set[int]] = defaultdict(set)
    for page in pages:
        deadline.check(step)
        for membership in page:
            containers[membership.user_id].add(membership.container_id)
    return containers


def _emails(users: Iterable[ZendeskUser]) -> list[str]:
    return sorted({email for user in users if (email := user.grantable_email)})


def ticket_access_of(
    user: ZendeskUser, custom_roles: dict[int, ZendeskCustomRole]
) -> ZendeskTicketAccess | None:
    """An agent's ticket access. Admins read every ticket through their own
    group, so they get None here, as do unknown values."""
    if user.role != ZendeskRole.AGENT:
        return None
    role = custom_roles.get(user.custom_role_id) if user.custom_role_id else None
    if role is not None:
        try:
            return ZendeskTicketAccess(role.ticket_access or "")
        except ValueError:
            return None
    # No custom role, or a plan that does not list them: the user's own
    # restriction, which cannot tell the two group variants apart.
    return _RESTRICTION_ACCESS.get(user.ticket_restriction)


def is_guide_manager(
    user: ZendeskUser, custom_roles: dict[int, ZendeskCustomRole]
) -> bool:
    if user.role == ZendeskRole.ADMIN:
        return True
    if user.role != ZendeskRole.AGENT or user.custom_role_id is None:
        return False
    role = custom_roles.get(user.custom_role_id)
    return role is not None and role.forum_access == _GUIDE_MANAGER_FORUM_ACCESS


def in_segment(
    user: ZendeskUser,
    segment: ZendeskUserSegment,
    organization_ids: set[int],
    organization_tags: set[str],
    group_ids: set[int],
) -> bool:
    """`organization_tags` are the tags of the user's organizations, which
    count as the user's own for end users."""
    if user.id in segment.added_user_ids:
        return True
    if segment.user_type == "staff" and not user.is_staff:
        return False
    if segment.user_type not in ("staff", "signed_in_users"):
        return False
    tags: set[str] = set(user.tags) | (set() if user.is_staff else organization_tags)
    if segment.tags and not set(segment.tags) <= tags:
        return False
    if segment.or_tags and not set(segment.or_tags) & tags:
        return False
    if (
        segment.organization_ids
        and not set(segment.organization_ids) & organization_ids
    ):
        return False
    if segment.group_ids and not (user.is_staff and set(segment.group_ids) & group_ids):
        return False
    return True


def _article_groups(
    account: str,
    users: list[ZendeskUser],
    custom_roles: dict[int, ZendeskCustomRole],
    organization_members: dict[int, set[int]],
    group_members: dict[int, set[int]],
    organizations: list[ZendeskOrganization],
    segments: list[ZendeskUserSegment],
) -> Generator[ExternalUserGroup, None, None]:
    # Bare ids: the source prefix is added when the groups are stored.
    yield ExternalUserGroup(id=all_users_group_id(account), user_emails=_emails(users))
    yield ExternalUserGroup(
        id=guide_managers_group_id(account),
        user_emails=_emails(u for u in users if is_guide_manager(u, custom_roles)),
    )
    tags_by_organization: dict[int, set[str]] = {
        organization.id: set(organization.tags) for organization in organizations
    }
    # Segment-independent per user, so computed once.
    profiles: list[tuple[ZendeskUser, set[int], set[str], set[int]]] = []
    for user in users:
        organization_ids: set[int] = organization_members.get(user.id, set())
        organization_tags: set[str] = set().union(
            *(tags_by_organization.get(org_id, set()) for org_id in organization_ids)
        )
        profiles.append(
            (
                user,
                organization_ids,
                organization_tags,
                group_members.get(user.id, set()),
            )
        )
    for segment in segments:
        members: list[ZendeskUser] = [
            user
            for user, organization_ids, organization_tags, group_ids in profiles
            if in_segment(user, segment, organization_ids, organization_tags, group_ids)
        ]
        yield ExternalUserGroup(
            id=segment_group_id(account, segment.id), user_emails=_emails(members)
        )


def _ticket_groups(
    ops: ZendeskSourceOperations,
    account: str,
    staff: list[ZendeskUser],
    custom_roles: dict[int, ZendeskCustomRole],
    group_members: dict[int, set[int]],
    deadline: _Deadline,
) -> Generator[ExternalUserGroup, None, None]:
    access: dict[int, ZendeskTicketAccess | None] = {
        user.id: ticket_access_of(user, custom_roles) for user in staff
    }
    yield ExternalUserGroup(
        id=admins_group_id(account),
        user_emails=_emails(u for u in staff if u.role == ZendeskRole.ADMIN),
    )
    yield ExternalUserGroup(
        id=all_tickets_group_id(account),
        user_emails=_emails(
            u for u in staff if access[u.id] == ZendeskTicketAccess.ALL
        ),
    )
    yield ExternalUserGroup(
        id=public_groups_group_id(account),
        user_emails=_emails(
            u
            for u in staff
            if access[u.id] == ZendeskTicketAccess.GROUPS_AND_PUBLIC_GROUPS
        ),
    )

    by_group: dict[int, list[ZendeskUser]] = defaultdict(list)
    by_organization: dict[int, list[ZendeskUser]] = defaultdict(list)
    for user in staff:
        if access[user.id] in (
            ZendeskTicketAccess.GROUPS,
            ZendeskTicketAccess.GROUPS_AND_PUBLIC_GROUPS,
        ):
            for group_id in group_members.get(user.id, set()):
                by_group[group_id].append(user)
        if access[user.id] == ZendeskTicketAccess.ORGANIZATION:
            # Few agents are limited to organizations, so their memberships
            # are read one user at a time.
            for organization_id in _memberships(
                ops.iterate_organization_memberships(user_id=user.id),
                deadline,
                "organization memberships",
            ).get(user.id, set()):
                by_organization[organization_id].append(user)

    for group_id, members in by_group.items():
        yield ExternalUserGroup(
            id=ticket_group_group_id(account, group_id), user_emails=_emails(members)
        )
    for organization_id, members in by_organization.items():
        yield ExternalUserGroup(
            id=org_agents_group_id(account, organization_id),
            user_emails=_emails(members),
        )


def _shared_organization_groups(
    ops: ZendeskSourceOperations, account: str, deadline: _Deadline
) -> Generator[ExternalUserGroup, None, None]:
    """The end users of each organization that shares its tickets. The doc
    sync names these groups only with grant_end_users."""
    for organization in _organizations(ops, deadline):
        if not organization.shared_tickets:
            continue
        members: list[ZendeskUser] = _users(
            ops.iterate_organization_users(organization_id=organization.id),
            deadline,
            "organization users",
        )
        yield ExternalUserGroup(
            id=org_end_users_group_id(account, organization.id),
            user_emails=_emails(user for user in members if not user.is_staff),
        )
