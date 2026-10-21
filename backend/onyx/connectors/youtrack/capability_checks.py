"""Named indexing checks for YouTrack, composed from the gateway's operations.

Indexing needs a base URL and token YouTrack accepts, configured projects the
token can read, and issues and their comments readable through search. The
permission sync checks build on the same helpers from EE.
"""

from collections.abc import Callable
from typing import TypeVar

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
    form_config,
)
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.youtrack.config import YouTrackConnectorConfig
from onyx.connectors.youtrack.connector import (
    missing_projects,
    projects_not_found,
    scoped_query,
)
from onyx.connectors.youtrack.source_operations import YouTrackSourceOperations

T = TypeVar("T")

PROBE_PAGE_SIZE: int = 1
# The gateway reads the base URL from the config, so no check runs without it.
REQUIRED_FIELDS: frozenset[str] = frozenset({"base_url"})


def gateway_from_context(context: CapabilityCheckContext) -> YouTrackSourceOperations:
    if not isinstance(context.source_operations, YouTrackSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def config_from_context(context: CapabilityCheckContext) -> YouTrackConnectorConfig:
    return form_config(context, YouTrackConnectorConfig)


def probe(action: Callable[[], T], denied: str) -> T:
    """Validation errors from the gateway already carry a user-facing message,
    so only other failures are wrapped."""
    try:
        return action()
    except RuntimeError as error:
        raise UnexpectedValidationError(f"{denied} {error}") from error


def scoped_issue_query(context: CapabilityCheckContext) -> str | None:
    return scoped_query(
        gateway_from_context(context), config_from_context(context).projects or []
    )


class _TokenCheck(CapabilityCheck[YouTrackConnectorConfig]):
    config_class = YouTrackConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="youtrack_token",
            display_name="YouTrack accepts the URL and token",
            requires_connector_instance=False,
            requires_fields=REQUIRED_FIELDS,
            remediation=(
                "Check the YouTrack URL, including the context path on YouTrack "
                "Server, and that the permanent token is valid."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        probe(gateway_from_context(context).get_me, "YouTrack did not answer.")


class _ProjectsCheck(CapabilityCheck[YouTrackConnectorConfig]):
    config_class = YouTrackConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="youtrack_projects",
            display_name="Configured projects are readable",
            requires_connector_instance=False,
            requires_fields=REQUIRED_FIELDS,
            remediation=(
                "Check each project short name, or give the token's user access "
                "to the project."
            ),
        )

    def applies(self, form_state: FormState[YouTrackConnectorConfig]) -> bool:
        return bool(form_state.config.projects)

    def run(self, context: CapabilityCheckContext) -> None:
        projects: list[str] = config_from_context(context).projects or []
        missing: list[str] = probe(
            lambda: missing_projects(gateway_from_context(context), projects),
            "The configured projects could not be checked.",
        )
        if missing:
            raise projects_not_found(missing)


class _IssuesCheck(CapabilityCheck[YouTrackConnectorConfig]):
    config_class = YouTrackConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="youtrack_issues",
            display_name="Issues and comments are readable",
            requires_connector_instance=False,
            requires_fields=REQUIRED_FIELDS,
            remediation="Give the token's user Read Issue and Read Issue Comment.",
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway: YouTrackSourceOperations = gateway_from_context(context)

        def read_first_issue() -> bool:
            """Whether an issue's comments were read."""
            query: str | None = scoped_issue_query(context)
            if query is None:
                return False
            next(
                gateway.iterate_slim_issues(query=query, page_size=PROBE_PAGE_SIZE),
                None,
            )
            page = next(
                gateway.iterate_issues(query=query, page_size=PROBE_PAGE_SIZE), None
            )
            if not page:
                return False
            gateway.list_issue_comments(issue_id=page[0].id)
            return True

        if probe(read_first_issue, "The token cannot read issues."):
            return None
        return CheckOutput(
            advisories=[
                CheckAdvisory(
                    message=(
                        "No issue in scope to read, so comment access was not checked."
                    )
                )
            ]
        )


def build_youtrack_indexing_checks() -> list[CapabilityCheck]:
    return [_TokenCheck(), _ProjectsCheck(), _IssuesCheck()]
