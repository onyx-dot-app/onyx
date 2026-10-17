"""Capability checks for the Jira connector.

The indexing checks register in ``registry.py``; the permission-sync and
group-sync checks register in the EE registry
(``ee/onyx/connectors/capability_checks.py``). Each check makes small probes
(one issue, one project) with the gateway operations that its sync calls,
with ``fast=True``: a request that Jira does not answer in time raises
``JiraTimeoutError``, and the check ends instead of waiting for its hang guard.

The gateway reaches the site through the bound config fields
(``jira_base_url``, ``scoped_token``), so every check requires
``jira_base_url``. The credential picks the API family: an account email means
Jira Cloud (REST v3, enhanced search and bulk fetch), a token alone means Jira
Data Center (REST v2 search). The checks call the operations of that family,
as the connector does.

The indexing scope follows the connector's precedence: JQL query, then project,
then everything. A blank mode field means "not this mode", so the mode checks
use ``applies`` instead of ``requires_fields``.
"""

import time
from typing import Any, NoReturn
from urllib.parse import urlparse

import requests
from pydantic import BaseModel

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CheckAdvisory,
    CheckOutput,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InconclusiveValidationError,
    InsufficientPermissionsError,
    NothingToCheckError,
    RateLimitedValidationError,
    UnexpectedValidationError,
    UnreachableValidationError,
)
from onyx.connectors.jira.config import JiraConnectorConfig
from onyx.connectors.jira.connector import build_jql_query, jira_error_messages
from onyx.connectors.jira.models import JiraGroupMemberSample, JiraIssueIdPage
from onyx.connectors.jira.source_operations import (
    JiraApiError,
    JiraCloudIdError,
    JiraGroupPage,
    JiraSourceOperations,
    JiraTimeoutError,
    is_cloud_gateway,
)
from onyx.connectors.jira.utils import (
    ATLASSIAN_GROUP_ROLE_ACTOR_TYPE,
    ATLASSIAN_USER_ROLE_ACTOR_TYPE,
    BROWSE_PROJECTS_PERMISSION,
    HOLDER_TYPE_ANYONE,
    HOLDER_TYPE_APPLICATION_ROLE,
    HOLDER_TYPE_GROUP,
    HOLDER_TYPE_PROJECT_ROLE,
    HOLDER_TYPE_USER,
    SUPPORTED_STATIC_HOLDER_TYPES,
    get_issue_field,
)
from onyx.connectors.source_operations import SourceOperations

_DOCS_LINK = "https://docs.onyx.app/admins/connectors/official/jira"
_SITE_FIELDS = frozenset({"jira_base_url"})
_ERROR_DETAIL_CHARS = 300
_CLOUD_HOST_SUFFIX = ".atlassian.net"
# Atlassian's text when a scoped token lacks the scope of an API.
_SCOPE_MISMATCH_TEXT = "scope does not match"
_TENANT_INFO_PATH = "/_edge/tenant_info"
_RATE_LIMITED_STATUS = 429


_INDEXING_SCOPE = "read:jira-work"
_BROWSE_NEED = "Browse Projects on the projects to index"
# Statuses at which a Cloud site turns away a credential without an email.
_SIGN_IN_REFUSED_STATUSES = frozenset({401, 403, 404})


def _gateway(context: CapabilityCheckContext) -> JiraSourceOperations:
    gateway: SourceOperations | None = context.source_operations
    if not isinstance(gateway, JiraSourceOperations):
        raise TypeError(
            "Bug: The runner constructs the registered gateway for migrated sources."
        )
    return gateway


class _RowText(BaseModel):
    """The row text of one outcome of a probe."""

    summary: str
    description: str


def _project_key(config: JiraConnectorConfig) -> str:
    return (config.project_key or "").strip()


def _jql(config: JiraConnectorConfig) -> str:
    return (config.jql_query or "").strip()


def _scope_jql(config: JiraConnectorConfig) -> str:
    """The query of a full indexing run: the configured scope, from the epoch
    to now."""
    return build_jql_query(
        project_key=_project_key(config) or None,
        jql_query=_jql(config) or None,
        start=0,
        end=time.time(),
    )


def _access_hint(
    config: JiraConnectorConfig, *, scope: str, user_permission: str
) -> str:
    """What to grant, in the terms of the token type."""
    if config.scoped_token:
        return (
            f"The scoped API token needs the `{scope}` scope. Create a token with "
            "the scopes in the Onyx Jira docs."
        )
    return f"The token acts as its Jira account. Give that account {user_permission}."


def _need(config: JiraConnectorConfig, *, scope: str, user_permission: str) -> str:
    """The row description's line of what a denied probe needs, for the token
    type. ``_access_hint`` is the full text for the message."""
    if config.scoped_token:
        return f"Required scope: {scope}"
    return f"Give the token's account {user_permission}."


def _error_detail(error: JiraApiError) -> str:
    messages: str | None = jira_error_messages(error.body)
    return (messages or error.body or str(error))[:_ERROR_DETAIL_CHARS]


def _raise_for_timeout(error: JiraTimeoutError) -> NoReturn:
    """INCOMPLETE: a slow Jira says nothing about the credential."""
    raise UnreachableValidationError(
        f"{error} Run the checks again, or check the status of Jira.",
        summary="Timed out",
        description=(
            "The check stopped because Jira did not answer in time.\nRe-run the checks."
        ),
    ) from error


def _raise_for_api_error(
    error: JiraApiError,
    *,
    denied: str,
    denied_row: _RowText | None = None,
    scope_row: _RowText | None = None,
    not_found: str | None = None,
    not_found_row: _RowText | None = None,
    bad_request: str | None = None,
    bad_request_row: _RowText | None = None,
) -> NoReturn:
    """Maps a Jira API error onto the validation-exception family. ``denied``
    explains a 403 (or a scoped token without the scope) for this probe; each
    ``*_row`` is the row text of that outcome."""
    if isinstance(error, JiraTimeoutError):
        _raise_for_timeout(error)
    status: int | None = error.status_code
    detail: str = _error_detail(error)
    # Callers' texts can end in a full stop; the mapper adds its own.
    denied = denied.rstrip(".")
    if status == 401 and _SCOPE_MISMATCH_TEXT in (error.body or ""):
        scope_row = scope_row or _RowText(
            summary="Token lacks a scope for this API",
            description=(
                "The token signs in but lacks the scope this call needs. "
                "(HTTP 401)\nCreate the token with the scopes in the docs."
            ),
        )
        raise InsufficientPermissionsError(
            f"{denied}. The scoped API token does not have the scope of this API "
            "(HTTP 401: scope does not match).",
            summary=scope_row.summary,
            description=scope_row.description,
        ) from error
    if status == 401:
        raise CredentialExpiredError(
            "Jira rejected the credential (HTTP 401). The token is wrong, expired, "
            "or revoked, or the email does not match the token's account.",
            summary="Jira rejected the token",
            description=(
                "Jira did not accept the token. (HTTP 401)\n"
                "Create a new token. For Jira Cloud, enter it with its owner's "
                "email."
            ),
        ) from error
    if status == 403:
        raise InsufficientPermissionsError(
            f"{denied} (HTTP 403).",
            summary=denied_row.summary if denied_row else None,
            description=denied_row.description if denied_row else None,
        ) from error
    if status == 404 and not_found is not None:
        raise ConnectorValidationError(
            f"{not_found.rstrip('.')} (HTTP 404).",
            summary=not_found_row.summary if not_found_row else None,
            description=not_found_row.description if not_found_row else None,
        ) from error
    if status == 400 and bad_request is not None:
        raise ConnectorValidationError(
            f"{bad_request} (HTTP 400): {detail}",
            summary=bad_request_row.summary if bad_request_row else None,
            description=bad_request_row.description if bad_request_row else None,
        ) from error
    if status == _RATE_LIMITED_STATUS:
        raise RateLimitedValidationError(
            "Jira rate limited the check. Run the checks again in a minute.",
            summary="Rate limited by Jira",
            description=(
                "Jira limited the number of requests. (HTTP 429)\n"
                "Wait a minute, then re-run."
            ),
        ) from error
    raise UnexpectedValidationError(
        f"Unexpected Jira response (HTTP {status}): {detail}",
        summary="Unexpected response from Jira",
        description=(
            "Jira answered with an error this check does not expect. "
            f"(HTTP {status})\nRe-run the checks."
        ),
    ) from error


_SIGN_IN_CHECK_IDS = ("jira_auth", "jira_scoped_token_auth")
_SCOPE_CHECK_IDS = (
    "jira_projects_visible",
    "jira_configured_project",
    "jira_jql_query",
)
# check_id to the checks it runs after, in run order. A listed check that does
# not apply (the other token type, a scope not in use) is left out.
_DEPENDS_ON: dict[str, tuple[str, ...]] = {
    "jira_projects_visible": _SIGN_IN_CHECK_IDS,
    "jira_configured_project": ("jira_projects_visible",),
    "jira_jql_query": ("jira_projects_visible",),
    "jira_issue_read": _SCOPE_CHECK_IDS,
    "jira_permission_scheme_read": _SCOPE_CHECK_IDS,
    "jira_project_access_mappable": ("jira_permission_scheme_read",),
    "jira_project_roles_read": ("jira_permission_scheme_read",),
    "jira_permission_user_emails": ("jira_project_roles_read",),
    "jira_group_listing": _SIGN_IN_CHECK_IDS,
    "jira_group_listing_complete": ("jira_group_listing",),
    "jira_group_membership": ("jira_group_listing",),
    "jira_group_member_emails": ("jira_group_membership",),
}


class _JiraCheck(CapabilityCheck[JiraConnectorConfig]):
    config_class = JiraConnectorConfig

    def __init__(
        self,
        *,
        check_id: str,
        display_name: str,
        remediation: str,
        required: bool = True,
        capability: CredentialCapability = CredentialCapability.INDEXING,
        validates_binding: bool = False,
        fails_when_unreachable: bool = False,
        row_id: str | None = None,
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            row_id=row_id,
            required=required,
            requires_connector_instance=False,
            requires_fields=_SITE_FIELDS,
            remediation=remediation,
            docs_link=_DOCS_LINK,
            validates_binding=validates_binding,
            fails_when_unreachable=fails_when_unreachable,
            depends_on=_DEPENDS_ON.get(check_id, ()),
        )


def _is_cloud_site(config: JiraConnectorConfig) -> bool:
    host: str = urlparse(config.jira_base_url).hostname or ""
    return host.endswith(_CLOUD_HOST_SUFFIX)


class _SiteAuthCheck(_JiraCheck):
    """Signs in the way the connector does.

    One check per token type: a scoped API token resolves the cloud id
    (``tenant_info``) and calls ``api.atlassian.com``; other tokens call the
    site URL. A scoped token signs in with a project listing, which needs only
    the indexing scope; ``myself`` needs a user scope that indexing does not.
    """

    def __init__(self, *, scoped: bool) -> None:
        self._scoped = scoped
        if scoped:
            super().__init__(
                check_id="jira_scoped_token_auth",
                row_id="jira_auth",
                validates_binding=True,
                fails_when_unreachable=True,
                display_name="Sign in to Jira",
                remediation=(
                    "Scoped API tokens work only with Jira Cloud. Enter the email "
                    "of the token's Atlassian account with the token, check the "
                    "site URL, and create a new token if it expired."
                ),
            )
        else:
            super().__init__(
                check_id="jira_auth",
                validates_binding=True,
                fails_when_unreachable=True,
                display_name="Sign in to Jira",
                remediation=(
                    "Jira Cloud: enter the email of the token's Atlassian account "
                    "and an API token. Jira Data Center: leave the email empty and "
                    "use a personal access token. Check the site URL, and create a "
                    "new token if it expired."
                ),
            )

    def applies(self, form_state: FormState[JiraConnectorConfig]) -> bool:
        return form_state.config.scoped_token == self._scoped

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        gateway: JiraSourceOperations = _gateway(context)
        try:
            if self._scoped:
                gateway.list_projects(fast=True)
                return CheckOutput(summary="Signed in")
            name: Any = gateway.get_myself(fast=True).get("displayName")
            return CheckOutput(summary=f"Signed in as {name}" if name else "Signed in")
        except requests.HTTPError as e:
            # Only the scoped token's tenant_info call raises a raw HTTPError.
            # tenant_info needs no auth: a 4xx means the URL is not a Cloud
            # site. 429 and 5xx fall through as INCOMPLETE.
            response: requests.Response | None = e.response
            config: JiraConnectorConfig = self.config(context)
            if (
                response is not None
                and _TENANT_INFO_PATH in (response.url or "")
                and 400 <= response.status_code < 500
                and response.status_code != _RATE_LIMITED_STATUS
            ):
                raise ConnectorValidationError(
                    "Onyx cannot get the Atlassian cloud id of "
                    f"{config.jira_base_url} (`{_TENANT_INFO_PATH}`). Scoped API "
                    "tokens work only with Jira Cloud; check the site URL.",
                    summary="Site is not a Jira Cloud site",
                    description=(
                        "Scoped tokens work only with Jira Cloud, and this URL "
                        "returned no Atlassian cloud ID."
                    ),
                ) from e
            raise UnexpectedValidationError(
                f"Unexpected response from {config.jira_base_url}: {e}",
                summary="Site lookup failed",
                description=(
                    "The Atlassian site lookup failed with a server error.\n"
                    "Re-run the checks."
                ),
            ) from e
        except (JiraTimeoutError, requests.Timeout) as e:
            # A raw Timeout comes from the scoped token's tenant_info call.
            raise UnreachableValidationError(
                f"{self.config(context).jira_base_url} did not answer the sign-in "
                f"in time: {e}",
                summary="Sign-in timed out",
                description=(
                    "Jira did not answer the sign-in in time.\n"
                    "Re-run, or check that Jira is reachable from Onyx."
                ),
            ) from e
        except requests.ConnectionError as e:
            raise UnreachableValidationError(
                f"Onyx cannot connect to {self.config(context).jira_base_url}. "
                "Check the site URL.",
                summary="Cannot reach Jira",
                description="The connection to Jira Base URL failed.\nCheck Jira Base URL.",
            ) from e
        except JiraApiError as e:
            self._raise_for_sign_in_error(context, gateway, e)
        except JiraCloudIdError as e:
            raise ConnectorValidationError(
                "Onyx cannot get the Atlassian cloud id of "
                f"{self.config(context).jira_base_url} (`{_TENANT_INFO_PATH}`). "
                "Scoped API tokens work only with Jira Cloud; check the site URL.",
                summary="Site returned no cloud ID",
                description=(
                    "The site answered without an Atlassian cloud ID, for example "
                    "with a login page."
                ),
            ) from e
        except (ValueError, KeyError) as e:
            # The client read an answer that is not Jira's (e.g. a login page).
            raise ConnectorValidationError(
                f"{self.config(context).jira_base_url} did not answer like Jira: {e}",
                summary="Site did not answer like Jira",
                description=(
                    "The site answered with data that is not a Jira API response, "
                    "for example a login page."
                ),
            ) from e

    def _raise_for_sign_in_error(
        self,
        context: CapabilityCheckContext,
        gateway: JiraSourceOperations,
        error: JiraApiError,
    ) -> NoReturn:
        config: JiraConnectorConfig = self.config(context)
        is_cloud_credential: bool = is_cloud_gateway(gateway)
        # Only a refusal means the missing email: a rate limit or a server
        # error says nothing about it.
        if (
            not is_cloud_credential
            and (self._scoped or _is_cloud_site(config))
            and error.status_code in _SIGN_IN_REFUSED_STATUSES
        ):
            raise ConnectorValidationError(
                "Jira Cloud needs the email of the token's Atlassian account with "
                "the API token, but this credential has no email. Edit the "
                "credential and add the email.",
                summary=(
                    "Account has no email for the token"
                    if self._scoped
                    else "Account has no email for Jira Cloud"
                ),
                description=(
                    "A scoped token signs in with the email of its Atlassian "
                    "account, and this account has none."
                    if self._scoped
                    else "Jira Cloud signs in with an email and a token, but this "
                    "account has only a token."
                ),
            ) from error
        if is_cloud_credential and error.status_code == 404:
            raise ConnectorValidationError(
                f"{config.jira_base_url} has no Jira Cloud REST API (v3). For Jira "
                "Data Center, leave the email empty and use a personal access "
                "token. For Jira Cloud, check the site URL "
                "(https://your-domain.atlassian.net).",
                summary="No Jira Cloud API at this URL",
                description=(
                    "The site at Jira Base URL does not answer the Jira Cloud API. "
                    "(HTTP 404)"
                ),
            ) from error
        _raise_for_api_error(
            error,
            denied=(
                "The credential signs in, but Jira does not let its account use "
                "Jira on this site. Give the account Jira product access"
            ),
            denied_row=_RowText(
                summary="Account has no Jira access on this site",
                description=(
                    "The token signs in, but its account cannot use Jira on this "
                    "site. (HTTP 403)"
                ),
            ),
            scope_row=(
                _RowText(
                    summary="Token lacks the read:jira-work scope",
                    description=(
                        "The token signs in but lacks the scope this call needs. "
                        "(HTTP 401)\nCreate a token with the read:jira-work scope "
                        "(see the docs)."
                    ),
                )
                if self._scoped
                else None
            ),
            not_found=(
                f"Jira has no REST API at {config.jira_base_url}. Check the site URL"
            ),
            not_found_row=_RowText(
                summary="No Jira API at this URL",
                description=(
                    "Jira Base URL does not point to a Jira REST API. (HTTP 404)\n"
                    "Check Jira Base URL, and include the context path if Jira "
                    "runs under one (e.g. https://example.com/jira)."
                ),
            ),
        )


class _ProjectsVisibleCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="jira_projects_visible",
            validates_binding=True,
            display_name="List projects",
            remediation=(
                "Give the token's account the Browse Projects permission on the "
                "projects to index. Scoped API token: the `read:jira-work` scope."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        need: str = _need(config, scope=_INDEXING_SCOPE, user_permission=_BROWSE_NEED)
        try:
            projects: list[dict[str, Any]] = _gateway(context).list_projects(fast=True)
        except JiraApiError as e:
            _raise_for_api_error(
                e,
                denied="The credential cannot list Jira projects. "
                + _access_hint(
                    config,
                    scope=_INDEXING_SCOPE,
                    user_permission="Browse Projects",
                ),
                denied_row=_RowText(
                    summary="Account cannot list projects",
                    description=f"Jira refused the project list. (HTTP 403)\n{need}",
                ),
            )
        if not projects:
            raise InsufficientPermissionsError(
                "No Jira project is visible to this credential. "
                + _access_hint(
                    config,
                    scope=_INDEXING_SCOPE,
                    user_permission=_BROWSE_NEED,
                ),
                summary="No projects visible",
                description=f"The account can see no Jira project.\n{need}",
            )
        return CheckOutput(summary=f"{len(projects)} projects visible")


def _matching_project_keys(
    projects: list[dict[str, Any]], project_key: str
) -> list[str]:
    """Keys of visible projects whose key or name matches ``project_key``,
    ignoring case."""
    wanted: str = project_key.casefold()
    return sorted(
        str(project["key"])
        for project in projects
        if str(project.get("key", "")).casefold() == wanted
        or str(project.get("name", "")).casefold() == wanted
    )


class _ConfiguredProjectCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="jira_configured_project",
            display_name="Find selected project",
            remediation=(
                "Use the project key, not the project name (e.g. `PROJ`), and give "
                "the token's account Browse Projects on the project."
            ),
        )

    def applies(self, form_state: FormState[JiraConnectorConfig]) -> bool:
        config: JiraConnectorConfig = form_state.config
        return bool(_project_key(config)) and not _jql(config)

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        project_key: str = _project_key(config)
        gateway: JiraSourceOperations = _gateway(context)
        try:
            project: dict[str, Any] = gateway.get_project(
                project_key=project_key, fast=True
            )
        except JiraApiError as e:
            if e.status_code != 404:
                _raise_for_api_error(
                    e,
                    denied=f"The credential cannot read the project `{project_key}`",
                    denied_row=_RowText(
                        summary=f"Account cannot read {project_key}",
                        description=(
                            "Jira refused access to the selected project. "
                            "(HTTP 403)\nGive the token's account Browse Projects "
                            "on the project."
                        ),
                    ),
                )
            self._raise_not_found(gateway, project_key, e)
        return CheckOutput(
            summary=f"Found project {project.get('name') or project_key}"
        )

    def _raise_not_found(
        self, gateway: JiraSourceOperations, project_key: str, error: JiraApiError
    ) -> NoReturn:
        try:
            matches: list[str] = _matching_project_keys(
                gateway.list_projects(fast=True), project_key
            )
        except JiraApiError:
            matches = []
        hint: str = (
            f" Did you mean the key `{matches[0]}`?"
            if matches and matches[0] != project_key
            else ""
        )
        raise ConnectorValidationError(
            f"No project with the key `{project_key}` is visible to this "
            "credential. Check the key, or give the token's account Browse "
            f"Projects on the project.{hint}",
            summary=f"Project {project_key} not found",
            description=(
                "No project with this key is visible to the account. (HTTP 404)\n"
                + (
                    f"Did you mean the key {matches[0]}?"
                    if hint
                    else "Enter the project key, not the project name, in Project "
                    "Key (e.g. PROJ)."
                )
            ),
        ) from error


def _search_one_issue(gateway: JiraSourceOperations, jql: str) -> dict[str, Any] | None:
    """The first issue the query matches, with all fields, read through the
    API family the connector uses. Raises ``JiraApiError``."""
    if is_cloud_gateway(gateway):
        page: JiraIssueIdPage = gateway.search_issue_ids(
            jql=jql, max_results=1, fast=True
        )
        if not page.issue_ids:
            return None
        issues: list[dict[str, Any]] = gateway.bulk_fetch_issues(
            issue_ids=page.issue_ids[:1], fast=True
        )
        return issues[0] if issues else {}
    issues: list[dict[str, Any]] = gateway.search_issues(
        jql=jql, start_at=0, max_results=1, fast=True
    )
    return issues[0] if issues else None


class _JqlQueryCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="jira_jql_query",
            display_name="Run JQL query",
            remediation=(
                "Test the query in Jira's issue search. Quote values that are "
                'reserved JQL words (e.g. project = "AS"). Use no ORDER BY.'
            ),
        )

    def applies(self, form_state: FormState[JiraConnectorConfig]) -> bool:
        return bool(_jql(form_state.config))

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        try:
            issue: dict[str, Any] | None = _search_one_issue(
                _gateway(context), _scope_jql(config)
            )
        except JiraApiError as e:
            _raise_for_api_error(
                e,
                denied="The credential cannot search Jira issues",
                denied_row=_RowText(
                    summary="Account cannot search issues",
                    description=(
                        "Jira refused the issue search. (HTTP 403)\n"
                        f"Give the token's account {_BROWSE_NEED}."
                    ),
                ),
                bad_request="Jira rejected the JQL query",
                bad_request_row=_RowText(
                    summary="Jira rejected the query",
                    description=(
                        f"Jira cannot run the JQL query: {_error_detail(e)} "
                        "(HTTP 400)\nTest the query in Jira's issue search."
                    ),
                ),
            )
        if issue is None:
            # An empty scope fails the first check that reads it: the
            # connector would index nothing.
            raise ConnectorValidationError(
                "The JQL query matched no issue that this credential can read. "
                "Jira accepted the query. If issues exist, check the query.",
                summary="Query matches no issues",
                description=(
                    "Jira accepts the query, but it matches no issue the account "
                    "can read."
                ),
            )
        return CheckOutput(summary="Query matches issues")


class _IssueReadCheck(_JiraCheck):
    """Reads the first in-scope issue with all its fields, through the same
    search the indexing run uses."""

    def __init__(self) -> None:
        super().__init__(
            check_id="jira_issue_read",
            display_name="Sample issues",
            remediation=(
                "Give the token's account Browse Projects on the projects to "
                "index, and access to their issue security levels. Scoped API "
                "token: the `read:jira-work` scope."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        hint: str = _access_hint(
            config, scope=_INDEXING_SCOPE, user_permission=_BROWSE_NEED
        )
        need: str = _need(config, scope=_INDEXING_SCOPE, user_permission=_BROWSE_NEED)
        try:
            issue: dict[str, Any] | None = _search_one_issue(
                _gateway(context), _scope_jql(config)
            )
        except JiraApiError as e:
            if e.status_code == 400:
                # jira_jql_query / jira_configured_project report a bad scope.
                raise UnexpectedValidationError(
                    "Jira rejected the indexing scope query, so this check cannot "
                    f"run. Fix the scope settings first: {_error_detail(e)}",
                    summary="Jira rejected the issue query",
                    description=(
                        "Jira did not accept the indexing scope query. (HTTP 400)\n"
                        "Check Project Key or JQL Query."
                    ),
                ) from e
            _raise_for_api_error(
                e,
                denied=f"The credential cannot search Jira issues. {hint}",
                denied_row=_RowText(
                    summary="Account cannot search issues",
                    description=f"Jira refused the issue search. (HTTP 403)\n{need}",
                ),
            )
        if issue is None:
            # An empty scope fails the first check that reads it: the
            # connector would index nothing.
            if not _project_key(config) and not _jql(config):
                raise ConnectorValidationError(
                    "Jira projects are visible, but this credential can read no "
                    f"issue in them, so indexing would add no documents. {hint}",
                    summary="No readable issues found",
                    description=(
                        "The account can read no issue in any project.\n"
                        f"{need} Give it access to the issue security levels."
                    ),
                )
            raise ConnectorValidationError(
                "The indexing scope has no issue that this credential can read, "
                f"so indexing would add no documents. If the scope has issues: {hint}",
                summary="No issues in the selected scope",
                description=(
                    "The selected scope has no issue the account can read.\n"
                    f"If the scope should have issues: {need}"
                ),
            )
        fields: Any = issue.get("fields")
        if not isinstance(fields, dict) or "summary" not in fields:
            raise InsufficientPermissionsError(
                "Jira found an issue but did not return its fields, so issues "
                f"would index without content. {hint}",
                summary="Issue came back without its content",
                description=(
                    "Issues would index empty.\n"
                    "Give the token's account access to the issue security levels."
                ),
            )
        project: Any = fields.get("project")
        project_key: Any = project.get("key") if isinstance(project, dict) else None
        return CheckOutput(
            summary=f"Read an issue from {project_key}"
            if project_key
            else "Read an issue"
        )


def build_jira_indexing_checks() -> list[CapabilityCheck]:
    return [
        _SiteAuthCheck(scoped=False),
        _SiteAuthCheck(scoped=True),
        _ProjectsVisibleCheck(),
        _ConfiguredProjectCheck(),
        _JqlQueryCheck(),
        _IssueReadCheck(),
    ]


# Permission sync. The EE registry registers these checks. Doc sync reads the
# Browse Projects grants of each project's permission scheme, the actors of its
# project roles, and the email of each user. Group sync lists the groups and
# the members of each group. Both map Jira users to Onyx users by email.

_PERMISSION_SYNC_SCOPES = "`read:jira-user` and `manage:jira-configuration`"
_PUBLIC_HOLDER_TYPES = frozenset({HOLDER_TYPE_ANYONE, HOLDER_TYPE_APPLICATION_ROLE})
_SAMPLE_USERS = 5
_SAMPLE_ROLES = 3
_SAMPLE_GROUPS = 3
_GROUP_MEMBER_PAGE_SIZE = 50
_ATLASSIAN_ACCOUNT_TYPE = "atlassian"

_ADMIN_HINT = (
    "Give the token's account Administer Jira, or Administer Projects on every "
    "project to sync (the Administrator role in team-managed projects)."
)
_CLOUD_EMAIL_HINT = (
    "Atlassian returns a user's email only when the user's profile shows it "
    "(Profile and visibility > Contact), or when the organization makes emails "
    "visible to apps. Users without a visible email get no access in Onyx."
)
_DC_EMAIL_HINT = (
    "Jira Data Center returns emails only when 'User email visibility' "
    "(General configuration) is 'Public', or 'Only visible to logged-in users' "
    "with a token account that can see them."
)
_ADMIN_NEED = "Give the token's account Administer Projects on every synced project."
_GROUP_ACCESS_NEED = (
    "Give the token's account Administer Jira, or the Browse users and groups "
    "global permission."
)
_EMAIL_NEED = "Ask users to make their email visible to anyone."
_PERMISSION_SYNC_SCOPE_ROW = _RowText(
    summary="Token lacks a permission sync scope",
    description=(
        "The token signs in but lacks the scope this call needs. (HTTP 401)\n"
        "Add the read:jira-user and manage:jira-configuration scopes."
    ),
)
_USER_SCOPE_ROW = _RowText(
    summary="Token lacks the read:jira-user scope",
    description=(
        "The token signs in but lacks the scope this call needs. (HTTP 401)\n"
        "Add the read:jira-user and manage:jira-configuration scopes."
    ),
)
_GROUP_ACCESS_HINT = (
    "Give the token's account Administer Jira, or the global Browse users and "
    "groups permission. On Data Center the account must be in a Jira "
    "administrators group."
)


def _perm_sync_hint(config: JiraConnectorConfig, admin_hint: str) -> str:
    if config.scoped_token:
        return (
            f"The scoped API token needs the {_PERMISSION_SYNC_SCOPES} scopes, and "
            f"its account needs admin access. {admin_hint}"
        )
    return admin_hint


def _email_hint(gateway: JiraSourceOperations) -> str:
    return _CLOUD_EMAIL_HINT if is_cloud_gateway(gateway) else _DC_EMAIL_HINT


def _probe_project_key(
    context: CapabilityCheckContext, config: JiraConnectorConfig
) -> str:
    """The configured project in project mode, the project of the first
    matching issue in JQL mode, else the first visible project. Permission sync
    reads the scheme of every project with indexed issues, so a JQL query that
    matches nothing leaves nothing to check."""
    project_key: str = _project_key(config)
    if project_key and not _jql(config):
        return project_key
    if _jql(config):
        try:
            issue = _search_one_issue(_gateway(context), _scope_jql(config))
        except JiraTimeoutError as e:
            _raise_for_timeout(e)
        except JiraApiError as e:
            raise UnexpectedValidationError(
                "Onyx cannot run the JQL query, so it cannot pick a project to "
                "probe. jira_jql_query reports why.",
                summary="Cannot run the JQL query",
                description="Run JQL query reports why.",
            ) from e
        if issue is None:
            raise NothingToCheckError(
                "The JQL query matched no issue, so permission sync reads no "
                "project yet.",
                summary="No project to read",
                description="The JQL query matches no issue yet.",
            )
        project: Any = get_issue_field(issue, "project")
        if not isinstance(project, dict) or not project.get("key"):
            raise UnexpectedValidationError(
                "Jira returned the first issue of the JQL query without its "
                "project, so Onyx cannot pick a project to probe.",
                summary="Sample issue came back without a project",
                description=(
                    "Jira returned the query's first issue without its project.\n"
                    "Re-run the checks."
                ),
            )
        return str(project["key"])
    try:
        projects: list[dict[str, Any]] = _gateway(context).list_projects(fast=True)
    except JiraApiError as e:
        _raise_for_api_error(
            e,
            denied="The credential cannot list Jira projects",
            denied_row=_RowText(
                summary="Account cannot list projects",
                description="Jira refused the project list. (HTTP 403)",
            ),
        )
    if not projects:
        raise UnexpectedValidationError(
            "No Jira project is visible, so Onyx cannot read a permission scheme. "
            "jira_projects_visible reports why.",
            summary="No project to read",
            description="List projects reports why.",
        )
    return str(projects[0]["key"])


def _browse_holders(scheme: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        permission["holder"]
        for permission in scheme.get("permissions") or []
        if isinstance(permission, dict)
        and permission.get("permission") == BROWSE_PROJECTS_PERMISSION
        and isinstance(permission.get("holder"), dict)
    ]


def _role_id(holder: dict[str, Any]) -> str | None:
    role_id: Any = holder.get("value") or holder.get("parameter")
    return str(role_id) if role_id else None


def _read_permission_scheme(
    context: CapabilityCheckContext, config: JiraConnectorConfig, project_key: str
) -> dict[str, Any]:
    try:
        scheme: dict[str, Any] = _gateway(context).get_project_permission_scheme(
            project_key=project_key, fast=True
        )
    except JiraApiError as e:
        _raise_for_api_error(
            e,
            denied=(
                "The credential cannot read the permission scheme of the project "
                f"`{project_key}`. {_perm_sync_hint(config, _ADMIN_HINT)}"
            ),
            denied_row=_RowText(
                summary="Account cannot read permission schemes",
                description=(
                    f"Synced issues in {project_key} would get no access. "
                    f"(HTTP 403)\n{_ADMIN_NEED}"
                ),
            ),
            scope_row=_PERMISSION_SYNC_SCOPE_ROW,
            not_found=(
                f"Jira does not return the permission scheme of the project "
                f"`{project_key}` to this credential. "
                f"{_perm_sync_hint(config, _ADMIN_HINT)}"
            ),
            not_found_row=_RowText(
                summary=f"No permission scheme for {project_key}",
                description=(
                    f"Jira did not return the permission scheme of {project_key} "
                    "to this account. (HTTP 404)"
                ),
            ),
        )
    if not isinstance(scheme.get("permissions"), list):
        raise InsufficientPermissionsError(
            f"Jira returned the permission scheme of the project `{project_key}` "
            f"without its grants. {_perm_sync_hint(config, _ADMIN_HINT)}",
            summary="Scheme came back without grants",
            description=(
                f"Jira returned the permission scheme of {project_key} without its "
                f"grants.\n{_ADMIN_NEED}"
            ),
        )
    return scheme


def _read_scheme_for_dependent_check(
    context: CapabilityCheckContext, config: JiraConnectorConfig
) -> tuple[str, dict[str, Any]]:
    """The probe project and its scheme, for a check that needs the scheme
    first. A failed read is jira_permission_scheme_read's failure."""
    try:
        project_key: str = _probe_project_key(context, config)
        return project_key, _read_permission_scheme(context, config, project_key)
    except ConnectorValidationError as e:
        raise UnexpectedValidationError(
            "Onyx cannot read the permission scheme, so this check cannot run. "
            "jira_permission_scheme_read reports why.",
            summary="Cannot read the permission scheme",
            description="Read permission schemes reports why.",
        ) from e


class _PermissionSchemeReadCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="jira_permission_scheme_read",
            display_name="Read permission schemes",
            remediation=(
                f"{_ADMIN_HINT} Scoped API token: the {_PERMISSION_SYNC_SCOPES} scopes."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        project_key: str = _probe_project_key(context, config)
        scheme: dict[str, Any] = _read_permission_scheme(context, config, project_key)
        holders: list[dict[str, Any]] = _browse_holders(scheme)
        if not holders:
            raise InsufficientPermissionsError(
                f"The permission scheme of the project `{project_key}` grants "
                "Browse Projects to nobody that Jira shows to this credential. "
                f"{_perm_sync_hint(config, _ADMIN_HINT)}",
                summary="No visible Browse Projects grants",
                description=(
                    f"The scheme of {project_key} shows no Browse Projects grant "
                    f"to this account.\n{_ADMIN_NEED}"
                ),
            )
        return CheckOutput(summary=f"{len(holders)} Browse grants in {project_key}")


class _ProjectAccessMappableCheck(_JiraCheck):
    """Warns when Browse Projects is granted only through holders that have no
    static Onyx equivalent (Reporter, Assignee, Project Lead, user fields)."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="jira_project_access_mappable",
            display_name="Map project access",
            required=False,
            remediation=(
                "Grant Browse Projects to users, groups or project roles. Onyx "
                "cannot map Reporter, Assignee, Project Lead or user-field grants, "
                "so those users get no access in Onyx."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        project_key, scheme = _read_scheme_for_dependent_check(context, config)
        holders: list[dict[str, Any]] = _browse_holders(scheme)
        holder_types: set[str] = {str(holder.get("type")) for holder in holders}
        unsupported: list[str] = sorted(holder_types - SUPPORTED_STATIC_HOLDER_TYPES)
        if unsupported:
            raise ConnectorValidationError(
                f"The project `{project_key}` grants Browse Projects through "
                f"{', '.join(unsupported)}. Onyx cannot map these grants, so the "
                "users they cover get no access to the project's issues in Onyx.",
                summary="Some grants cannot map to users",
                description=(
                    f"{project_key} grants Browse Projects through "
                    f"{', '.join(unsupported)}.\nGrant Browse Projects to users, "
                    "groups or project roles instead."
                ),
            )
        return CheckOutput(summary=f"All {len(holders)} grants map to users")


def _role_actor_user(actor: dict[str, Any]) -> dict[str, Any] | None:
    """The user of a role actor: nested ``actorUser`` on Cloud, the flat actor
    on Data Center."""
    actor_user: Any = actor.get("actorUser")
    if isinstance(actor_user, dict):
        return actor_user
    if actor.get("type") == ATLASSIAN_USER_ROLE_ACTOR_TYPE:
        return actor
    return None


def _user_lookup_id(gateway: JiraSourceOperations, user: dict[str, Any]) -> str | None:
    fields: tuple[str, ...] = (
        ("accountId", "name", "key")
        if is_cloud_gateway(gateway)
        else (
            "name",
            "key",
            "accountId",
        )
    )
    for field in fields:
        value: Any = user.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _browse_role_ids(scheme: dict[str, Any]) -> list[str]:
    return [
        role_id
        for holder in _browse_holders(scheme)
        if holder.get("type") == HOLDER_TYPE_PROJECT_ROLE
        and (role_id := _role_id(holder))
    ]


def _read_role(
    context: CapabilityCheckContext,
    config: JiraConnectorConfig,
    project_key: str,
    role_id: str,
) -> dict[str, Any]:
    """Reads one project role. Raises the validation family on a failed read."""
    try:
        return _gateway(context).get_project_role(
            project_key=project_key, role_id=role_id, fast=True
        )
    except JiraApiError as e:
        _raise_for_api_error(
            e,
            denied=(
                f"The credential cannot read the roles of the project "
                f"`{project_key}`. {_perm_sync_hint(config, _ADMIN_HINT)}"
            ),
            denied_row=_RowText(
                summary="Account cannot read project roles",
                description=(
                    f"Users with access through roles in {project_key} would get "
                    f"none. (HTTP 403)\n{_ADMIN_NEED}"
                ),
            ),
            scope_row=_PERMISSION_SYNC_SCOPE_ROW,
            not_found=(
                f"Jira does not return the role {role_id} of the project "
                f"`{project_key}` to this credential. "
                f"{_perm_sync_hint(config, _ADMIN_HINT)}"
            ),
            not_found_row=_RowText(
                summary="Project role not found",
                description=(
                    f"Jira did not return role {role_id} of {project_key} to this "
                    "account. (HTTP 404)"
                ),
            ),
        )


def _is_public(scheme: dict[str, Any]) -> bool:
    """True when anyone or every licensed user can browse the project.
    Permission sync then returns public access without reading roles or
    users."""
    return any(
        holder.get("type") in _PUBLIC_HOLDER_TYPES for holder in _browse_holders(scheme)
    )


class _ProjectRolesReadCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="jira_project_roles_read",
            display_name="Read project roles",
            remediation=(
                f"{_ADMIN_HINT} Scoped API token: the {_PERMISSION_SYNC_SCOPES} scopes."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        project_key, scheme = _read_scheme_for_dependent_check(context, config)
        role_ids: list[str] = _browse_role_ids(scheme)
        if _is_public(scheme):
            raise NothingToCheckError(
                f"The project `{project_key}` is open to all users, so permission "
                "sync reads no role.",
                summary=f"{project_key} is open to all users",
                description="Permission sync needs no role members.",
            )
        if not role_ids:
            raise NothingToCheckError(
                f"No project role holds Browse Projects in `{project_key}`.",
                summary="No role grants to test",
                description=f"No project role holds Browse Projects in {project_key}.",
            )
        role: dict[str, Any] = _read_role(context, config, project_key, role_ids[0])
        actors: Any = role.get("actors")
        if not isinstance(actors, list):
            raise InsufficientPermissionsError(
                f"Jira returned a role of the project `{project_key}` without its "
                f"members. {_perm_sync_hint(config, _ADMIN_HINT)}",
                summary="Role came back without members",
                description=(
                    f"Jira returned a role of {project_key} without its members.\n"
                    "Give the token's account Administer Jira, or Administer "
                    "Projects on every synced project."
                ),
            )
        return CheckOutput(
            summary=f"Read {role.get('name') or 'a role'}: {len(actors)} members"
        )


def _is_group_actor(actor: dict[str, Any]) -> bool:
    return (
        isinstance(actor.get("actorGroup"), dict)
        or actor.get("type") == ATLASSIAN_GROUP_ROLE_ACTOR_TYPE
    )


class _PermissionUserEmailsCheck(_JiraCheck):
    """People who hold Browse Projects, directly or through a project role,
    have emails. Permission sync maps them to Onyx users by email.

    Passes for a public project (``anyone`` or ``applicationRole``), which syncs
    without reading users, and for a project with group grants, which give
    access through group sync. Fails when the sample covers every user the
    sync reads and no user maps: no user account holds the grant, or every
    user hides the email. A partial sample is INCOMPLETE."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="jira_permission_user_emails",
            display_name="Read user emails",
            remediation=(
                "Make user emails visible to the token's account. "
                f"Cloud: {_CLOUD_EMAIL_HINT} Data Center: {_DC_EMAIL_HINT}"
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        gateway: JiraSourceOperations = _gateway(context)
        project_key, scheme = _read_scheme_for_dependent_check(context, config)
        holders: list[dict[str, Any]] = _browse_holders(scheme)
        holder_types: set[str] = {str(holder.get("type")) for holder in holders}
        if _is_public(scheme):
            raise NothingToCheckError(
                f"The project `{project_key}` is open to all users, so permission "
                "sync reads no user.",
                summary=f"{project_key} is open to all users",
                description="Permission sync needs no user emails.",
            )
        if HOLDER_TYPE_GROUP in holder_types:
            raise NothingToCheckError(
                f"The project `{project_key}` grants access through groups, which "
                "group sync maps.",
                summary="Access comes through groups",
                description=f"Group sync gives the access in {project_key}.",
            )
        # Direct user grants carry the expanded user.
        emails: list[str | None] = [
            holder["user"].get("emailAddress")
            for holder in holders
            if holder.get("type") == HOLDER_TYPE_USER
            and isinstance(holder.get("user"), dict)
        ]
        role_ids: list[str] = _browse_role_ids(scheme)
        try:
            roles: list[dict[str, Any]] = [
                _read_role(context, config, project_key, role_id)
                for role_id in role_ids[:_SAMPLE_ROLES]
            ]
        except ConnectorValidationError as e:
            raise UnexpectedValidationError(
                "Onyx cannot read the project roles, so this check cannot run. "
                "jira_project_roles_read reports why.",
                summary="Cannot read project roles",
                description="Read project roles reports why.",
            ) from e
        actors: list[dict[str, Any]] = [
            actor
            for role in roles
            for actor in role.get("actors") or []
            if isinstance(actor, dict)
        ]
        if any(_is_group_actor(actor) for actor in actors):
            raise NothingToCheckError(
                f"The roles of the project `{project_key}` grant access through "
                "groups, which group sync maps.",
                summary="Access comes through groups",
                description=f"Group sync gives the access in {project_key}.",
            )
        role_users: list[dict[str, Any]] = [
            user for actor in actors if (user := _role_actor_user(actor))
        ]
        complete_sample: bool = (
            len(role_ids) <= _SAMPLE_ROLES and len(role_users) <= _SAMPLE_USERS
        )
        for user in role_users[:_SAMPLE_USERS]:
            lookup_id: str | None = _user_lookup_id(gateway, user)
            if not lookup_id:
                continue
            try:
                details: dict[str, Any] = gateway.get_user(user_id=lookup_id, fast=True)
            except JiraApiError as e:
                _raise_for_api_error(
                    e,
                    denied=(
                        "The credential cannot read Jira users. "
                        f"{_perm_sync_hint(config, _GROUP_ACCESS_HINT)}"
                    ),
                    denied_row=_RowText(
                        summary="Account cannot read users",
                        description=(
                            f"Jira refused user details. (HTTP 403)\n{_GROUP_ACCESS_NEED}"
                        ),
                    ),
                    scope_row=_USER_SCOPE_ROW,
                )
            account_type: Any = details.get("accountType")
            if account_type is not None and account_type != _ATLASSIAN_ACCOUNT_TYPE:
                # Apps and customers never map to Onyx users.
                continue
            emails.append(details.get("emailAddress"))
        if not emails:
            if not complete_sample:
                raise InconclusiveValidationError(
                    f"The sampled grants of the project `{project_key}` hold no "
                    "user account. Permission sync reads more users, so Onyx "
                    "cannot verify the rest.",
                    summary="No user accounts in the sample",
                    description=(
                        f"The sampled grants of {project_key} hold no user "
                        "account, and sync reads more."
                    ),
                )
            raise ConnectorValidationError(
                f"The Browse Projects grants of the project `{project_key}` hold "
                "no user, group, or public access that Onyx can map, so no user "
                "would get access to its issues in Onyx. Grant Browse Projects "
                "to users, groups or project roles with members.",
                summary="Grants hold no users to map",
                description=(
                    f"The Browse Projects grants of {project_key} hold no user, "
                    "group or public access."
                ),
            )
        with_email: int = sum(1 for email in emails if email)
        if not with_email:
            if not complete_sample:
                raise InconclusiveValidationError(
                    f"The sampled users who can browse the project `{project_key}` "
                    "have no visible email. Permission sync reads more users, so "
                    f"Onyx cannot verify the rest. {_email_hint(gateway)}",
                    summary="Sampled users show no email",
                    description=(
                        f"The sampled users of {project_key} show no email, and "
                        "sync reads more users."
                    ),
                )
            raise InsufficientPermissionsError(
                f"No user who can browse the project `{project_key}` has a visible "
                "email, so their access cannot map to Onyx users. "
                f"{_email_hint(gateway)}",
                summary="No user shows an email",
                description=(
                    f"Users with access to {project_key} would get none in Onyx.\n"
                    f"{_EMAIL_NEED}"
                ),
            )
        return CheckOutput(
            summary=f"{with_email} of {len(emails)} users show an email",
            advisories=_missing_email_caveat(len(emails) - with_email),
        )


def _missing_email_caveat(missing: int) -> list[CheckAdvisory]:
    if not missing:
        return []
    return [
        CheckAdvisory(
            message=(
                f"{missing} users without a visible email get no access to synced "
                "issues."
            )
        )
    ]


def _list_groups(
    context: CapabilityCheckContext, config: JiraConnectorConfig
) -> JiraGroupPage:
    try:
        return _gateway(context).list_groups(fast=True)
    except JiraApiError as e:
        _raise_for_api_error(
            e,
            denied=(
                "The credential cannot list Jira groups. "
                f"{_perm_sync_hint(config, _GROUP_ACCESS_HINT)}"
            ),
            denied_row=_RowText(
                summary="Account cannot list groups",
                description=f"Jira refused the group list. (HTTP 403)\n{_GROUP_ACCESS_NEED}",
            ),
            scope_row=_RowText(
                summary="Token lacks a group sync scope",
                description=_PERMISSION_SYNC_SCOPE_ROW.description,
            ),
        )


def _list_groups_for_dependent_check(
    context: CapabilityCheckContext, config: JiraConnectorConfig
) -> list[str]:
    try:
        group_names: list[str] = _list_groups(context, config).group_names
    except ConnectorValidationError as e:
        raise UnexpectedValidationError(
            "Onyx cannot list Jira groups, so this check cannot run. "
            "jira_group_listing reports why.",
            summary="Cannot list groups",
            description="List groups reports why.",
        ) from e
    if not group_names:
        raise UnexpectedValidationError(
            "Jira listed no groups, so Onyx cannot read group members. "
            "jira_group_listing reports why.",
            summary="No groups to read",
            description="List groups reports why.",
        )
    return group_names


def _sample_group_members(
    context: CapabilityCheckContext, config: JiraConnectorConfig
) -> JiraGroupMemberSample:
    gateway: JiraSourceOperations = _gateway(context)
    group_names: list[str] = _list_groups_for_dependent_check(context, config)
    members: list[dict[str, Any]] = []
    complete: bool = len(group_names) <= _SAMPLE_GROUPS
    for group_name in group_names[:_SAMPLE_GROUPS]:
        try:
            page: dict[str, Any] = gateway.get_group_members_page(
                group_name=group_name,
                start_at=0,
                max_results=_GROUP_MEMBER_PAGE_SIZE,
                fast=True,
            )
        except JiraApiError as e:
            if e.status_code == 404 and "does not exist" in (e.body or ""):
                # The group was deleted after the listing; group sync skips it.
                continue
            _raise_for_api_error(
                e,
                denied=(
                    f"The credential cannot read the members of the group "
                    f"`{group_name}`. {_perm_sync_hint(config, _GROUP_ACCESS_HINT)}"
                ),
                denied_row=_RowText(
                    summary="Account cannot read group members",
                    description=(
                        f"Jira refused the members of {group_name}. (HTTP 403)\n"
                        f"{_GROUP_ACCESS_NEED}"
                    ),
                ),
                scope_row=_RowText(
                    summary="Token lacks the read:jira-user scope",
                    description=(
                        "The token signs in but lacks the scope this call needs. "
                        "(HTTP 401)\nAdd read:jira-user, or the read:group:jira, "
                        "read:user:jira and read:avatar:jira scopes."
                    ),
                ),
                not_found=(
                    "Jira has no group-member API (GET /group/member, Jira 6.0+). "
                    "Upgrade Jira"
                ),
                not_found_row=_RowText(
                    summary="Jira has no group member API",
                    description=(
                        "This Jira version has no group-member API (Jira 6.0+). "
                        "(HTTP 404)\nUpgrade Jira to 6.0 or later."
                    ),
                ),
            )
        page_members: Any = page.get("values")
        if isinstance(page_members, list):
            members.extend(m for m in page_members if isinstance(m, dict))
        if not page.get("isLast", True):
            complete = False
    return JiraGroupMemberSample(
        members=members,
        complete=complete,
        groups_read=min(len(group_names), _SAMPLE_GROUPS),
    )


class _GroupListingCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="jira_group_listing",
            display_name="List groups",
            remediation=(
                f"{_GROUP_ACCESS_HINT} Scoped API token: the "
                f"{_PERMISSION_SYNC_SCOPES} scopes."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        group_names: list[str] = _list_groups(context, config).group_names
        if not group_names:
            # Group sync fails when the listing is empty.
            raise InsufficientPermissionsError(
                "Jira listed no groups, and group sync fails without groups. "
                f"{_perm_sync_hint(config, _GROUP_ACCESS_HINT)}",
                summary="No groups listed",
                description=(
                    "Jira returned no groups, and group sync fails without groups.\n"
                    f"{_GROUP_ACCESS_NEED}"
                ),
            )
        return CheckOutput(summary=f"{len(group_names)} groups listed")


class _GroupListingCompleteCheck(_JiraCheck):
    """``groups/picker`` returns at most its result limit, which a site can set
    lower than the number of groups."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="jira_group_listing_complete",
            row_id="jira_group_listing",
            display_name="List groups",
            required=False,
            remediation=(
                "Group sync skips the groups after the limit, so their members "
                "lose access in Onyx. A Jira administrator can raise the "
                "jira.ajax.autocomplete.limit setting (Data Center)."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        try:
            page: JiraGroupPage = _list_groups(context, config)
        except ConnectorValidationError as e:
            raise UnexpectedValidationError(
                "Onyx cannot list Jira groups, so this check cannot run. "
                "jira_group_listing reports why.",
                summary="Cannot list groups",
                description="List groups reports why.",
            ) from e
        returned: int = len(page.group_names)
        if page.total is None:
            raise InconclusiveValidationError(
                "Jira did not report how many groups match, so Onyx cannot tell "
                "whether the listing is complete.",
                summary="Jira did not report a group total",
                description="A cut-off group list cannot be detected.",
            )
        if page.total > returned:
            raise ConnectorValidationError(
                f"Jira matched {page.total} groups but returned only "
                f"{returned}, so group sync misses {page.total - returned} groups.",
                summary=f"Only {returned} of {page.total} groups listed",
                description=(
                    f"Members of the {page.total - returned} missing groups would "
                    "lose access."
                ),
            )
        return CheckOutput(summary=f"All {page.total} groups listed")


class _GroupMembershipCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="jira_group_membership",
            display_name="Read group members",
            remediation=(
                f"{_GROUP_ACCESS_HINT} Scoped API token: the `read:jira-user` "
                "scope, or the granular `read:group:jira`, `read:user:jira` and "
                "`read:avatar:jira` scopes."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        sample: JiraGroupMemberSample = _sample_group_members(context, config)
        if not sample.members:
            # The reads succeeded: the first groups can be empty.
            raise InconclusiveValidationError(
                "The sampled groups have no members, so Onyx did not verify that "
                "group members are readable.",
                summary="No members found to test",
                description="The first groups have no active members.",
            )
        return CheckOutput(
            summary=(
                f"Read {len(sample.members)} members in {sample.groups_read} groups"
            )
        )


class _GroupMemberEmailsCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="jira_group_member_emails",
            display_name="Read member emails",
            remediation=(
                "Make user emails visible to the token's account. "
                f"Cloud: {_CLOUD_EMAIL_HINT} Data Center: {_DC_EMAIL_HINT}"
            ),
        )

    def run(self, context: CapabilityCheckContext) -> CheckOutput:
        config: JiraConnectorConfig = self.config(context)
        try:
            sample: JiraGroupMemberSample = _sample_group_members(context, config)
        except ConnectorValidationError as e:
            raise UnexpectedValidationError(
                "Onyx cannot read group members, so this check cannot run. "
                "jira_group_membership reports why.",
                summary="Cannot read group members",
                description="Read group members reports why.",
            ) from e
        # Group sync skips app and customer accounts.
        people: list[dict[str, Any]] = [
            member
            for member in sample.members
            if member.get("accountType") in (None, _ATLASSIAN_ACCOUNT_TYPE)
        ]
        if not people:
            raise InconclusiveValidationError(
                "The sampled groups have no user members, so Onyx did not verify "
                "that group members have emails.",
                summary="No user members found to test",
                description="The sampled groups hold no user accounts.",
            )
        with_email: int = sum(1 for member in people if member.get("emailAddress"))
        if not with_email:
            if not sample.complete:
                raise InconclusiveValidationError(
                    "The sampled group members have no visible email. Group sync "
                    "reads more groups and members, so Onyx cannot verify the "
                    f"rest. {_email_hint(_gateway(context))}",
                    summary="Sampled members show no email",
                    description=(
                        "The sampled members show no email, and group sync reads "
                        "more members."
                    ),
                )
            raise InsufficientPermissionsError(
                "No member of the sampled group has a visible email, so group "
                f"members cannot map to Onyx users. {_email_hint(_gateway(context))}",
                summary="No member shows an email",
                description=f"Group access would reach no one.\n{_EMAIL_NEED}",
            )
        return CheckOutput(
            summary=f"{with_email} of {len(people)} members show an email",
            advisories=_missing_email_caveat(len(people) - with_email),
        )


def build_jira_doc_permission_sync_checks() -> list[CapabilityCheck]:
    return [
        _PermissionSchemeReadCheck(),
        _ProjectAccessMappableCheck(),
        _ProjectRolesReadCheck(),
        _PermissionUserEmailsCheck(),
    ]


def build_jira_group_sync_checks() -> list[CapabilityCheck]:
    return [
        _GroupListingCheck(),
        _GroupListingCompleteCheck(),
        _GroupMembershipCheck(),
        _GroupMemberEmailsCheck(),
    ]
