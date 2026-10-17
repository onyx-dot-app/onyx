"""
Permissioning / AccessControl logic for JSM Projects + Issues.
"""

from collections.abc import Callable
from typing import cast

from jira import JIRA

from onyx.access.models import ExternalAccess
from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import global_version


def get_project_permissions(
    jsm_client: JIRA,
    jsm_project: str,
    add_prefix: bool = False,
) -> ExternalAccess | None:
    """
    Fetch the project + issue level permissions / access-control.
    This functionality requires Enterprise Edition.

    Args:
        jsm_client: The JSM client instance.
        jsm_project: The JSM project string.
        add_prefix: When True, prefix group IDs with source type (for indexing path).
                   When False (default), leave unprefixed (for permission sync path
                   where upsert_document_external_perms handles prefixing).

    Returns:
        ExternalAccess object for the page. None if EE is not enabled or no restrictions found.
    """

    # Check if EE is enabled
    if not global_version.is_ee_version():
        return None

    ee_get_project_permissions = cast(
        Callable[
            [JSM, str, bool],
            ExternalAccess | None,
        ],
        fetch_versioned_implementation(
            "onyx.external_permissions.jsm.page_access", "get_project_permissions"
        ),
    )

    return ee_get_project_permissions(
        jsm_client,
        jsm_project,
        add_prefix,
    )
