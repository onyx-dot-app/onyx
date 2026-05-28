from collections.abc import Callable
from typing import Any

from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.connectors.confluence.onyx_confluence import (
    get_user_email_from_username__server,
)
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _extract_read_access_restrictions(
    confluence_client: OnyxConfluence, restrictions: dict[str, Any]
) -> tuple[set[str], set[str], bool]:
    """
    Converts a page's restrictions dict into an ExternalAccess object.
    If there are no restrictions, then return None
    """
    read_access = restrictions.get("read", {})
    read_access_restrictions = read_access.get("restrictions", {})

    # Extract the users with read access
    read_access_user = read_access_restrictions.get("user", {})
    read_access_user_jsons = read_access_user.get("results", [])
    # any items found means that there is a restriction
    found_any_restriction = bool(read_access_user_jsons)

    read_access_user_emails = []
    for user in read_access_user_jsons:
        # If the user has an email, then add it to the list
        if user.get("email"):
            read_access_user_emails.append(user["email"])
        # If the user has a username and not an email, then get the email from Confluence
        elif user.get("username"):
            email = get_user_email_from_username__server(
                confluence_client=confluence_client, user_name=user["username"]
            )
            if email:
                read_access_user_emails.append(email)
            else:
                logger.warning(
                    "Email for user %s not found in Confluence", user["username"]
                )
        else:
            if user.get("email") is not None:
                logger.warning("Cant find email for user %s", user.get("displayName"))
                logger.warning(
                    "This user needs to make their email accessible in Confluence Settings"
                )

            logger.warning("no user email or username for %s", user)

    # Extract the groups with read access
    read_access_group = read_access_restrictions.get("group", {})
    read_access_group_jsons = read_access_group.get("results", [])
    # any items found means that there is a restriction
    found_any_restriction |= bool(read_access_group_jsons)
    read_access_group_names = [
        group["name"] for group in read_access_group_jsons if group.get("name")
    ]

    return (
        set(read_access_user_emails),
        set(read_access_group_names),
        found_any_restriction,
    )


# Resolve an ancestor's read-restrictions; None means "unreadable, skip
# and keep walking up" (e.g. a draft owned by another user).
_AncestorRestrictionsResolver = Callable[[dict[str, Any]], dict[str, Any] | None]


def _maybe_prefix_groups(group_names: set[str], add_prefix: bool) -> set[str]:
    if not add_prefix:
        return group_names
    return {
        build_ext_group_name_for_onyx(g, DocumentSource.CONFLUENCE) for g in group_names
    }


def _resolve_external_access(
    confluence_client: OnyxConfluence,
    page_id: str,
    page_restrictions: dict[str, Any],
    ancestors: list[dict[str, Any]],
    resolve_ancestor_restrictions: _AncestorRestrictionsResolver,
    add_prefix: bool,
) -> ExternalAccess | None:
    """Shared inheritance walk. Page-level restriction wins outright;
    otherwise walk ancestors closest-parent-first (they arrive root-first)
    and apply the closest one with a restriction. Returns None when
    nothing restricts the page so the caller falls back to space-level."""
    found_user_emails, found_group_names, found_any_page_level_restriction = (
        _extract_read_access_restrictions(
            confluence_client=confluence_client,
            restrictions=page_restrictions,
        )
    )

    if found_any_page_level_restriction:
        return ExternalAccess(
            external_user_emails=found_user_emails,
            external_user_group_ids=_maybe_prefix_groups(found_group_names, add_prefix),
            is_public=False,
        )

    for ancestor in reversed(ancestors):
        ancestor_restrictions = resolve_ancestor_restrictions(ancestor)
        if ancestor_restrictions is None:
            # Unreadable (draft / 403 / 404); skip and keep walking.
            continue
        (
            ancestor_user_emails,
            ancestor_group_names,
            found_any_restrictions_in_ancestor,
        ) = _extract_read_access_restrictions(
            confluence_client=confluence_client,
            restrictions=ancestor_restrictions,
        )
        if found_any_restrictions_in_ancestor:
            logger.debug(
                "Found user restrictions %s and group restrictions %s for document %s based on ancestor %s",
                ancestor_user_emails,
                ancestor_group_names,
                page_id,
                ancestor,
            )
            return ExternalAccess(
                external_user_emails=ancestor_user_emails,
                external_user_group_ids=_maybe_prefix_groups(
                    ancestor_group_names, add_prefix
                ),
                is_public=False,
            )

    return None


def get_page_restrictions(
    confluence_client: OnyxConfluence,
    page_id: str,
    page_restrictions: dict[str, Any],
    ancestors: list[dict[str, Any]],
    add_prefix: bool = False,
) -> ExternalAccess | None:
    """Standard expand-driven inheritance: read restrictions come from
    inline data on the page and each ancestor.

    add_prefix: True for the indexing path (Document.external_access) so
    group IDs carry the source-type prefix the search filter expects;
    False for the perm-sync path, where `upsert_document_external_perms`
    adds the prefix instead.
    """
    return _resolve_external_access(
        confluence_client=confluence_client,
        page_id=page_id,
        page_restrictions=page_restrictions,
        ancestors=ancestors,
        resolve_ancestor_restrictions=lambda ancestor: ancestor.get("restrictions", {}),
        add_prefix=add_prefix,
    )


def get_page_restrictions_with_per_ancestor_fetch(
    confluence_client: OnyxConfluence,
    page_id: str,
    page_restrictions: dict[str, Any],
    ancestors: list[dict[str, Any]],
    ancestor_restrictions_cache: dict[str, dict[str, Any] | None],
    add_prefix: bool = False,
) -> ExternalAccess | None:
    """CONFCLOUD-77618 variant: each ancestor's restrictions come from
    `restriction/byOperation`, with 403/404 -> "unreadable, skip" (the
    only correct semantic for drafts owned by another user).
    `ancestor_restrictions_cache` is caller-scoped per perm-sync run so
    sibling pages sharing ancestors only pay the GET once."""

    def _resolve(ancestor: dict[str, Any]) -> dict[str, Any] | None:
        ancestor_id = ancestor.get("id")
        if ancestor_id is None:
            return None
        cache_key = str(ancestor_id)
        if cache_key in ancestor_restrictions_cache:
            return ancestor_restrictions_cache[cache_key]
        restrictions = confluence_client.fetch_content_read_restrictions(cache_key)
        ancestor_restrictions_cache[cache_key] = restrictions
        return restrictions

    return _resolve_external_access(
        confluence_client=confluence_client,
        page_id=page_id,
        page_restrictions=page_restrictions,
        ancestors=ancestors,
        resolve_ancestor_restrictions=_resolve,
        add_prefix=add_prefix,
    )
