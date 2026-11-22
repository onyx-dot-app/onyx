"""
Permissioning / AccessControl logic for JIRA Projects + Issues.
"""

from collections.abc import Callable
from typing import cast

from onyx.access.models import ExternalAccess
from onyx.connectors.jira.source_operations import JiraSourceOperations
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)


def get_project_permissions(
    source_operations: JiraSourceOperations,
    jira_project: str,
) -> ExternalAccess | None:
    """
    Fetch the project + issue level permissions / access-control.
    This functionality requires Enterprise Edition.

    Args:
        source_operations: The Jira gateway.
        jira_project: The JIRA project string.

    Returns:
        ExternalAccess object for the page. None if EE is not enabled or no restrictions found.
    """

    # Check if EE is enabled
    if not global_version.is_ee_version():
        return None

    ee_get_project_permissions = cast(
        Callable[
            [JiraSourceOperations, str],
            ExternalAccess | None,
        ],
        fetch_versioned_implementation(
            "onyx.external_permissions.jira.page_access", "get_project_permissions"
        ),
    )

    return ee_get_project_permissions(source_operations, jira_project)
