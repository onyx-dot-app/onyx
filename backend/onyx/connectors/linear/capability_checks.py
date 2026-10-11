"""Named indexing checks for Linear, composed from the gateway's operations.

Indexing needs a credential Linear accepts and, when the connector is scoped,
teams and projects Linear answers for. The permission sync checks build on the
same helpers from EE.
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
    UnexpectedValidationError,
)
from onyx.connectors.linear.config import LinearConnectorConfig
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

DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/linear"
PROBE_PAGE_SIZE = 1


def gateway_from_context(context: CapabilityCheckContext) -> LinearSourceOperations:
    if not isinstance(context.source_operations, LinearSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def config_from_context(context: CapabilityCheckContext) -> LinearConnectorConfig:
    return form_config(context, LinearConnectorConfig)


def _raise_for_linear_error(error: Exception, denied: str) -> NoReturn:
    if isinstance(error, LinearAuthError):
        raise CredentialInvalidError(
            "Linear refused the credential. Check the API key or reconnect."
        ) from error
    if isinstance(error, LinearGraphQLError):
        raise UnexpectedValidationError(f"{denied} {error}") from error
    raise UnexpectedValidationError(f"{denied} {error}") from error


def probe(action: Callable[[], T], denied: str) -> T:
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
            docs_link=DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        probe(
            gateway_from_context(context).get_viewer,
            "Linear did not answer for the token.",
        )


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
            docs_link=DOCS_LINK,
        )

    def applies(self, form_state: FormState[LinearConnectorConfig]) -> bool:
        return bool(form_state.config.team_keys)

    def run(self, context: CapabilityCheckContext) -> None:
        keys: list[str] = normalize_team_keys(config_from_context(context).team_keys)
        missing: list[str] = probe(
            lambda: missing_team_keys(gateway_from_context(context), keys),
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
            docs_link=DOCS_LINK,
        )

    def applies(self, form_state: FormState[LinearConnectorConfig]) -> bool:
        return bool(form_state.config.projects)

    def run(self, context: CapabilityCheckContext) -> None:
        names, slug_ids = project_scope(config_from_context(context).projects)
        missing: list[str] = probe(
            lambda: missing_projects(gateway_from_context(context), names, slug_ids),
            "The configured projects could not be checked.",
        )
        if missing:
            raise scope_error([], missing)


def scoped_issue_filter(context: CapabilityCheckContext) -> dict[str, object]:
    config: LinearConnectorConfig = config_from_context(context)
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
            docs_link=DOCS_LINK,
        )

    def run(self, context: CapabilityCheckContext) -> None:
        pages = gateway_from_context(context).iterate_issues(
            issue_filter=scoped_issue_filter(context), page_size=PROBE_PAGE_SIZE
        )
        probe(lambda: next(pages, None), "The credential cannot read issues.")


def build_linear_indexing_checks() -> list[CapabilityCheck]:
    return [_TokenCheck(), _TeamsCheck(), _ProjectsCheck(), _IssuesCheck()]
