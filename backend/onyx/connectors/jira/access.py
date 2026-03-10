"""
Permissioning / AccessControl logic for JIRA Projects + Issues.
"""

from collections.abc import Callable
from typing import cast

from jira import JIRA

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.utils.variable_functionality import fetch_versioned_implementation
from onyx.utils.variable_functionality import global_version


def get_project_permissions(
    jira_client: JIRA,
    jira_project: str,
    add_prefix: bool = False,
    source: DocumentSource = DocumentSource.JIRA,
) -> ExternalAccess | None:
    """
    Fetch the project + issue level permissions / access-control.
    This functionality requires Enterprise Edition.

    Args:
        jira_client: The JIRA client instance.
        jira_project: The JIRA project string.
        add_prefix: When True, prefix group IDs with source type (for indexing path).
                   When False (default), leave unprefixed (for permission sync path
                   where upsert_document_external_perms handles prefixing).
        source: The DocumentSource to use when prefixing group IDs.
                Defaults to JIRA; JSM connector passes JIRA_SERVICE_MANAGEMENT.

    Returns:
        ExternalAccess object for the page. None if EE is not enabled or no restrictions found.
    """

    # Check if EE is enabled
    if not global_version.is_ee_version():
        return None

    ee_get_project_permissions = cast(
        Callable[
            [JIRA, str, bool, DocumentSource],
            ExternalAccess | None,
        ],
        fetch_versioned_implementation(
            "onyx.external_permissions.jira.page_access", "get_project_permissions"
        ),
    )

    return ee_get_project_permissions(
        jira_client,
        jira_project,
        add_prefix,
        source,
    )
