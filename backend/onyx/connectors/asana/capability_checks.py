"""Named indexing checks for Asana, composed from the gateway's operations.

Indexing needs a personal access token Asana accepts, the configured
workspace, the team or projects that narrow it, and tasks and their comments
readable in those projects. Asana has no permission sync.
"""

from collections.abc import Callable
from typing import Any, TypeVar

from onyx.connectors.asana.config import AsanaConnectorConfig
from onyx.connectors.asana.scope import check_projects, read_team, read_workspace
from onyx.connectors.asana.source_operations import (
    AsanaApiError,
    AsanaSourceOperations,
)
from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckNotApplicableError,
    CheckOutput,
    CredentialCapability,
    form_config,
    sign_in_timeout_text,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.models import CheckRowText, fit_summary

T = TypeVar("T")

DOCS_LINK: str = "https://docs.onyx.app/admins/connectors/official/asana"
SIGN_IN_CHECK_ID: str = "asana_token"
_WORKSPACE_CHECK_ID: str = "asana_workspace"
_TEAM_CHECK_ID: str = "asana_team"
_PROJECTS_CHECK_ID: str = "asana_projects"
_TASKS_CHECK_ID: str = "asana_tasks"
# check_id to the checks it runs after. A scope check that does not apply
# (no team or no projects set) does not stop the tasks sample.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    _WORKSPACE_CHECK_ID: (SIGN_IN_CHECK_ID,),
    _TEAM_CHECK_ID: (_WORKSPACE_CHECK_ID,),
    _PROJECTS_CHECK_ID: (_WORKSPACE_CHECK_ID,),
    _TASKS_CHECK_ID: (_WORKSPACE_CHECK_ID, _TEAM_CHECK_ID, _PROJECTS_CHECK_ID),
}
_REQUIRED_FIELDS: frozenset[str] = frozenset({"asana_workspace_id"})
# Projects the tasks sample lists to find one that is not archived.
_PROJECT_SAMPLE_SIZE: int = 20
_STORY_SAMPLE_SIZE: int = 50
_TIMEOUT_TEXT = CheckRowText(
    summary="Timed out",
    description=(
        "The check stopped after {time_limit} without an answer from Asana.\n"
        "Re-run the checks."
    ),
)
_SIGN_IN_TIMEOUT_TEXT = sign_in_timeout_text("Asana")


def _gateway(context: CapabilityCheckContext) -> AsanaSourceOperations:
    if not isinstance(context.source_operations, AsanaSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def _config(context: CapabilityCheckContext) -> AsanaConnectorConfig:
    return form_config(context, AsanaConnectorConfig)


def _workspace_id(config: AsanaConnectorConfig) -> str:
    return (config.asana_workspace_id or "").strip()


def _project_ids(config: AsanaConnectorConfig) -> list[str]:
    return [p.strip() for p in (config.asana_project_ids or "").split(",") if p.strip()]


def _team_id(config: AsanaConnectorConfig) -> str | None:
    return (config.asana_team_id or "").strip() or None


def _probe(action: Callable[[], T], failed: str) -> T:
    """The gateway maps a rejected token, a denied request, a rate limit and
    a transport failure itself; any other error status is unexpected here."""
    try:
        return action()
    except AsanaApiError as error:
        raise UnexpectedValidationError(f"{failed} {error}") from error


class _AsanaCheck(CapabilityCheck[AsanaConnectorConfig]):
    config_class = AsanaConnectorConfig

    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        requires_fields: frozenset[str] = _REQUIRED_FIELDS,
        validates_binding: bool = False,
        fails_when_unreachable: bool = False,
        timeout_text: CheckRowText = _TIMEOUT_TEXT,
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=display_name,
            depends_on=_DEPENDS_ON.get(check_id, ()),
            requires_connector_instance=False,
            requires_fields=requires_fields,
            remediation=remediation,
            docs_link=DOCS_LINK,
            validates_binding=validates_binding,
            fails_when_unreachable=fails_when_unreachable,
            timeout_text=timeout_text,
        )


class _TokenCheck(_AsanaCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=SIGN_IN_CHECK_ID,
            display_name="Sign in to Asana",
            remediation="Check the personal access token, or create a new one.",
            requires_fields=frozenset(),
            validates_binding=True,
            fails_when_unreachable=True,
            timeout_text=_SIGN_IN_TIMEOUT_TEXT,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        me: dict[str, Any] = _probe(
            _gateway(context).get_me, "Asana did not answer for the token."
        )
        identity: Any = me.get("email") or me.get("name")
        if not identity:
            return CheckOutput(summary="Signed in to Asana")
        return CheckOutput(summary=fit_summary("Signed in as ", str(identity)))


class _WorkspaceCheck(_AsanaCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=_WORKSPACE_CHECK_ID,
            display_name="Find the workspace",
            remediation=(
                "Check the Workspace ID, or use the token of a member of the workspace."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        workspace_id: str = _workspace_id(_config(context))
        workspace: dict[str, Any] = _probe(
            lambda: read_workspace(_gateway(context), workspace_id),
            "Onyx could not read the workspace.",
        )
        return CheckOutput(
            summary=fit_summary(
                "Found workspace ", str(workspace.get("name") or workspace_id)
            )
        )


class _TeamCheck(_AsanaCheck):
    """The team filter applies only when no project IDs are set, as in
    indexing."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_TEAM_CHECK_ID,
            display_name="Find the team",
            remediation="Check the Team ID, or use the token of a member of the team.",
        )

    def applies(self, form_state: FormState[AsanaConnectorConfig]) -> bool:
        return bool(_team_id(form_state.config)) and not _project_ids(form_state.config)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: AsanaConnectorConfig = _config(context)
        team_id: str | None = _team_id(config)
        if team_id is None or _project_ids(config):
            raise CheckNotApplicableError("No team filter applies.")
        team: dict[str, Any] = _probe(
            lambda: read_team(_gateway(context), team_id, _workspace_id(config)),
            "Onyx could not read the team.",
        )
        return CheckOutput(
            summary=fit_summary("Found team ", str(team.get("name") or team_id))
        )


class _ProjectsCheck(_AsanaCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=_PROJECTS_CHECK_ID,
            display_name="Find selected projects",
            remediation="Check each project ID, or add the token's user to the project.",
        )

    def applies(self, form_state: FormState[AsanaConnectorConfig]) -> bool:
        return bool(_project_ids(form_state.config))

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: AsanaConnectorConfig = _config(context)
        project_ids: list[str] = _project_ids(config)
        if not project_ids:
            raise CheckNotApplicableError("No projects are selected.")
        archived: list[str] = _probe(
            lambda: check_projects(
                _gateway(context), project_ids, _workspace_id(config)
            ),
            "Onyx could not read the selected projects.",
        )
        advisories: list[CheckAdvisory] = []
        if archived:
            advisories.append(
                CheckAdvisory(
                    message=(
                        f"Onyx skips archived projects: {', '.join(archived)}. "
                        "Unarchive them to index their tasks."
                    )
                )
            )
        return CheckOutput(
            summary=(
                fit_summary("Found project ", project_ids[0])
                if len(project_ids) == 1
                else f"Found all {len(project_ids)} projects"
            ),
            advisories=advisories,
        )


class _TasksCheck(_AsanaCheck):
    """Reads the first task of the first project in scope, its comments and
    its creator, as indexing does. No project at all FAILS: the connector
    would index nothing."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_TASKS_CHECK_ID,
            display_name="Sample tasks",
            remediation="Add the token's user to the projects to index.",
        )

    def _first_project(self, context: CapabilityCheckContext) -> dict[str, Any] | None:
        """The first project that is not archived: a selected one, else one
        of the workspace."""
        gateway: AsanaSourceOperations = _gateway(context)
        config: AsanaConnectorConfig = _config(context)
        project_ids: list[str] = _project_ids(config)
        projects = (
            (
                gateway.get_project(project_gid=project_id, opt_fields="name,archived")
                for project_id in project_ids
            )
            if project_ids
            else gateway.iterate_projects(
                workspace_gid=_workspace_id(config),
                opt_fields="name,archived",
                limit=_PROJECT_SAMPLE_SIZE,
            )
        )
        return _probe(
            lambda: next((p for p in projects if not p.get("archived")), None),
            "Onyx could not read the projects in scope.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: AsanaSourceOperations = _gateway(context)
        project: dict[str, Any] | None = self._first_project(context)
        if project is None:
            raise ConnectorValidationError(
                "Asana returned no project in scope that is not archived, so "
                "the connector would index nothing.",
                summary="No projects to index",
                description=(
                    "The token's user sees no project in scope that is not "
                    "archived.\nAdd the user to a project, or check the scope."
                ),
            )
        project_name: str = str(project.get("name") or project["gid"])
        tasks = gateway.iterate_project_tasks(
            project_gid=str(project["gid"]), opt_fields="name,created_by", limit=1
        )
        task: dict[str, Any] | None = _probe(
            lambda: next(tasks, None),
            f"Onyx could not read the tasks of project {project_name}.",
        )
        if task is None:
            return CheckOutput(
                summary=fit_summary("No tasks in ", project_name),
                advisories=[
                    CheckAdvisory(
                        message=(
                            f"Project {project_name} has no task, so task and "
                            "comment access were not checked."
                        )
                    )
                ],
            )
        stories = gateway.iterate_task_stories(
            task_gid=str(task["gid"]), limit=_STORY_SAMPLE_SIZE
        )
        comment: dict[str, Any] | None = _probe(
            lambda: next(
                (s for s in stories if s.get("resource_subtype") == "comment_added"),
                None,
            ),
            "Onyx could not read the task's comments.",
        )
        if comment is not None:
            _probe(
                lambda: gateway.get_story(
                    story_gid=str(comment["gid"]), opt_fields="text,created_by"
                ),
                "Onyx could not read a comment of the task.",
            )
        creator: dict[str, Any] = task.get("created_by") or {}
        if creator.get("gid"):
            _probe(
                lambda: gateway.get_user(
                    user_gid=str(creator["gid"]), opt_fields="name,email"
                ),
                "Onyx could not read the task's creator.",
            )
        return CheckOutput(
            summary=fit_summary("Read task ", str(task.get("name") or task["gid"]))
        )


def build_asana_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenCheck(),
        _WorkspaceCheck(),
        _TeamCheck(),
        _ProjectsCheck(),
        _TasksCheck(),
    ]
