"""Entra ID group expansion for the Microsoft permission-sync paths.

Lives outside the SharePoint module because any Microsoft source that mirrors
permissions names Entra groups and needs the same two things from Graph:
expand one group into its members and nested groups, and enumerate a tenant's
groups outright. SharePoint is the caller today.

The external group id is the Entra group id. Display names change and are not
unique, and OneDrive and Azure Data Lake store the same id, so one Entra group
has one id across the Microsoft sources. Onyx prefixes it with the source when
it stores the group.

This module knows nothing about SharePoint principal types or any other
source-specific shape. Callers adapt :class:`ResolvedEntraGroup` into their own
models where they need extra fields. Graph is reached only through the
caller's :class:`EntraGroupReader`.
"""

from collections.abc import Generator

from pydantic import BaseModel

from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.connectors.microsoft_utils.entra import iter_entra_items
from onyx.connectors.microsoft_utils.models import (
    EntraMemberKind,
)
from onyx.connectors.microsoft_utils.sharepoint_principals import resolve_group_id
from onyx.connectors.microsoft_utils.sharepoint_rest import (
    EntraGroupReader,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

MICROSOFT_DOMAIN = ".onmicrosoft"

# Tenant-wide enumeration walks every group and every member. Past this many
# groups the run is not worth the memory or the Graph budget, so it stops and
# leaves the rest to be resolved from the source's own references.
ENTRA_GROUP_ENUMERATION_THRESHOLD = 100_000
ENTRA_GROUP_MEMBER_THRESHOLD = 1_000_000


class ResolvedEntraGroup(BaseModel):
    """An Entra group as a caller needs it. The id is also its external group id."""

    model_config = {"frozen": True}

    id: str


def normalize_email(email: str) -> str:
    return email.replace(MICROSOFT_DOMAIN, "")


def resolve_entra_group_id(reader: EntraGroupReader, identifier: str) -> str | None:
    """The external group id for a group known only by an identifier, or None
    when Entra has no such group. A grant to an unresolved group matches no one."""
    return resolve_group_id(reader, identifier)


def expand_entra_group(
    reader: EntraGroupReader, identifier: str
) -> tuple[set[ResolvedEntraGroup], set[str]]:
    """Return one group's nested groups and its direct member emails."""
    group_id = resolve_group_id(reader, identifier)
    if not group_id:
        logger.error("Failed to get Entra group id for %s", identifier)
        return set(), set()
    groups: set[ResolvedEntraGroup] = set()
    user_emails: set[str] = set()

    for member in reader.list_entra_group_members(group_id=group_id):
        if member.kind == EntraMemberKind.USER:
            email = member.user_principal_name or member.mail
            if email:
                user_emails.add(normalize_email(email))
            logger.info("Added user: %s", email)
        elif member.kind == EntraMemberKind.GROUP:
            groups.add(ResolvedEntraGroup(id=member.id))
            logger.info("Added group: %s", member.id)
        else:
            logger.warning("Could not identify member type for: %s", member)

    return groups, user_emails


def list_nested_entra_groups(
    reader: EntraGroupReader, identifier: str
) -> set[ResolvedEntraGroup]:
    """One group's direct member groups, without its users."""
    group_id = resolve_group_id(reader, identifier)
    if not group_id:
        logger.error("Failed to get Entra group id for %s", identifier)
        return set()
    return {
        ResolvedEntraGroup(id=group.id)
        for group in reader.list_nested_entra_groups(group_id=group_id)
    }


def enumerate_entra_groups(
    reader: EntraGroupReader,
    already_resolved: set[str],
    threshold: int = ENTRA_GROUP_ENUMERATION_THRESHOLD,
) -> Generator[ExternalUserGroup, None, None]:
    """Yield every Entra group in the tenant as an ExternalUserGroup.

    Skips groups whose id is already in ``already_resolved``. Stops once
    ``threshold`` groups have been seen.
    """
    total_groups = 0

    groups = iter_entra_items(
        lambda next_link: reader.list_entra_groups(next_link=next_link),
        "Entra group listing",
    )
    for group in groups:
        group_id = group.id
        if not group_id:
            continue

        total_groups += 1
        if total_groups > threshold:
            logger.warning(
                "Entra group enumeration exceeded %s groups, stopping to avoid excessive memory and API usage. Remaining groups will be resolved from source references only.",
                threshold,
            )
            return

        if group_id in already_resolved:
            continue

        member_emails: list[str] = []
        members = iter_entra_items(
            lambda next_link, group_id=group_id: reader.list_entra_group_member_page(
                group_id=group_id, next_link=next_link
            ),
            f"Entra group `{group_id}` members",
        )
        for member in members:
            email = member.user_principal_name or member.mail
            if email:
                member_emails.append(normalize_email(email))
            if len(member_emails) > ENTRA_GROUP_MEMBER_THRESHOLD:
                raise RuntimeError(
                    f"Entra group `{group_id}` exceeds the member count limit."
                )

        yield ExternalUserGroup(id=group_id, user_emails=member_emails)

    logger.info("Enumerated %s Entra groups via paginated Graph API", total_groups)
