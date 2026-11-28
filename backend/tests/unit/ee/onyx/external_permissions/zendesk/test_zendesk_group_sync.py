from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest

from ee.onyx.external_permissions.zendesk.group_sync import (
    in_segment,
    is_guide_manager,
    ticket_access_of,
    zendesk_groups,
)
from onyx.connectors.zendesk.connector import ZendeskConnector
from onyx.connectors.zendesk.models import (
    ZendeskCustomRole,
    ZendeskMembership,
    ZendeskOrganization,
    ZendeskTicketAccess,
    ZendeskUser,
    ZendeskUserSegment,
)

ROLES = {
    1: ZendeskCustomRole(id=1, ticket_access="all", forum_access="full"),
    2: ZendeskCustomRole(id=2, ticket_access="within-groups", forum_access="readonly"),
    3: ZendeskCustomRole(id=3, ticket_access="within-groups-and-public-groups"),
    4: ZendeskCustomRole(id=4, ticket_access="within-organization"),
    5: ZendeskCustomRole(id=5, ticket_access="something-new"),
}
ADMIN = ZendeskUser(id=10, email="admin@acme.com", role="admin")
LEAD = ZendeskUser(id=11, email="lead@acme.com", role="agent", custom_role_id=1)
GROUP_AGENT = ZendeskUser(
    id=12,
    email="group@acme.com",
    role="agent",
    custom_role_id=2,
    ticket_restriction="groups",
)
PUBLIC_AGENT = ZendeskUser(
    id=13, email="public@acme.com", role="agent", custom_role_id=3
)
ORG_AGENT = ZendeskUser(id=14, email="org@acme.com", role="agent", custom_role_id=4)
ODD_AGENT = ZendeskUser(
    id=15,
    email="odd@acme.com",
    role="agent",
    custom_role_id=5,
    ticket_restriction="assigned",
)
VIP = ZendeskUser(id=20, email="vip@example.com", role="end-user", tags=["vip"])
PLAIN = ZendeskUser(id=21, email="plain@example.com", role="end-user")
SUSPENDED = ZendeskUser(
    id=22, email="gone@example.com", role="end-user", suspended=True
)
USERS = [
    ADMIN,
    LEAD,
    GROUP_AGENT,
    PUBLIC_AGENT,
    ORG_AGENT,
    ODD_AGENT,
    VIP,
    PLAIN,
    SUSPENDED,
]
SHARED_ORG = ZendeskOrganization(id=30, shared_tickets=True, tags=["partner"])
PRIVATE_ORG = ZendeskOrganization(id=31, shared_tickets=False)
GROUP = 40
ORG_MEMBERSHIPS = [
    ZendeskMembership(user_id=VIP.id, container_id=SHARED_ORG.id),
    ZendeskMembership(user_id=PLAIN.id, container_id=PRIVATE_ORG.id),
    ZendeskMembership(user_id=ORG_AGENT.id, container_id=SHARED_ORG.id),
    ZendeskMembership(user_id=SUSPENDED.id, container_id=SHARED_ORG.id),
]
GROUP_MEMBERSHIPS = [
    ZendeskMembership(user_id=user.id, container_id=GROUP)
    for user in (ADMIN, LEAD, GROUP_AGENT, PUBLIC_AGENT, ORG_AGENT)
]
SEGMENTS = [
    ZendeskUserSegment(
        id=50, user_type="signed_in_users", tags=["vip"], organization_ids=[30]
    ),
    ZendeskUserSegment(id=51, user_type="signed_in_users", or_tags=["partner", "x"]),
    ZendeskUserSegment(id=52, user_type="staff", group_ids=[GROUP]),
    ZendeskUserSegment(
        id=53, user_type="signed_in_users", tags=["nobody"], added_user_ids=[PLAIN.id]
    ),
]


def test_ticket_access_of() -> None:
    assert ticket_access_of(LEAD, ROLES) == ZendeskTicketAccess.ALL
    assert ticket_access_of(PUBLIC_AGENT, ROLES) == (
        ZendeskTicketAccess.GROUPS_AND_PUBLIC_GROUPS
    )
    # Unknown values and missing roles grant nothing.
    assert ticket_access_of(ODD_AGENT, ROLES) is None
    # A plan that lists no custom roles falls back to the user's restriction.
    assert ticket_access_of(GROUP_AGENT, {}) == ZendeskTicketAccess.GROUPS
    # Admins have their own group; end users have no agent access.
    assert ticket_access_of(ADMIN, ROLES) is None
    assert ticket_access_of(VIP, ROLES) is None
    # Agents without a custom role go by ticket_restriction.
    assert ticket_access_of(ZendeskUser(id=1, role="agent"), {}) == (
        ZendeskTicketAccess.ALL
    )
    assert ticket_access_of(
        ZendeskUser(id=1, role="agent", ticket_restriction="groups"), {}
    ) == (ZendeskTicketAccess.GROUPS)
    assert (
        ticket_access_of(
            ZendeskUser(id=1, role="agent", ticket_restriction="requested"), {}
        )
        is None
    )


def test_is_guide_manager() -> None:
    assert is_guide_manager(ADMIN, ROLES)
    assert is_guide_manager(LEAD, ROLES)
    assert not is_guide_manager(GROUP_AGENT, ROLES)
    assert not is_guide_manager(VIP, ROLES)


@pytest.mark.parametrize(
    "user, organizations, organization_tags, groups, members",
    [
        # Tags and organizations combine with AND.
        (VIP, {30}, {"partner"}, set(), {50, 51}),
        (VIP, set(), set(), set(), set()),
        # Organization tags count for end users; added users skip the filters.
        (PLAIN, {31}, set(), set(), {53}),
        # Staff segments need staff in one of the groups.
        (GROUP_AGENT, set(), set(), {GROUP}, {52}),
        (GROUP_AGENT, set(), set(), set(), set()),
    ],
)
def test_in_segment(
    user: ZendeskUser,
    organizations: set[int],
    organization_tags: set[str],
    groups: set[int],
    members: set[int],
) -> None:
    assert {
        segment.id
        for segment in SEGMENTS
        if in_segment(user, segment, organizations, organization_tags, groups)
    } == members


def _connector(content_type: str, grant_end_users: bool = False) -> ZendeskConnector:
    connector = ZendeskConnector(
        content_type=content_type, grant_end_users=grant_end_users
    )
    connector.subdomain = "acme"
    ops = MagicMock()

    def users(staff_only: bool = False) -> Iterator[list[ZendeskUser]]:
        yield [user for user in USERS if not staff_only or user.is_staff]

    ops.iterate_users.side_effect = users
    ops.list_custom_roles.return_value = list(ROLES.values())

    def organization_memberships(
        user_id: int | None = None,
    ) -> Iterator[list[ZendeskMembership]]:
        yield [m for m in ORG_MEMBERSHIPS if user_id is None or m.user_id == user_id]

    def organization_users(organization_id: int) -> Iterator[list[ZendeskUser]]:
        member_ids = {
            m.user_id for m in ORG_MEMBERSHIPS if m.container_id == organization_id
        }
        yield [user for user in USERS if user.id in member_ids]

    ops.iterate_organization_memberships.side_effect = organization_memberships
    ops.iterate_organization_users.side_effect = organization_users
    ops.iterate_group_memberships.side_effect = lambda: iter([GROUP_MEMBERSHIPS])
    ops.iterate_organizations.side_effect = lambda: iter([[SHARED_ORG, PRIVATE_ORG]])
    ops.list_user_segments.return_value = SEGMENTS
    connector._ops = ops
    return connector


def _groups(connector: ZendeskConnector) -> dict[str, list[str]]:
    return {group.id: group.user_emails for group in zendesk_groups(connector)}


def test_article_groups() -> None:
    groups = _groups(_connector("articles"))
    assert groups["acme:all_users"] == sorted(
        user.email for user in USERS if user is not SUSPENDED and user.email
    )
    assert groups["acme:guide_managers"] == ["admin@acme.com", "lead@acme.com"]
    assert groups["acme:segment:50"] == ["vip@example.com"]
    assert groups["acme:segment:51"] == ["vip@example.com"]
    assert groups["acme:segment:52"] == sorted(
        [
            "admin@acme.com",
            "lead@acme.com",
            "group@acme.com",
            "public@acme.com",
            "org@acme.com",
        ]
    )
    assert groups["acme:segment:53"] == ["plain@example.com"]


def test_ticket_groups_without_end_users() -> None:
    connector = _connector("tickets")
    groups = _groups(connector)
    assert groups == {
        "acme:admins": ["admin@acme.com"],
        "acme:all_tickets": ["lead@acme.com"],
        "acme:public_groups": ["public@acme.com"],
        "acme:group:40": ["group@acme.com", "public@acme.com"],
        "acme:org_agents:30": ["org@acme.com"],
    }
    # Without end-user grants, only staff are read, and only the memberships of
    # agents limited to organizations.
    ops: Any = connector.ops
    assert ops.iterate_users.call_args.kwargs == {"staff_only": True}
    ops.iterate_organizations.assert_not_called()
    assert [c.kwargs for c in ops.iterate_organization_memberships.call_args_list] == [
        {"user_id": ORG_AGENT.id}
    ]


def test_ticket_groups_with_end_users() -> None:
    groups = _groups(_connector("tickets", grant_end_users=True))
    # Only organizations that share tickets, and no suspended users.
    assert groups["acme:org_end_users:30"] == ["vip@example.com"]
    assert "acme:org_end_users:31" not in groups
