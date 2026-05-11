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
    add_prefix: bool = False,
) -> ExternalAccess | None:
    """
    Get page access restrictions for a Confluence page.
    This functionality requires Enterprise Edition.

    add_prefix: True for the indexing path (Document.external_access) so group
    ids carry the source-type prefix the search filter expects. False for the
    permission-sync path, where upsert_document_external_perms adds the prefix.

    Returns ExternalAccess for the page, or None if EE is not enabled or no
    restrictions are found.
    """
    if not global_version.is_ee_version():
        return None

    ee_get_all_page_restrictions = cast(
        Callable[
            [OnyxConfluence, str, dict[str, Any], list[dict[str, Any]], bool],
            ExternalAccess | None,
        ],
        fetch_versioned_implementation(
            "onyx.external_permissions.confluence.page_access", "get_page_restrictions"
        ),
    )

    return ee_get_all_page_restrictions(
        confluence_client, page_id, page_restrictions, ancestors, add_prefix
    )


def get_all_space_permissions(
    confluence_client: OnyxConfluence,
    is_cloud: bool,
    add_prefix: bool = False,
) -> dict[str, ExternalAccess]:
    """
    Get access permissions for all spaces in Confluence.
    This functionality requires Enterprise Edition.

    add_prefix: True for the indexing path (Document.external_access) so group
    ids carry the source-type prefix the search filter expects. False for the
    permission-sync path, where upsert_document_external_perms adds the prefix.

    Returns a mapping of space key to ExternalAccess. Empty dict if EE is not
    enabled.
    """
    if not global_version.is_ee_version():
        return {}

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

    return ee_get_all_space_permissions(confluence_client, is_cloud, add_prefix)
