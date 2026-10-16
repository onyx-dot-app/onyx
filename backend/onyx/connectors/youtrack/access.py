from collections.abc import Callable
from typing import cast

from onyx.access.models import ExternalAccess
from onyx.connectors.youtrack.models import YouTrackIssueAccess
from onyx.utils.variable_functionality import (
    fetch_versioned_implementation,
    global_version,
)

_EE_ACCESS_MODULE: str = "onyx.external_permissions.youtrack.access"


def get_issue_access(
    base_url: str, issue: YouTrackIssueAccess
) -> ExternalAccess | None:
    if not global_version.is_ee_version():
        return None
    ee_issue_access = cast(
        Callable[[str, YouTrackIssueAccess], ExternalAccess],
        fetch_versioned_implementation(_EE_ACCESS_MODULE, "issue_access"),
    )
    return ee_issue_access(base_url, issue)


def get_project_node_access(base_url: str, project_id: str) -> ExternalAccess | None:
    if not global_version.is_ee_version():
        return None
    ee_project_node_access = cast(
        Callable[[str, str], ExternalAccess],
        fetch_versioned_implementation(_EE_ACCESS_MODULE, "project_node_access"),
    )
    return ee_project_node_access(base_url, project_id)
