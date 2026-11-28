"""Access for Zendesk documents. The rules live in EE; CE indexes without
access. The helpers here decide what the connector must read."""

from collections.abc import Callable, Iterable, Mapping
from typing import Any, cast

from onyx.access.models import ExternalAccess
from onyx.connectors.zendesk.models import (
    ZendeskGroup,
    ZendeskOrganization,
    ZendeskUser,
)
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)

_EE_ACCESS_MODULE: str = "onyx.external_permissions.zendesk.access"


def access_enabled() -> bool:
    return global_version.is_ee_version()


def get_article_access(
    subdomain: str, article: Mapping[str, Any], help_center_public: bool
) -> ExternalAccess | None:
    if not access_enabled():
        return None
    ee_article_access = cast(
        Callable[[str, Mapping[str, Any], bool], ExternalAccess],
        fetch_versioned_implementation(_EE_ACCESS_MODULE, "article_access"),
    )
    return ee_article_access(subdomain, article, help_center_public)


def get_ticket_access(
    subdomain: str,
    ticket: Mapping[str, Any],
    users: Mapping[int, ZendeskUser],
    groups: Mapping[int, ZendeskGroup],
    organizations: Mapping[int, ZendeskOrganization],
    internal_note: bool,
) -> ExternalAccess | None:
    if not access_enabled():
        return None
    ee_ticket_access = cast(
        Callable[
            [
                str,
                Mapping[str, Any],
                Mapping[int, ZendeskUser],
                Mapping[int, ZendeskGroup],
                Mapping[int, ZendeskOrganization],
                bool,
            ],
            ExternalAccess,
        ],
        fetch_versioned_implementation(_EE_ACCESS_MODULE, "ticket_access"),
    )
    return ee_ticket_access(
        subdomain, ticket, users, groups, organizations, internal_note
    )


def ticket_user_ids(ticket: Mapping[str, Any]) -> set[int]:
    """The users a ticket names who read it whatever their role allows."""
    ids: set[int] = set()
    for key in ("requester_id", "assignee_id"):
        if ticket.get(key):
            ids.add(ticket[key])
    for key in ("email_cc_ids", "follower_ids", "collaborator_ids"):
        ids.update(ticket.get(key) or [])
    return ids


def grants_end_users(
    ticket: Mapping[str, Any],
    users: Mapping[int, ZendeskUser],
    organizations: Mapping[int, ZendeskOrganization],
) -> bool:
    """Whether an end user would read the ticket if it had no internal note,
    so the caller knows whether the comments must be read."""
    if any(
        (user := users.get(user_id)) is not None
        and not user.is_staff
        and user.grantable_email is not None
        for user_id in ticket_user_ids(ticket)
    ):
        return True
    organization_id: int | None = ticket.get("organization_id")
    organization = organizations.get(organization_id) if organization_id else None
    return organization is not None and organization.shared_tickets


def has_internal_note(comments: Iterable[Mapping[str, Any]]) -> bool:
    """A comment without an explicit public flag counts as internal."""
    return any(comment.get("public") is not True for comment in comments)
