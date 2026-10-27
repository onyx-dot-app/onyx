"""Named indexing checks for Asana, composed from the gateway's operations.

Indexing needs a personal access token Asana accepts, the configured
workspace, the team or projects that narrow it, and tasks and their comments
readable in those projects. Asana has no permission sync.
"""

import functools
from typing import Any

from onyx.connectors.asana.config import AsanaConnectorConfig
from onyx.connectors.asana.source_operations import AsanaSourceOperations
from onyx.connectors.asana.validation import (
    DOCS_LINK,
    SIGN_IN_TIMEOUT_TEXT,
    TIMEOUT_TEXT,
    probe,
    raise_for_project_scan,
    read_team,
    read_workspace,
    scan_projects,
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
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import CheckRowText, fit_summary

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
_WORKSPACE_FIELD: str = "asana_workspace_id"
_REQUIRED_FIELDS: frozenset[str] = frozenset({_WORKSPACE_FIELD})
# Projects the tasks sample reads to find one that is not archived.
_PROJECT_SAMPLE_SIZE: int = 20
_STORY_SAMPLE_SIZE: int = 50
_COMMENT_SUBTYPE: str = "comment_added"


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
    return [
        project_id.strip()
        for project_id in (config.asana_project_ids or "").split(",")
        if project_id.strip()
    ]


def _team_id(config: AsanaConnectorConfig) -> str | None:
    return (config.asana_team_id or "").strip() or None


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
        timeout_text: CheckRowText = TIMEOUT_TEXT,
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
            timeout_text=SIGN_IN_TIMEOUT_TEXT,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        me: dict[str, Any] = probe(
            _gateway(context).get_me,
            "Asana did not answer for the token.",
            sign_in=True,
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
        workspace: dict[str, Any] = read_workspace(_gateway(context), workspace_id)
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
            remediation=(
                "Check the Team ID, or use the token of a member of the team."
            ),
        )

    def applies(self, form_state: FormState[AsanaConnectorConfig]) -> bool:
        return bool(_team_id(form_state.config)) and not _project_ids(form_state.config)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: AsanaConnectorConfig = _config(context)
        team_id: str | None = _team_id(config)
        if team_id is None or _project_ids(config):
            raise CheckNotApplicableError("No team filter applies.")
        team: dict[str, Any] = read_team(
            _gateway(context), team_id, _workspace_id(config)
        )
        return CheckOutput(
            summary=fit_summary("Found team ", str(team.get("name") or team_id))
        )


class _ProjectsCheck(_AsanaCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id=_PROJECTS_CHECK_ID,
            display_name="Find selected projects",
            remediation=(
                "Check each project ID, or add the token's user to the project."
            ),
        )

    def applies(self, form_state: FormState[AsanaConnectorConfig]) -> bool:
        return bool(_project_ids(form_state.config))

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: AsanaConnectorConfig = _config(context)
        project_ids: list[str] = _project_ids(config)
        if not project_ids:
            raise CheckNotApplicableError("No projects are selected.")
        scan = scan_projects(_gateway(context), project_ids, _workspace_id(config))
        raise_for_project_scan(scan, project_ids)
        advisories: list[CheckAdvisory] = []
        if scan.archived:
            advisories.append(
                CheckAdvisory(
                    message=(
                        "Onyx skips archived projects: "
                        f"{', '.join(scan.archived)}. Unarchive them to index "
                        "their tasks."
                    )
                )
            )
        if len(project_ids) == 1:
            return CheckOutput(
                summary=fit_summary(
                    "Found project ",
                    str(
                        scan.readable[0].get("name")
                        if scan.readable
                        else project_ids[0]
                    ),
                ),
                advisories=advisories,
            )
        return CheckOutput(
            summary=f"Found all {len(project_ids)} projects", advisories=advisories
        )


def _first_project(context: CapabilityCheckContext) -> dict[str, Any] | None:
    """The first project that indexing would read: a configured one, else
    the first one of the workspace. Archived projects are skipped, as in
    indexing."""
    gateway: AsanaSourceOperations = _gateway(context)
    config: AsanaConnectorConfig = _config(context)
    project_ids: list[str] = _project_ids(config)
    if project_ids:
        for project_id in project_ids:
            project: dict[str, Any] = probe(
                functools.partial(
                    gateway.get_project,
                    project_gid=project_id,
                    opt_fields="name,archived",
                ),
                f"Onyx could not read project {project_id}.",
            )
            if not project.get("archived"):
                return {**project, "gid": project.get("gid") or project_id}
        return None
    projects = gateway.iterate_projects(
        workspace_gid=_workspace_id(config),
        opt_fields="name,archived",
        limit=_PROJECT_SAMPLE_SIZE,
    )
    return probe(
        lambda: next(
            (candidate for candidate in projects if not candidate.get("archived")),
            None,
        ),
        "Onyx could not list the workspace's projects.",
    )


class _TasksCheck(_AsanaCheck):
    """Reads the first task of the first project in scope, its comments and
    its creator. No project at all FAILS: the connector would index
    nothing."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_TASKS_CHECK_ID,
            display_name="Sample tasks",
            remediation="Add the token's user to the projects to index.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: AsanaSourceOperations = _gateway(context)
        project: dict[str, Any] | None = _first_project(context)
        if project is None:
            raise ConnectorValidationError(
                "Asana returned no project that is not archived in scope, so "
                "the connector would index nothing.",
                summary="No projects to index",
                description=(
                    "The token's user sees no project that is not archived in "
                    "the scope.\nAdd the user to a project, or check the scope."
                ),
            )
        project_gid: str = str(project["gid"])
        project_name: str = str(project.get("name") or project_gid)
        tasks = gateway.iterate_project_tasks(
            project_gid=project_gid, opt_fields="name,created_by", limit=1
        )
        task: dict[str, Any] | None = probe(
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
        task_gid: str = str(task["gid"])
        stories = gateway.iterate_task_stories(
            task_gid=task_gid, limit=_STORY_SAMPLE_SIZE
        )
        comment: dict[str, Any] | None = probe(
            lambda: next(
                (
                    story
                    for story in stories
                    if story.get("resource_subtype") == _COMMENT_SUBTYPE
                ),
                None,
            ),
            "Onyx could not read the task's comments.",
        )
        if comment is not None:
            probe(
                lambda: gateway.get_story(
                    story_gid=str(comment["gid"]),
                    opt_fields="text,created_by,created_at",
                ),
                "Onyx could not read a comment of the task.",
            )
        creator: Any = task.get("created_by")
        if isinstance(creator, dict) and creator.get("gid"):
            probe(
                lambda: gateway.get_user(
                    user_gid=str(creator["gid"]), opt_fields="name,email"
                ),
                "Onyx could not read the task's creator.",
            )
        return CheckOutput(
            summary=fit_summary("Read task ", str(task.get("name") or task_gid)),
            advisories=(
                []
                if comment is not None
                else [
                    CheckAdvisory(
                        message=(
                            "The sampled task has no comment, so comment access "
                            "was not checked."
                        )
                    )
                ]
            ),
        )


def build_asana_indexing_checks() -> list[CapabilityCheck]:
    return [
        _TokenCheck(),
        _WorkspaceCheck(),
        _TeamCheck(),
        _ProjectsCheck(),
        _TasksCheck(),
    ]
