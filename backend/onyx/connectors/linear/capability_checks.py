"""Named capability checks for Linear, composed from the gateway's operations.

Indexing needs a credential Linear accepts and, when the connector is scoped,
teams and projects Linear answers for. Permission sync needs a workspace
member rather than a guest, since a guest's token lists only the guest's own
teams and cannot name the workspace's members.
"""

from collections.abc import Callable
from typing import NoReturn, TypeVar

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
    form_config,
)
from onyx.connectors.exceptions import (
    CredentialInvalidError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.linear.config import LinearConnectorConfig
from onyx.connectors.linear.models import LinearViewer
from onyx.connectors.linear.scope import (
    issue_filter,
    missing_projects,
    missing_team_keys,
    normalize_team_keys,
    project_filter,
    project_scope,
    scope_error,
)
from onyx.connectors.linear.source_operations import (
    LinearAuthError,
    LinearGraphQLError,
    LinearSourceOperations,
)

T = TypeVar("T")

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/linear"
_PROBE_PAGE_SIZE = 1
_GUEST_REMEDIATION = (
    "Connect as a workspace member who belongs to every private team to index."
)


def _gateway(context: CapabilityCheckContext) -> LinearSourceOperations:
    if not isinstance(context.source_operations, LinearSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def _config(context: CapabilityCheckContext) -> LinearConnectorConfig:
    return form_config(context, LinearConnectorConfig)


def _raise_for_linear_error(error: Exception, denied: str) -> NoReturn:
    if isinstance(error, LinearAuthError):
        raise CredentialInvalidError(
            "Linear refused the credential. Check the API key or reconnect."
        ) from error
    if isinstance(error, LinearGraphQLError):
        raise UnexpectedValidationError(f"{denied} {error}") from error
    raise UnexpectedValidationError(f"{denied} {error}") from error


def _probe(action: Callable[[], T], denied: str) -> T:
    try:
        return action()
    except (LinearAuthError, LinearGraphQLError, RuntimeError) as error:
        _raise_for_linear_error(error, denied)


class _TokenCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="linear_token",
            display_name="Linear accepts the credential",
            requires_connector_instance=False,
            remediation="Check the API key, or reconnect through OAuth.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        _probe(_gateway(context).get_viewer, "Linear did not answer for the token.")


class _TeamsCheck(CapabilityCheck[LinearConnectorConfig]):
    config_class = LinearConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="linear_teams",
            display_name="Configured teams are visible",
            requires_connector_instance=False,
            requires_connector_config=True,
            remediation=(
                "Check each team key, or connect as a member of the team if it is private."
            ),
            docs_link=_DOCS_LINK,
        )

    def applies(self, form_state: FormState[LinearConnectorConfig]) -> bool:
        return bool(form_state.config.team_keys)

    def run(self, context: CapabilityCheckContext) -> None:
        keys: list[str] = normalize_team_keys(_config(context).team_keys)
        missing: list[str] = _probe(
            lambda: missing_team_keys(_gateway(context), keys),
            "The configured teams could not be checked.",
        )
        if missing:
            raise scope_error(missing, [])


class _ProjectsCheck(CapabilityCheck[LinearConnectorConfig]):
    config_class = LinearConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="linear_projects",
            display_name="Configured projects are visible",
            requires_connector_instance=False,
            requires_connector_config=True,
            remediation=(
                "Check each project name or URL, or connect as a member of the "
                "project's team if it is private."
            ),
            docs_link=_DOCS_LINK,
        )

    def applies(self, form_state: FormState[LinearConnectorConfig]) -> bool:
        return bool(form_state.config.projects)

    def run(self, context: CapabilityCheckContext) -> None:
        names, slug_ids = project_scope(_config(context).projects)
        missing: list[str] = _probe(
            lambda: missing_projects(_gateway(context), names, slug_ids),
            "The configured projects could not be checked.",
        )
        if missing:
            raise scope_error([], missing)


def _scoped_issue_filter(context: CapabilityCheckContext) -> dict[str, object]:
    config: LinearConnectorConfig = _config(context)
    names, slug_ids = project_scope(config.projects)
    return issue_filter(
        normalize_team_keys(config.team_keys), project_filter(names, slug_ids)
    )


class _IssuesCheck(CapabilityCheck[LinearConnectorConfig]):
    config_class = LinearConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="linear_issues",
            display_name="Issues are readable",
            requires_connector_instance=False,
            remediation="Grant the credential read access to issues.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        pages = _gateway(context).iterate_issues(
            issue_filter=_scoped_issue_filter(context), page_size=_PROBE_PAGE_SIZE
        )
        _probe(lambda: next(pages, None), "The credential cannot read issues.")


class _WorkspaceMemberCheck(CapabilityCheck):
    def __init__(self, capability: CredentialCapability) -> None:
        super().__init__(
            capability=capability,
            check_id=f"linear_workspace_member_{capability.value}",
            display_name="The connected user is a workspace member",
            requires_connector_instance=False,
            remediation=_GUEST_REMEDIATION,
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        viewer: LinearViewer = _probe(
            _gateway(context).get_viewer, "Linear did not answer for the token."
        )
        if viewer.guest:
            raise InsufficientPermissionsError(
                f"The connected Linear user is a guest. {_GUEST_REMEDIATION}"
            )


class _IssueAccessCheck(CapabilityCheck[LinearConnectorConfig]):
    config_class = LinearConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="linear_issue_access",
            display_name="Issue teams and sharing are readable",
            requires_connector_instance=False,
            remediation="Grant the credential read access to issues and teams.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway = _gateway(context)
        pages = gateway.iterate_issue_access(
            issue_filter=_scoped_issue_filter(context), page_size=_PROBE_PAGE_SIZE
        )

        def read_first_issue_and_its_share() -> None:
            page = next(pages, None)
            if page is None or not page.issues:
                return
            gateway.get_issue_share(issue_id=page.issues[0].id)

        _probe(
            read_first_issue_and_its_share, "The credential cannot read issue access."
        )


class _WorkspaceUsersCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="linear_workspace_users",
            display_name="Workspace users are listable",
            requires_connector_instance=False,
            remediation=_GUEST_REMEDIATION,
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        _probe(
            _gateway(context).list_workspace_users,
            "The credential cannot list the workspace's users.",
        )


class _TeamMembersCheck(CapabilityCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="linear_team_members",
            display_name="Team memberships are readable",
            requires_connector_instance=False,
            remediation="Grant the credential read access to teams.",
            docs_link=_DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway = _gateway(context)

        def read_first_teams_members() -> None:
            teams = gateway.list_teams()
            if teams:
                gateway.list_team_members(team_id=teams[0].id)

        _probe(read_first_teams_members, "The credential cannot read team memberships.")


def build_linear_indexing_checks() -> list[CapabilityCheck]:
    return [_TokenCheck(), _TeamsCheck(), _ProjectsCheck(), _IssuesCheck()]


def build_linear_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [
        _WorkspaceMemberCheck(CredentialCapability.DOC_PERMISSION_SYNC),
        _IssueAccessCheck(),
    ]


def build_linear_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _WorkspaceMemberCheck(CredentialCapability.EXTERNAL_GROUP_SYNC),
        _WorkspaceUsersCheck(),
        _TeamMembersCheck(),
    ]
