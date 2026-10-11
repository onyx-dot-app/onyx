"""JSM-specific helpers: confirming the scoped project is a Service Management
project before indexing it.

JSM projects are still Jira projects (same issues REST API), so the JSM
connector reuses the Jira gateway. What differs is the *type* of project the
user should select, which the Jira REST ``project`` resource reports as
``projectTypeKey`` (``"service_desk"`` for JSM).
"""

from typing import Any

from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira.source_operations import JiraSourceOperations

SERVICE_DESK_PROJECT_TYPE = "service_desk"

# ``projectTypeKey`` never appears as an empty/invalid value from Jira; a
# missing key means the response did not include the field.
_UNKNOWN_PROJECT_TYPE = "unknown"


def get_project_type_key(
    source_operations: JiraSourceOperations, project_key: str
) -> str:
    """Returns the Jira ``projectTypeKey`` for a project.

    Raises ``ConnectorValidationError`` if the project does not exist or the
    credential cannot browse it, so the caller never conflates "API error"
    with "is not a Service Management project".
    """
    project: Any
    try:
        project = source_operations.get_project(project_key=project_key)
    except Exception as e:
        raise ConnectorValidationError(
            f"Could not verify project {project_key!r}: {e}"
        ) from e
    return project.get("projectTypeKey") or _UNKNOWN_PROJECT_TYPE


def require_service_management_project(
    source_operations: JiraSourceOperations, project_key: str
) -> None:
    """Raises ``ConnectorValidationError`` unless ``project_key`` is a Jira
    Service Management project, with a hint pointing to the right connector.
    """
    project_type = get_project_type_key(source_operations, project_key)
    if project_type == SERVICE_DESK_PROJECT_TYPE:
        return
    if project_type == _UNKNOWN_PROJECT_TYPE:
        raise ConnectorValidationError(
            f"Could not confirm that project {project_key!r} is a Jira "
            "Service Management project."
        )
    raise ConnectorValidationError(
        f"Project {project_key!r} is a Jira {project_type} project, not a "
        "Jira Service Management project. Pick a Service Management project, "
        "or use the Jira connector for software/business projects."
    )
