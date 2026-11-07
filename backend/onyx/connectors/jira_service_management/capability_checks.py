"""Capability checks for the Jira Service Management connector.

A service desk is a Jira project, so the sign-in and project probes are the
Jira connector's: the same gateway family, the same credential, the same
errors. Two things differ, and each has a check:

- The project must be a *service desk* project, not a Jira Software or Jira
  Work Management project. ``_ServiceDeskProjectCheck`` reads it through
  ``servicedeskapi``.
- The servicedeskapi needs a Service Desk *agent* licence. A portal-only
  account indexes requests fine but gets no service desk metadata, so that
  check advises instead of failing.

The checks use ``fast=True`` probes, like the Jira ones, and run through the
registered JSM gateway.
"""

import time
from typing import Any

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CheckStep,
    CredentialCapability,
    sign_in_timeout_text,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    TimedOutValidationError,
    UnexpectedValidationError,
)
from onyx.connectors.jira.connector import build_jql_query
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementConnectorConfig,
)
from onyx.connectors.jira_service_management.source_operations import (
    JiraServiceManagementSourceOperations,
    JsmApiError,
)
from onyx.connectors.models import CheckRowText
from onyx.connectors.source_operations import SourceOperations
from onyx.utils.logger import setup_logger

logger = setup_logger()

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/jira"
_SITE_FIELDS = frozenset({"jira_base_url"})
# The probes below read the configured project, so they wait for it.
_DESK_FIELDS = frozenset({"jira_base_url", "project_key"})
_ERROR_DETAIL_CHARS = 300
_SIGN_IN_TIMEOUT_TEXT = sign_in_timeout_text("Jira Service Management")


def _gateway(context: CapabilityCheckContext) -> JiraServiceManagementSourceOperations:
    gateway: SourceOperations | None = context.source_operations
    if not isinstance(gateway, JiraServiceManagementSourceOperations):
        raise TypeError(
            "Bug: The runner constructs the registered gateway for migrated sources."
        )
    return gateway


def _project_key(config: JiraServiceManagementConnectorConfig) -> str:
    return (config.project_key or "").strip()


def _scope_jql(config: JiraServiceManagementConnectorConfig) -> str:
    """The query of a full indexing run: the configured scope, from the epoch
    to now."""
    return build_jql_query(
        project_key=_project_key(config) or None,
        jql_query=(config.jql_query or "").strip() or None,
        start=0,
        end=time.time(),
    )


def _detail(error: Exception) -> str:
    body: str | None = getattr(error, "body", None)
    return (body or str(error))[:_ERROR_DETAIL_CHARS]


class _JsmCheck(CapabilityCheck[JiraServiceManagementConnectorConfig]):
    config_class = JiraServiceManagementConnectorConfig

    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        required: bool = True,
        validates_binding: bool = False,
        fails_when_unreachable: bool = False,
        row_id: str | None = None,
        step: CheckStep | None = None,
        timeout_text: CheckRowText | None = None,
        requires_fields: frozenset[str] = _SITE_FIELDS,
        depends_on: tuple[str, ...] = (),
    ) -> None:
        super().__init__(
            capability=CredentialCapability.INDEXING,
            check_id=check_id,
            display_name=display_name,
            row_id=row_id,
            required=required,
            requires_connector_instance=False,
            requires_fields=requires_fields,
            depends_on=depends_on,
            remediation=remediation,
            docs_link=_DOCS_LINK,
            validates_binding=validates_binding,
            fails_when_unreachable=fails_when_unreachable,
            step=step,
            timeout_text=timeout_text
            or CheckRowText(
                summary="Jira did not answer in time",
                description="The site took too long to answer. Check the site URL and try again.",
            ),
        )


class _SignInCheck(_JsmCheck):
    """Signs in the way the connector does. The JSM source uses the Jira
    credential, so this calls ``myself`` through the JSM gateway."""

    def __init__(self) -> None:
        super().__init__(
            check_id="jsm_auth",
            display_name="Sign in to Jira Service Management",
            remediation=(
                "Enter the site URL and an API token with its owner's email "
                "(Jira Cloud), or a personal access token (Jira Data Center)."
            ),
            validates_binding=True,
            fails_when_unreachable=True,
            timeout_text=_SIGN_IN_TIMEOUT_TEXT,
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        try:
            me: dict[str, Any] = _gateway(context).get_myself(fast=True)
        except JsmApiError as e:
            if e.status_code is None:
                raise TimedOutValidationError(
                    "Jira did not answer the sign-in request in time.",
                    summary="Jira did not answer in time",
                    description="The site took too long to answer. Check the site URL.",
                ) from e
            if e.status_code in (401, 403):
                raise CredentialExpiredError(
                    "Jira rejected the credential. The token is wrong, expired or "
                    "revoked, or the email does not match the token's account.",
                    summary="Jira rejected the token",
                    description=(
                        "Jira did not accept the token.\n"
                        "Create a new token and enter it with its owner's email "
                        "for Jira Cloud."
                    ),
                ) from e
            raise UnexpectedValidationError(
                f"Jira answered the sign-in with an unexpected error: {_detail(e)}",
                summary="Unexpected answer from Jira",
                description="The site answered, but not as Jira should.",
            ) from e
        display_name: Any = me.get("displayName") or me.get("emailAddress")
        return CheckOutput(
            summary=f"Signed in as {display_name}" if display_name else "Signed in"
        )


class _ServiceDeskProjectCheck(_JsmCheck):
    """The configured project exists and this credential can read it.

    Deliberately uses the plain Jira project read, **not** servicedeskapi: the
    connector supports portal-only accounts, which have no agent licence and
    are refused by servicedeskapi. A required check must not block them.
    """

    def __init__(self) -> None:
        super().__init__(
            check_id="jsm_service_desk",
            display_name="Read the project",
            requires_fields=_DESK_FIELDS,
            depends_on=("jsm_auth",),
            remediation=(
                "Enter the key of a Jira Service Management project. To read it, "
                "give the token's account the Service Desk agent role, or at "
                "least browse access to the project."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraServiceManagementConnectorConfig = self.config(context)
        project_key: str = _project_key(config)
        try:
            project: dict[str, Any] = _gateway(context).get_project(
                project_key=project_key, fast=True
            )
        except JsmApiError as e:
            if e.status_code == 404:
                raise ConnectorValidationError(
                    f"Jira has no project {project_key}, or the credential cannot "
                    "see it. Enter a Jira Service Management project key.",
                    summary="Project not found",
                    description=(
                        f"Jira returned no project {project_key}.\n"
                        "Check the project key of the service desk."
                    ),
                ) from e
            if e.status_code in (401, 403):
                raise InsufficientPermissionsError(
                    "The credential cannot read the service desk. A Service Desk "
                    "agent role on the project is needed for the servicedeskapi.",
                    summary="Account cannot read the service desk",
                    description=(
                        "Jira refused the service desk call. (HTTP "
                        f"{e.status_code})\nGive the token's account the Service "
                        "Desk agent role on this project."
                    ),
                ) from e
            if e.status_code is None:
                raise TimedOutValidationError(
                    "Jira did not answer the service desk request in time.",
                    summary="Jira did not answer in time",
                    description="The site took too long to answer.",
                ) from e
            raise UnexpectedValidationError(
                f"Jira answered the service desk call unexpectedly: {_detail(e)}",
                summary="Unexpected answer from Jira",
                description="The site answered, but not as Jira should.",
            ) from e
        name: Any = project.get("name")
        return CheckOutput(
            summary=f"Read the project {name}" if name else "Read the project"
        )


class _RequestReadCheck(_JsmCheck):
    """Reads the first in-scope request, through the same search the indexing
    run uses."""

    def __init__(self) -> None:
        super().__init__(
            check_id="jsm_request_read",
            display_name="Sample requests",
            requires_fields=_DESK_FIELDS,
            depends_on=("jsm_auth", "jsm_service_desk"),
            remediation=(
                "Give the token's account Browse Projects on the service desk, "
                "and access to the request security levels."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraServiceManagementConnectorConfig = self.config(context)
        jql: str = _scope_jql(config)
        gateway = _gateway(context)
        try:
            page = gateway.search_issue_ids(jql=jql, max_results=1, fast=True)
        except JsmApiError as e:
            if e.status_code is None:
                raise TimedOutValidationError(
                    "Jira did not answer the request search in time.",
                    summary="Jira did not answer in time",
                    description="The site took too long to answer. Re-run the check.",
                ) from e
            if e.status_code == 400:
                raise ConnectorValidationError(
                    f"Jira rejected the request query: {_detail(e)}",
                    summary="Jira rejected the request query",
                    description="Check the Project Key and the JQL Query.",
                ) from e
            if e.status_code in (401, 403):
                raise InsufficientPermissionsError(
                    "The credential cannot search the requests of this service desk.",
                    summary="Account cannot search requests",
                    description=(
                        "Jira refused the request search.\nGive the token's account "
                        "Browse Projects on the service desk."
                    ),
                ) from e
            raise UnexpectedValidationError(
                f"Jira answered the request search unexpectedly: {_detail(e)}",
                summary="Unexpected answer from Jira",
                description="The site answered, but not as Jira should.",
            ) from e
        if not page.issue_ids:
            raise ConnectorValidationError(
                "The selected service desk has no request this credential can read, "
                "so indexing would add no documents.",
                summary="No requests in the selected scope",
                description=(
                    "The service desk has no readable request.\n"
                    "Check the Project Key, or give the account access to the "
                    "request security levels."
                ),
            )
        # Read the request the search found, through the same bulk fetch the
        # indexing run uses, so a passing check has proved the full read path.
        try:
            issues = gateway.bulk_fetch_issues(issue_ids=[page.issue_ids[0]], fast=True)
        except JsmApiError as e:
            if e.status_code is None:
                raise TimedOutValidationError(
                    "Jira did not answer the request read in time.",
                    summary="Jira did not answer in time",
                    description="The site took too long to answer. Re-run the check.",
                ) from e
            if e.status_code in (401, 403):
                raise InsufficientPermissionsError(
                    "The credential can search the service desk but cannot read a "
                    "request it found.",
                    summary="Account cannot read a request",
                    description=(
                        f"Jira refused the request read. (HTTP {e.status_code})\n"
                        "Give the token's account access to the request security "
                        "levels."
                    ),
                ) from e
            raise UnexpectedValidationError(
                f"Jira answered the request read unexpectedly: {_detail(e)}",
                summary="Unexpected answer from Jira",
                description="The site answered, but not as Jira should.",
            ) from e
        fields: Any = issues[0].get("fields") if issues else None
        if not isinstance(fields, dict) or "summary" not in fields:
            raise ConnectorValidationError(
                "Jira listed a request but did not return its fields, so requests "
                "would index empty.",
                summary="Request came back without content",
                description="Give the account access to the request security levels.",
            )
        return CheckOutput(summary="Read a request")


class _ServiceDeskMetadataCheck(_JsmCheck):
    """The credential can also read the service desk metadata that the
    connector adds to each request. Advisory: without it, requests still index
    through the Jira API, so this never holds Create."""

    def __init__(self) -> None:
        super().__init__(
            check_id="jsm_metadata",
            display_name="Read service desk metadata",
            requires_fields=_DESK_FIELDS,
            depends_on=("jsm_auth", "jsm_service_desk"),
            remediation=(
                "Give the token's account the Service Desk agent role on this "
                "project to add the portal name and the request type to each "
                "request. Requests index without them."
            ),
            required=False,
        )

    def applies(
        self, form_state: FormState[JiraServiceManagementConnectorConfig]
    ) -> bool:
        return form_state.config.include_service_desk_metadata

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraServiceManagementConnectorConfig = self.config(context)
        try:
            desk: dict[str, Any] = _gateway(context).get_service_desk(
                project_key=_project_key(config), fast=True
            )
        except JsmApiError as e:
            return CheckOutput(
                summary="Service desk metadata is unavailable",
                advisories=[
                    CheckAdvisory(
                        message=(
                            "Requests index without the service desk name and the "
                            f"request type: {_detail(e)}"
                        )
                    )
                ],
            )
        if not desk.get("id"):
            return CheckOutput(
                summary="Service desk metadata is unavailable",
                advisories=[
                    CheckAdvisory(
                        message=(
                            "Requests index without the service desk name and the "
                            "request type: Jira returned no service desk."
                        )
                    )
                ],
            )
        return CheckOutput(summary="Read the service desk metadata")


def build_jsm_indexing_checks() -> list[CapabilityCheck]:
    return [
        _SignInCheck(),
        _ServiceDeskProjectCheck(),
        _RequestReadCheck(),
        _ServiceDeskMetadataCheck(),
    ]
