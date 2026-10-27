"""Validation shared by the Asana connector and its capability checks: the
mapping of gateway errors onto the validation-exception family, and the reads
of the configured workspace, team and projects.

Asana answers 404 for an item that does not exist and, mostly, for one the
token's user cannot see. It answers 400 for an ID that is not a number. So the
not-found messages name both causes.
"""

from collections.abc import Callable
from typing import Any, NoReturn, TypeVar

from onyx.connectors.asana.source_operations import (
    AsanaApiError,
    AsanaSourceOperations,
)
from onyx.connectors.capability_checks.models import sign_in_timeout_text
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    TimedOutValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)
from onyx.connectors.models import (
    CheckRowText,
    ConnectorMissingCredentialError,
    fit_summary,
)

T = TypeVar("T")

DOCS_LINK: str = "https://docs.onyx.app/admins/connectors/official/asana"
TIMEOUT_TEXT = CheckRowText(
    summary="Timed out",
    description=(
        "The check stopped after {time_limit} without an answer from Asana.\n"
        "Re-run the checks."
    ),
)
SIGN_IN_TIMEOUT_TEXT = sign_in_timeout_text("Asana")

_NEW_TOKEN_LINE = (
    "In Asana, open My settings > Apps > Manage Developer Apps, create a "
    "personal access token, and paste it in the account."
)
_NOT_FOUND_STATUSES: frozenset[int] = frozenset({400, 404})
# Workspaces a not-found row names, so it stays within three lines.
_MAX_LISTED_WORKSPACES: int = 3


def _status_line(error: AsanaApiError) -> str:
    return f"(HTTP {error.status_code})" if error.status_code else ""


def raise_for_asana_error(
    error: AsanaApiError | ConnectorMissingCredentialError,
    *,
    failed: str,
    sign_in: bool = False,
) -> NoReturn:
    """Maps a gateway error onto the validation-exception family. ``failed``
    leads the message of an error the caller cannot word better."""
    if isinstance(error, ConnectorMissingCredentialError):
        raise CredentialInvalidError(
            "The credential holds no Asana personal access token.",
            summary="No token saved in the account",
            description=(
                f"The account holds no personal access token.\n{_NEW_TOKEN_LINE}"
            ),
        ) from error
    if error.is_rate_limited:
        raise RateLimitedValidationError(
            "Asana rate limited the check. Run the checks again in a minute.",
            summary="Rate limited by Asana",
            description=(
                "Asana refused the request because of its rate limit. (HTTP 429)\n"
                "Wait a minute, then re-run."
            ),
        ) from error
    if error.status_code == 401:
        raise CredentialInvalidError(
            f"Asana rejected the personal access token: {error}",
            summary="Asana rejected the token",
            description=(
                f"The token is wrong, expired or revoked. (HTTP 401)\n{_NEW_TOKEN_LINE}"
            ),
        ) from error
    if error.status_code == 403:
        raise InsufficientPermissionsError(
            f"{failed} {error}",
            summary="Asana denied access",
            description=(
                f"Asana refused the request for this token. {_status_line(error)}\n"
                "Give the token's user access in Asana, or use another user's token."
            ),
        ) from error
    if error.timed_out:
        row: CheckRowText = SIGN_IN_TIMEOUT_TEXT if sign_in else TIMEOUT_TEXT
        raise TimedOutValidationError(
            f"Asana did not answer in time: {error}",
            summary=row.summary,
            description=row.description,
        ) from error
    if error.status_code is None:
        raise UnreachableValidationError(
            f"Onyx cannot connect to Asana: {error}",
            summary="Cannot reach Asana",
            description=(
                "The request failed before Asana answered.\n"
                "Check that Onyx can reach app.asana.com, then re-run."
            ),
        ) from error
    if error.status_code >= 500:
        raise UnexpectedValidationError(
            f"{failed} {error}",
            summary="Asana had a server error",
            description=(
                f"Asana answered with a server error. {_status_line(error)}\n"
                "Re-run the checks. If it repeats, check status.asana.com."
            ),
        ) from error
    raise UnexpectedValidationError(
        f"{failed} {error}",
        summary="Unexpected response from Asana",
        description=(
            f"Asana answered with an error this check does not expect. "
            f"{_status_line(error)}\nRe-run the checks. If it repeats, share the "
            "error details with support."
        ),
    ) from error


def probe(action: Callable[[], T], failed: str, *, sign_in: bool = False) -> T:
    try:
        return action()
    except (AsanaApiError, ConnectorMissingCredentialError) as error:
        raise_for_asana_error(error, failed=failed, sign_in=sign_in)


def _is_not_visible(error: AsanaApiError) -> bool:
    return error.status_code in _NOT_FOUND_STATUSES or error.status_code == 403


def _visible_workspaces_line(ops: AsanaSourceOperations) -> str:
    """Names the workspaces the token can read, so the admin can copy the
    right ID. Best effort: the not-found error stays the finding."""
    try:
        me: dict[str, Any] = ops.get_me()
    except (AsanaApiError, ConnectorMissingCredentialError):
        return "Copy the ID from the workspace's URL in Asana."
    workspaces: list[dict[str, Any]] = [
        workspace
        for workspace in me.get("workspaces") or []
        if isinstance(workspace, dict) and workspace.get("gid")
    ]
    if not workspaces:
        return "The token's user is a member of no workspace."
    listed: str = ", ".join(
        f"{workspace.get('name') or 'Untitled'} ({workspace['gid']})"
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
        if not _is_not_visible(error):
            raise_for_asana_error(error, failed="Onyx could not read the workspace.")
        visible: str = _visible_workspaces_line(ops)
        exception_class: type[ConnectorValidationError] = (
            InsufficientPermissionsError
            if error.status_code == 403
            else ConnectorValidationError
        )
        raise exception_class(
            f"Asana workspace {workspace_id} is not visible to the token. {visible} "
            f"{error}",
            summary=fit_summary("Workspace not found: ", workspace_id),
            description=(
                f"The Workspace ID is wrong, or the token's user is not a member. "
                f"{_status_line(error)}\n{visible}"
            ),
        ) from error


def read_team(
    ops: AsanaSourceOperations, team_id: str, workspace_id: str
) -> dict[str, Any]:
    """The configured team, which must belong to the configured workspace."""
    try:
        team: dict[str, Any] = ops.get_team(team_gid=team_id)
    except AsanaApiError as error:
        if not _is_not_visible(error):
            raise_for_asana_error(error, failed="Onyx could not read the team.")
        raise ConnectorValidationError(
            f"Asana team {team_id} is not visible to the token. {error}",
            summary=fit_summary("Team not found: ", team_id),
            description=(
                "The Team ID is wrong, or the team is private and the token's "
                f"user is not in it. {_status_line(error)}\n"
                "Copy the ID from the team's URL in Asana."
            ),
        ) from error
    organization: Any = team.get("organization")
    organization_gid: Any = (
        organization.get("gid") if isinstance(organization, dict) else None
    )
    if organization_gid and organization_gid != workspace_id:
        name: str = str(team.get("name") or team_id)
        raise ConnectorValidationError(
            f"Asana team {name} ({team_id}) belongs to workspace "
            f"{organization_gid}, not {workspace_id}.",
            summary="Team is in another workspace",
            description=(
                f"Team {name} belongs to workspace {organization_gid}, not "
                f"{workspace_id}.\nUse a team of the configured workspace."
            ),
        )
    return team


class ProjectScan:
    """What a read of the configured projects found."""

    def __init__(self) -> None:
        self.readable: list[dict[str, Any]] = []
        self.missing: list[str] = []
        self.elsewhere: list[str] = []
        self.archived: list[str] = []


def scan_projects(
    ops: AsanaSourceOperations, project_ids: list[str], workspace_id: str
) -> ProjectScan:
    scan = ProjectScan()
    for project_id in project_ids:
        try:
            project: dict[str, Any] = ops.get_project(
                project_gid=project_id, opt_fields="name,archived,workspace"
            )
        except AsanaApiError as error:
            if not _is_not_visible(error):
                raise_for_asana_error(
                    error, failed=f"Onyx could not read project {project_id}."
                )
            scan.missing.append(project_id)
            continue
        workspace: Any = project.get("workspace")
        project_workspace: Any = (
            workspace.get("gid") if isinstance(workspace, dict) else None
        )
        if project_workspace and project_workspace != workspace_id:
            scan.elsewhere.append(project_id)
            continue
        if project.get("archived"):
            scan.archived.append(str(project.get("name") or project_id))
            continue
        scan.readable.append(project)
    return scan


def raise_for_project_scan(scan: ProjectScan, project_ids: list[str]) -> None:
    """Fails when a configured project is missing or in another workspace:
    indexing would skip it without an error."""
    if not scan.missing and not scan.elsewhere:
        return
    lines: list[str] = []
    if scan.missing:
        lines.append(f"Not found: {', '.join(scan.missing)}.")
    if scan.elsewhere:
        lines.append(f"In another workspace: {', '.join(scan.elsewhere)}.")
    bad: int = len(scan.missing) + len(scan.elsewhere)
    summary: str = (
        fit_summary("Project not found: ", scan.missing[0])
        if bad == 1 and scan.missing
        else fit_summary("Project in other workspace: ", scan.elsewhere[0])
        if bad == 1
        else f"{bad} of {len(project_ids)} projects not usable"
    )
    raise ConnectorValidationError(
        "Some configured Asana projects cannot be indexed. " + " ".join(lines),
        summary=summary,
        description=(
            "Asana hides a wrong ID and a project the token's user cannot see "
            "the same way.\n" + " ".join(lines)
        ),
    )
