"""Named indexing checks for YouTrack, composed from the gateway's operations.

Indexing needs a base URL and token YouTrack accepts, configured projects the
token can read, and issues and their comments readable through search. The
permission sync checks build on the same helpers from EE.
"""

from collections.abc import Callable
from typing import TypeVar

from onyx.configs.constants import DocumentSource
from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.graph import check_node
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
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
        self.init_from_graph(check_node(DocumentSource.YOUTRACK, "youtrack_token"))

    def run(self, context: CapabilityCheckContext) -> None:
        probe(gateway_from_context(context).get_me, "YouTrack did not answer.")


class _ProjectsCheck(CapabilityCheck[YouTrackConnectorConfig]):
    config_class = YouTrackConnectorConfig

    def __init__(self) -> None:
        self.init_from_graph(check_node(DocumentSource.YOUTRACK, "youtrack_projects"))

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
        self.init_from_graph(check_node(DocumentSource.YOUTRACK, "youtrack_issues"))

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
