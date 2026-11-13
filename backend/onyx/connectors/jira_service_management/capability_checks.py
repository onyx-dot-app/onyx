"""Named indexing checks for Jira Service Management.

The checks register in ``capability_checks/registry.py``. Each check makes a
small probe with the gateway's operations, with ``fast=True``: a request the
site does not answer in time ends the check instead of waiting for its hang
guard.

The gateway reaches the site through the bound config fields
(``jira_base_url``, ``scoped_token``), so every check requires
``jira_base_url``. The credential picks the API family: an account email means
Cloud (REST v3), a token alone means Server / Data Center (REST v2).
"""

from typing import Any

from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
    form_config,
    sign_in_timeout_text,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira.source_operations import JiraApiError
from onyx.connectors.jira_service_management.source_operations import (
    JiraServiceManagementSourceOperations,
)
from onyx.connectors.models import CheckRowText
from onyx.connectors.source_operations import SourceOperations

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/jira_service_management"
_SIGN_IN_TIMEOUT_TEXT = sign_in_timeout_text("Jira Service Management")
_TIMEOUT_TEXT = CheckRowText(
    summary="Timed out",
    description=(
        "The check stopped because the site did not answer in time.\n"
        "Re-run the checks."
    ),
)

_SITE_FIELDS = frozenset({"jira_base_url"})
_PROJECT_FIELDS = frozenset({"jira_base_url", "project_key"})
_SIGN_IN_CHECK_ID = "jira_service_management_auth"

_PROBE_ISSUE_COUNT = 1


def _gateway(context: CapabilityCheckContext) -> JiraServiceManagementSourceOperations:
    gateway: SourceOperations | None = context.source_operations
    if not isinstance(gateway, JiraServiceManagementSourceOperations):
        raise TypeError(
            "Bug: the runner constructs the registered gateway for migrated sources."
        )
    return gateway


def _config(context: CapabilityCheckContext) -> JiraServiceManagementConnectorConfig:
    return form_config(context, JiraServiceManagementConnectorConfig)


class _JsmCheck(CapabilityCheck[JiraServiceManagementConnectorConfig]):
    config_class = JiraServiceManagementConnectorConfig

    def __init__(self, *, check_id: str, **kwargs: Any) -> None:
        kwargs.setdefault("timeout_text", _TIMEOUT_TEXT)
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            requires_connector_instance=False,
            docs_link=_DOCS_LINK,
            **kwargs,
        )


class _ServiceDeskAuthCheck(_JsmCheck):
    """Signs in the way the connector does and lists the site's service desks,
    which needs only the indexing scope of the credential."""

    def __init__(self) -> None:
        super().__init__(
            check_id=_SIGN_IN_CHECK_ID,
            display_name="Sign in to Jira Service Management",
            requires_fields=_SITE_FIELDS,
            validates_binding=True,
            fails_when_unreachable=True,
            timeout_text=_SIGN_IN_TIMEOUT_TEXT,
            remediation=(
                "Jira Cloud: enter the email of the token's Atlassian account "
                "and an API token. Data Center: leave the email empty and use a "
                "personal access token. Check the site URL, and create a new "
                "token if it expired."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        desks = _gateway(context).list_service_desks(fast=True)
        return CheckOutput(summary=f"Signed in, {len(desks)} service desk(s) visible")


class _ServiceDeskProjectCheck(_JsmCheck):
    """The configured project key is served by a service desk."""

    def __init__(self) -> None:
        super().__init__(
            check_id="jira_service_management_project",
            display_name="The project is a Jira Service Management project",
            requires_fields=_PROJECT_FIELDS,
            reports_field="project_key",
            depends_on=(_SIGN_IN_CHECK_ID,),
            remediation=(
                "Check the project key, and that the project is a Jira Service "
                "Management (service desk) project the account can access."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = _config(context)
        desks = _gateway(context).list_service_desks(fast=True)
        desk_keys = {desk.project_key.upper() for desk in desks}
        if config.project_key.upper() not in desk_keys:
            raise ConnectorValidationError(
                f"Project '{config.project_key}' is not a Jira Service Management "
                "project: no service desk serves it. Service desk projects: "
                f"{', '.join(sorted(desk_keys)) or 'none'}."
            )


class _RequestReadCheck(_JsmCheck):
    """One real ticket of the project is readable through the servicedesk
    API: request details, comments, and SLAs."""

    def __init__(self) -> None:
        super().__init__(
            check_id="jira_service_management_request_read",
            display_name="Tickets are readable through the service desk API",
            requires_fields=_PROJECT_FIELDS,
            depends_on=(_SIGN_IN_CHECK_ID,),
            remediation=(
                "Give the account access to the project's tickets, and check "
                "that Jira Service Management is enabled on the site."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput | None:
        gateway = _gateway(context)
        config = _config(context)
        keys = gateway.search_issue_keys(
            project_key=config.project_key,
            max_results=_PROBE_ISSUE_COUNT,
            fast=True,
        )
        if not keys:
            return CheckOutput(
                advisories=[
                    CheckAdvisory(
                        message=(
                            "The project has no ticket to read yet, so request "
                            "reads were not checked."
                        )
                    )
                ]
            )
        issue_key = keys[0]
        advisories: list[CheckAdvisory] = []
        try:
            gateway.get_request(issue_key=issue_key, fast=True)
            gateway.get_request_comments(issue_key=issue_key, fast=True)
            gateway.get_request_slas(issue_key=issue_key, fast=True)
        except JiraApiError as e:
            if getattr(e, "status_code", None) == 404 or "404" in str(e):
                advisories.append(
                    CheckAdvisory(
                        message=(
                            f"Sample issue '{issue_key}' has no customer request record; "
                            "request-specific enrichment will be applied when available."
                        )
                    )
                )
            else:
                raise
        except Exception:
            raise

        if advisories:
            return CheckOutput(advisories=advisories)
        return None


def build_jira_service_management_indexing_checks() -> list[CapabilityCheck]:
    return [
        _ServiceDeskAuthCheck(),
        _ServiceDeskProjectCheck(),
        _RequestReadCheck(),
    ]
