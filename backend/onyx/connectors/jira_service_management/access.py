from typing import Any

from jira import JIRA


def get_project_permissions(
    jira_client: JIRA,
    jira_project: str,
    add_prefix: bool = False,
) -> Any:
    """Placeholder hook for Jira Service Management project permission fetching."""
    return None
