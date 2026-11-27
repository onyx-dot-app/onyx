"""Indexing checks for Jira Service Management.

The account must sign in, the project must be a service desk the account can
read, and that desk's requests and comments must be readable.
"""

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
    form_config,
)
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.connector import project_jql
from onyx.connectors.jira_service_management.source_operations import (
    JiraServiceManagementSourceOperations,
)

_PROBE_LIMIT: int = 1
_SIGN_IN_FIELDS: frozenset[str] = frozenset({"jira_base_url"})


def gateway_from_context(
    context: CapabilityCheckContext,
) -> JiraServiceManagementSourceOperations:
    if not isinstance(context.source_operations, JiraServiceManagementSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return context.source_operations


def config_from_context(
    context: CapabilityCheckContext,
) -> JiraServiceManagementConnectorConfig:
    return form_config(context, JiraServiceManagementConnectorConfig)


class _AccountCheck(CapabilityCheck[JiraServiceManagementConnectorConfig]):
    config_class = JiraServiceManagementConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="jsm_account",
            display_name="Jira accepts the site and account",
            requires_connector_instance=False,
            requires_fields=_SIGN_IN_FIELDS,
            validates_binding=True,
            remediation=(
                "Check the Jira site URL. Cloud needs the account email and an "
                "API token. Data Center needs a personal access token and no email."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        gateway_from_context(context).get_myself()


class _ServiceDeskCheck(CapabilityCheck[JiraServiceManagementConnectorConfig]):
    config_class = JiraServiceManagementConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="jsm_service_desk",
            display_name="The project is a service desk",
            requires_connector_instance=False,
            requires_fields=_SIGN_IN_FIELDS | frozenset({"project_key"}),
            remediation=(
                "Check the project key. The account needs the Service Desk Team "
                "role on that service desk."
            ),
        )

    def applies(
        self, form_state: FormState[JiraServiceManagementConnectorConfig]
    ) -> bool:
        return bool(form_state.config.project_key)

    def run(self, context: CapabilityCheckContext) -> None:
        gateway_from_context(context).find_service_desk(
            project_key=config_from_context(context).project_key
        )


class _RequestsCheck(CapabilityCheck[JiraServiceManagementConnectorConfig]):
    config_class = JiraServiceManagementConnectorConfig

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id="jsm_requests",
            display_name="Requests and comments are readable",
            requires_connector_instance=False,
            requires_fields=_SIGN_IN_FIELDS | frozenset({"project_key"}),
            remediation=(
                "Give the account the Service Desk Team role, and Browse Projects "
                "on the service project, so it can read every request and comment."
            ),
        )

    def applies(
        self, form_state: FormState[JiraServiceManagementConnectorConfig]
    ) -> bool:
        return bool(form_state.config.project_key)

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway = gateway_from_context(context)
        config = config_from_context(context)
        desk = gateway.find_service_desk(project_key=config.project_key)
        page = gateway.list_requests(service_desk_id=desk.id, limit=_PROBE_LIMIT)
        gateway.search_issues(jql=project_jql(config.project_key), limit=_PROBE_LIMIT)
        if not page.values:
            return CheckOutput(
                advisories=[
                    CheckAdvisory(
                        message=(
                            "This service desk has no requests, so comment "
                            "access was not checked."
                        )
                    )
                ]
            )
        issue_key = page.values[0].issue_key
        gateway.get_request(issue_key=issue_key)
        gateway.list_comments(issue_key=issue_key, limit=_PROBE_LIMIT)
        return None


def build_jsm_indexing_checks() -> list[CapabilityCheck]:
    return [_AccountCheck(), _ServiceDeskCheck(), _RequestsCheck()]
