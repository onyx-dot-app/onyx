"""Reads of the configured Asana scope, shared by the connector's settings
validation and the capability checks: the workspace, the team filter, and the
selected projects. Asana answers 404 for an item that does not exist and
for one the token's user cannot see, so the messages name both causes."""

from typing import Any

from onyx.connectors.asana.source_operations import (
    AsanaApiError,
    AsanaSourceOperations,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import fit_summary

# Workspaces a not-found row names, so it stays within three lines.
_MAX_LISTED_WORKSPACES: int = 3


def _readable_workspaces_line(ops: AsanaSourceOperations) -> str:
    """Names the workspaces the token can read, so the admin can copy the
    right ID. Best effort: the not-found error stays the finding."""
    try:
        workspaces: list[dict[str, Any]] = ops.get_me().get("workspaces") or []
    except Exception:
        return "Copy the ID from the workspace's URL in Asana."
    if not workspaces:
        return "The token's user is a member of no workspace."
    listed: str = ", ".join(
        f"{workspace.get('name') or 'Untitled'} ({workspace.get('gid')})"
        for workspace in workspaces[:_MAX_LISTED_WORKSPACES]
    )
    more: int = len(workspaces) - _MAX_LISTED_WORKSPACES
    return f"The token can read: {listed}" + (f" and {more} more." if more > 0 else ".")


def read_workspace(ops: AsanaSourceOperations, workspace_id: str) -> dict[str, Any]:
    """The configured workspace. A workspace the token cannot read fails with
    the workspaces it can read."""
    try:
        return ops.get_workspace(workspace_gid=workspace_id)
    except AsanaApiError as error:
        if not error.not_found:
            raise
        readable: str = _readable_workspaces_line(ops)
        raise ConnectorValidationError(
            f"Asana workspace {workspace_id} is not visible to the token. {readable}",
            summary=fit_summary("Workspace not found: ", workspace_id),
            description=(
                "The Workspace ID is wrong, or the token's user is not a member. "
                f"(HTTP {error.status_code})\n{readable}"
            ),
        ) from error


def read_team(
    ops: AsanaSourceOperations, team_id: str, workspace_id: str
) -> dict[str, Any]:
    """The configured team, which must belong to the configured workspace."""
    try:
        team: dict[str, Any] = ops.get_team(team_gid=team_id)
    except AsanaApiError as error:
        if not error.not_found:
            raise
        raise ConnectorValidationError(
            f"Asana team {team_id} is not visible to the token.",
            summary=fit_summary("Team not found: ", team_id),
            description=(
                "The Team ID is wrong, or the team is private and the token's "
                f"user is not in it. (HTTP {error.status_code})\n"
                "Copy the ID from the team's URL in Asana."
            ),
        ) from error
    team_workspace: str | None = (team.get("organization") or {}).get("gid")
    if team_workspace and team_workspace != workspace_id:
        raise ConnectorValidationError(
            f"Asana team {team_id} belongs to workspace {team_workspace}, not "
            f"{workspace_id}.",
            summary="Team is in another workspace",
            description=(
                f"Team {team.get('name') or team_id} belongs to workspace "
                f"{team_workspace}, not {workspace_id}.\n"
                "Use a team of the configured workspace."
            ),
        )
    return team


def check_projects(
    ops: AsanaSourceOperations, project_ids: list[str], workspace_id: str
) -> list[str]:
    """Reads every selected project and returns the names of the archived
    ones, which indexing skips. A project that is missing or in another
    workspace fails: indexing would skip it without an error."""
    missing: list[str] = []
    elsewhere: list[str] = []
    archived: list[str] = []
    for project_id in project_ids:
        try:
            project: dict[str, Any] = ops.get_project(
                project_gid=project_id, opt_fields="name,archived,workspace"
            )
        except AsanaApiError as error:
            if not error.not_found:
                raise
            missing.append(project_id)
            continue
        project_workspace: str | None = (project.get("workspace") or {}).get("gid")
        if project_workspace and project_workspace != workspace_id:
            elsewhere.append(project_id)
        elif project.get("archived"):
            archived.append(str(project.get("name") or project_id))
    if not missing and not elsewhere:
        return archived
    lines: list[str] = []
    if missing:
        lines.append(f"Not found: {', '.join(missing)}.")
    if elsewhere:
        lines.append(f"In another workspace: {', '.join(elsewhere)}.")
    bad: int = len(missing) + len(elsewhere)
    raise ConnectorValidationError(
        "Some selected Asana projects cannot be indexed. " + " ".join(lines),
        summary=(
            fit_summary("Project not found: ", missing[0])
            if bad == 1 and missing
            else f"{bad} of {len(project_ids)} projects not usable"
        ),
        description=(
            "Asana hides a wrong ID and a project the token's user cannot see "
            "the same way.\n" + " ".join(lines)
        ),
    )
