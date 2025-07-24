from typing import Any

from onyx.access.models import ExternalAccess
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
                    f"Email for user {user['username']} not found in Confluence"
                )
        else:
            if user.get("email") is not None:
                logger.warning(f"Cant find email for user {user.get('displayName')}")
                logger.warning(
                    "This user needs to make their email accessible in Confluence Settings"
                )

            logger.warning(f"no user email or username for {user}")

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


def get_page_restrictions(
    confluence_client: OnyxConfluence,
    page_id: str,
    page_restrictions: dict[str, Any],
    ancestors: list[dict[str, Any]],
) -> ExternalAccess | None:
    """
    This function gets the restrictions for a page. In Confluence, a child can have
    at MOST the same level accessibility as its immediate parent.

    If no restrictions are found anywhere, then return None, indicating that the page
    should inherit the space's restrictions.
    """
    found_user_emails: set[str] = set()
    found_group_names: set[str] = set()

    # NOTE: need the found_any_restriction, since we can find restrictions
    # but not be able to extract any user emails or group names
    # in this case, we should just give no access
    found_user_emails, found_group_names, found_any_page_level_restriction = (
        _extract_read_access_restrictions(
            confluence_client=confluence_client,
            restrictions=page_restrictions,
        )
    )
    # if there are individual page-level restrictions, then this is the accurate
    # restriction for the page. You cannot both have page-level restrictions AND
    # inherit restrictions from the parent.
    if found_any_page_level_restriction:
        return ExternalAccess(
            external_user_emails=found_user_emails,
            external_user_group_ids=found_group_names,
            is_public=False,
        )

    # ancestors seem to be in order from root to immediate parent
    # https://community.atlassian.com/forums/Confluence-questions/Order-of-ancestors-in-REST-API-response-Confluence-Server-amp/qaq-p/2385981
    # we want the restrictions from the immediate parent to take precedence, so we should
    # reverse the list
    for ancestor in reversed(ancestors):
        (
            ancestor_user_emails,
            ancestor_group_names,
            found_any_restrictions_in_ancestor,
        ) = _extract_read_access_restrictions(
            confluence_client=confluence_client,
            restrictions=ancestor.get("restrictions", {}),
        )
        if found_any_restrictions_in_ancestor:
            # if inheriting restrictions from the parent, then the first one we run into
            # should be applied (the reason why we'd traverse more than one ancestor is if
            # the ancestor also is in "inherit" mode.)
            logger.debug(
                f"Found user restrictions {ancestor_user_emails} and group restrictions {ancestor_group_names}"
                f"for document {page_id} based on ancestor {ancestor}"
            )
            return ExternalAccess(
                external_user_emails=ancestor_user_emails,
                external_user_group_ids=ancestor_group_names,
                is_public=False,
            )

    # we didn't find any restrictions, so the page inherits the space's restrictions
    return None
