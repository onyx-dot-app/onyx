"""Entra ID group expansion for the Microsoft permission-sync paths.

Lives outside the SharePoint module because any Microsoft source that mirrors
permissions names Entra groups and needs the same two things from Graph:
expand one group into its members and nested groups, and enumerate a tenant's
groups outright. SharePoint is the caller today.

The external group name is ``{displayName}_{groupId}``, built only through
:func:`entra_group_name`. Onyx prefixes it with the source when it stores the
group, so the shape here only has to be stable within a source.

This module knows nothing about SharePoint principal types or any other
source-specific shape. Callers adapt :class:`ResolvedEntraGroup` into their own
models where they need extra fields. Graph is reached only through the
caller's :class:`EntraGroupReader`.
"""

import re
from collections.abc import Generator

from pydantic import BaseModel

from ee.onyx.db.external_perm import ExternalUserGroup
from onyx.connectors.microsoft_utils.entra import iter_entra_items
from onyx.connectors.microsoft_utils.models import (
    EntraMemberKind,
)
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

_GUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


class ResolvedEntraGroup(BaseModel):
    """An Entra group as a caller needs it: the id and its external group name."""

    model_config = {"frozen": True}

    id: str
    name: str


def normalize_email(email: str) -> str:
    return email.replace(MICROSOFT_DOMAIN, "")


def entra_group_name(display_name: str, group_id: str | None) -> str:
    """The external group name for an Entra group.

    Display names are not unique in Entra, so the id is part of the name. A
    failed id lookup yields the literal ``None`` suffix. Persisted ACLs already
    carry that name, so it must keep matching.
    """
    return f"{display_name}_{group_id}"


def extract_guid(text: str) -> str | None:
    """Pull the first GUID out of a string such as a SharePoint claims token."""
    try:
        match = re.search(f"({_GUID_RE})", text, re.IGNORECASE)
        if match:
            return match.group(1)

        return None

    except Exception as e:
        logger.error("Failed to extract GUID from %s: %s", text, e)
        return None


def find_group_id_by_name(reader: EntraGroupReader, display_name: str) -> str | None:
    try:
        return reader.find_entra_group_id(display_name=display_name)
    except Exception as e:
        logger.error("Failed to get Entra group id for name %s: %s", display_name, e)
        return None


def resolve_group_id(reader: EntraGroupReader, identifier: str) -> str | None:
    """Resolve a GUID, a SharePoint claims token, or a display name to a group id."""
    try:
        if re.match(f"^{_GUID_RE}$", identifier, re.IGNORECASE):
            return identifier

        if identifier.startswith("c:0") and "|" in identifier:
            guid = extract_guid(identifier)
            if guid:
                logger.info("Extracted GUID %s from claims token %s", guid, identifier)
                return guid

        return find_group_id_by_name(reader, identifier)

    except Exception as e:
        logger.error("Failed to resolve group id from %s: %s", identifier, e)
        return None


def resolve_entra_group_name(
    reader: EntraGroupReader, identifier: str, display_name: str
) -> str:
    """The external group name for a group known only by an identifier."""
    return entra_group_name(display_name, resolve_group_id(reader, identifier))


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
            if not member.display_name:
                logger.error("No display name for group: %s", member.id)
                continue
            name = resolve_entra_group_name(reader, member.id, member.display_name)
            groups.add(ResolvedEntraGroup(id=member.id, name=name))
            logger.info("Added group: %s", name)
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
        ResolvedEntraGroup(
            id=group.id,
            name=resolve_entra_group_name(reader, group.id, group.display_name),
        )
        for group in reader.list_nested_entra_groups(group_id=group_id)
        if group.display_name
    }


def enumerate_entra_groups(
    reader: EntraGroupReader,
    already_resolved: set[str],
    threshold: int = ENTRA_GROUP_ENUMERATION_THRESHOLD,
) -> Generator[ExternalUserGroup, None, None]:
    """Yield every Entra group in the tenant as an ExternalUserGroup.

    Skips groups whose name is already in ``already_resolved``. Stops once
    ``threshold`` groups have been seen.
    """
    total_groups = 0

    groups = iter_entra_items(
        lambda next_link: reader.list_entra_groups(next_link=next_link),
        "Entra group listing",
    )
    for group in groups:
        group_id = group.id
        display_name = group.display_name
        if not group_id or not display_name:
            continue

        total_groups += 1
        if total_groups > threshold:
            logger.warning(
                "Entra group enumeration exceeded %s groups, stopping to avoid excessive memory and API usage. Remaining groups will be resolved from source references only.",
                threshold,
            )
            return

        name = entra_group_name(display_name, group_id)
        if name in already_resolved:
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

        yield ExternalUserGroup(id=name, user_emails=member_emails)

    logger.info("Enumerated %s Entra groups via paginated Graph API", total_groups)
