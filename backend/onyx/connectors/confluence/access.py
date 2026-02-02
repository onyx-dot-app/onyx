from collections.abc import Callable
from typing import Any
from typing import cast

from onyx.access.models import ExternalAccess
from onyx.connectors.confluence.onyx_confluence import OnyxConfluence
from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import global_version


def get_page_restrictions(
    confluence_client: OnyxConfluence,
    page_id: str,
    page_restrictions: dict[str, Any],
    ancestors: list[dict[str, Any]],
) -> ExternalAccess | None:
    """
    Get page access restrictions for a Confluence page.
    This functionality requires Enterprise Edition.

    Note: This wrapper is only called from permission sync path. Group IDs are
    left unprefixed here because upsert_document_external_perms handles prefixing.

    Args:
        confluence_client: OnyxConfluence client instance
        page_id: The ID of the page
        page_restrictions: Dictionary containing page restriction data
        ancestors: List of ancestor pages with their restriction data

    Returns:
        ExternalAccess object for the page. None if EE is not enabled or no restrictions found.
    """
    # Check if EE is enabled
    if not global_version.is_ee_version():
        return None

    # Fetch the EE implementation
    ee_get_all_page_restrictions = cast(
        Callable[
            [OnyxConfluence, str, dict[str, Any], list[dict[str, Any]], bool],
            ExternalAccess | None,
        ],
        fetch_versioned_implementation(
            "onyx.external_permissions.confluence.page_access", "get_page_restrictions"
        ),
    )

    # add_prefix=False: permission sync path - upsert_document_external_perms handles prefixing
    return ee_get_all_page_restrictions(
        confluence_client, page_id, page_restrictions, ancestors, False
    )


def get_all_space_permissions(
    confluence_client: OnyxConfluence,
    is_cloud: bool,
) -> dict[str, ExternalAccess]:
    """
    Get access permissions for all spaces in Confluence.
    This functionality requires Enterprise Edition.

    Note: This wrapper is only called from permission sync path. Group IDs are
    left unprefixed here because upsert_document_external_perms handles prefixing.

    Args:
        confluence_client: OnyxConfluence client instance
        is_cloud: Whether this is a Confluence Cloud instance

    Returns:
        Dictionary mapping space keys to ExternalAccess objects. Empty dict if EE is not enabled.
    """
    # Check if EE is enabled
    if not global_version.is_ee_version():
        return {}

    # Fetch the EE implementation
    ee_get_all_space_permissions = cast(
        Callable[
            [OnyxConfluence, bool, bool],
            dict[str, ExternalAccess],
        ],
        fetch_versioned_implementation(
            "onyx.external_permissions.confluence.space_access",
            "get_all_space_permissions",
        ),
    )

    # add_prefix=False: permission sync path - upsert_document_external_perms handles prefixing
    return ee_get_all_space_permissions(confluence_client, is_cloud, False)
