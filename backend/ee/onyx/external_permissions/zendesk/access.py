"""Who may read a Zendesk article or ticket.

Articles: an article with no user segment is for everyone. It is public only
when the Help Center serves it without sign-in; otherwise every signed-in user
reads it. An article with segments is for the members of any of them, plus Guide
managers, who read all content. Group sync evaluates the segments.

Tickets: admins and agents whose role reads all tickets read every ticket,
private groups too. Agents restricted to their groups read the tickets of those
groups (and of every public group, for that role variant). Agents restricted to
their organization read its tickets. The assignee, followers, CCs and requester
read the ticket whatever their role. End users read a ticket (as requester, CC,
or member of an organization that shares tickets) only when it has no internal
note, since the indexed text carries every comment.

Users are granted by email, so a ticket's ACL needs no group per user.
"""

from collections.abc import Mapping
from typing import Any

from onyx.access.models import ExternalAccess
from onyx.connectors.zendesk.access import ticket_user_ids
from onyx.connectors.zendesk.models import (
    ZendeskGroup,
    ZendeskOrganization,
    ZendeskUser,
)


def account_key(subdomain: str) -> str:
    """Scopes group ids to one Zendesk account, whose ids repeat across
    accounts."""
    return subdomain.lower()


def all_users_group_id(account: str) -> str:
    return f"{account}:all_users"


def guide_managers_group_id(account: str) -> str:
    return f"{account}:guide_managers"


def segment_group_id(account: str, segment_id: int) -> str:
    return f"{account}:segment:{segment_id}"


def admins_group_id(account: str) -> str:
    return f"{account}:admins"


def all_tickets_group_id(account: str) -> str:
    return f"{account}:all_tickets"


def public_groups_group_id(account: str) -> str:
    """Agents whose role reads their groups' tickets and every public group's."""
    return f"{account}:public_groups"


def ticket_group_group_id(account: str, group_id: int) -> str:
    """Agents whose role reads their groups' tickets, in this group."""
    return f"{account}:group:{group_id}"


def org_agents_group_id(account: str, organization_id: int) -> str:
    """Agents whose role reads their organization's tickets, in this one."""
    return f"{account}:org_agents:{organization_id}"


def org_end_users_group_id(account: str, organization_id: int) -> str:
    """End users of an organization that shares its tickets."""
    return f"{account}:org_end_users:{organization_id}"


def article_access(
    subdomain: str, article: Mapping[str, Any], help_center_public: bool
) -> ExternalAccess:
    account: str = account_key(subdomain)
    segment_ids: list[int] = article.get("user_segment_ids") or []
    if not segment_ids and article.get("user_segment_id") is not None:
        segment_ids = [article["user_segment_id"]]
    if not segment_ids:
        if help_center_public:
            return ExternalAccess.public()
        return ExternalAccess(
            external_user_emails=set(),
            external_user_group_ids={all_users_group_id(account)},
            is_public=False,
        )
    return ExternalAccess(
        external_user_emails=set(),
        external_user_group_ids={
            guide_managers_group_id(account),
            *(segment_group_id(account, segment_id) for segment_id in segment_ids),
        },
        is_public=False,
    )


def ticket_access(
    subdomain: str,
    ticket: Mapping[str, Any],
    users: Mapping[int, ZendeskUser],
    groups: Mapping[int, ZendeskGroup],
    organizations: Mapping[int, ZendeskOrganization],
    internal_note: bool,
) -> ExternalAccess:
    """`internal_note` may be True without reading the comments when
    `grants_end_users` is False, since end users are then not granted anyway.
    A user, group or organization missing from the mappings grants nothing."""
    account: str = account_key(subdomain)
    group_ids: set[str] = {admins_group_id(account), all_tickets_group_id(account)}

    group_id: int | None = ticket.get("group_id")
    if group_id:
        group_ids.add(ticket_group_group_id(account, group_id))
        group = groups.get(group_id)
        if group is not None and group.is_public:
            group_ids.add(public_groups_group_id(account))
    else:
        # Zendesk's "within their groups and all public groups" also covers
        # tickets with no group.
        group_ids.add(public_groups_group_id(account))

    organization_id: int | None = ticket.get("organization_id")
    if organization_id:
        group_ids.add(org_agents_group_id(account, organization_id))
        organization = organizations.get(organization_id)
        if (
            not internal_note
            and organization is not None
            and organization.shared_tickets
        ):
            group_ids.add(org_end_users_group_id(account, organization_id))

    emails: set[str] = set()
    for user_id in ticket_user_ids(ticket):
        user = users.get(user_id)
        if user is None or user.grantable_email is None:
            continue
        if internal_note and not user.is_staff:
            continue
        emails.add(user.grantable_email)

    return ExternalAccess(
        external_user_emails=emails,
        external_user_group_ids=group_ids,
        is_public=False,
    )
