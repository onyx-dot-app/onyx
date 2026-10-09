"""Capability checks for the Jira connector.

The indexing checks register in ``registry.py``. Each check makes small probes
(one issue, one project) with the gateway operations that its sync calls.

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

import re
import time
from typing import Any, NoReturn
from urllib.parse import urlparse

import requests

from onyx.connectors.capability_checks.form_state import FormState
from onyx.connectors.capability_checks.models import (
    CapabilityCheck,
    CapabilityCheckContext,
    CredentialCapability,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialExpiredError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.jira.config import JiraConnectorConfig
from onyx.connectors.jira.connector import build_jql_query, jira_error_messages
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira.source_operations import (
    JiraApiError,
    JiraSourceOperations,
    is_cloud_gateway,
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

_ORDER_BY_PATTERN = re.compile(r"\border\s+by\b", re.IGNORECASE)
# A quoted JQL value; a backslash escapes the next character.
_QUOTED_PATTERN = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'")

_INDEXING_SCOPE = "read:jira-work"


def _gateway(context: CapabilityCheckContext) -> JiraSourceOperations:
    gateway: SourceOperations | None = context.source_operations
    if not isinstance(gateway, JiraSourceOperations):
        raise TypeError(
            "Bug: The runner constructs the registered gateway for migrated sources."
        )
    return gateway


def _project_key(config: JiraConnectorConfig) -> str:
    return (config.project_key or "").strip()


def _jql(config: JiraConnectorConfig) -> str:
    return (config.jql_query or "").strip()


def _scope_jql(config: JiraConnectorConfig) -> str:
    """The query of a full indexing run: the configured scope, from the epoch
    to now."""
    return build_jql_query(
        project_key=config.project_key or None,
        jql_query=config.jql_query or None,
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


def _error_detail(error: JiraApiError) -> str:
    messages: str | None = jira_error_messages(error.text)
    return (messages or error.text or str(error))[:_ERROR_DETAIL_CHARS]


def _raise_for_api_error(
    error: JiraApiError,
    *,
    denied: str,
    not_found: str | None = None,
    bad_request: str | None = None,
) -> NoReturn:
    """Maps a Jira API error onto the validation-exception family. ``denied``
    explains a 403 (or a scoped token without the scope) for this probe."""
    status: int | None = error.status_code
    detail: str = _error_detail(error)
    if status == 401 and _SCOPE_MISMATCH_TEXT in (error.text or ""):
        raise InsufficientPermissionsError(
            f"{denied}. The scoped API token does not have the scope of this API "
            "(HTTP 401: scope does not match)."
        ) from error
    if status == 401:
        raise CredentialExpiredError(
            "Jira rejected the credential (HTTP 401). The token is wrong, expired, "
            "or revoked, or the email does not match the token's account."
        ) from error
    if status == 403:
        raise InsufficientPermissionsError(f"{denied} (HTTP 403).") from error
    if status == 404 and not_found is not None:
        raise ConnectorValidationError(f"{not_found} (HTTP 404).") from error
    if status == 400 and bad_request is not None:
        raise ConnectorValidationError(f"{bad_request} (HTTP 400): {detail}") from error
    if status == _RATE_LIMITED_STATUS:
        raise UnexpectedValidationError(
            "Jira rate limited the check. Run the checks again in a minute."
        ) from error
    raise UnexpectedValidationError(
        f"Unexpected Jira response (HTTP {status}): {detail}"
    ) from error


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
    ) -> None:
        super().__init__(
            capability=capability,
            check_id=check_id,
            display_name=display_name,
            required=required,
            requires_connector_instance=False,
            requires_fields=_SITE_FIELDS,
            remediation=remediation,
            docs_link=_DOCS_LINK,
            validates_binding=validates_binding,
        )


def _is_cloud_site(config: JiraConnectorConfig) -> bool:
    host: str = urlparse(config.jira_base_url).hostname or ""
    return host.endswith(_CLOUD_HOST_SUFFIX)


class _SiteAuthCheck(_JiraCheck):
    """Signs in the way the connector does (``myself``).

    One check per token type: a scoped API token resolves the cloud id
    (``tenant_info``) and calls ``api.atlassian.com``; other tokens call the
    site URL. ``myself`` needs a user scope that indexing does not, so a
    scoped token without it still proves sign-in; jira_projects_visible
    checks the indexing scope.
    """

    def __init__(self, *, scoped: bool) -> None:
        self._scoped = scoped
        if scoped:
            super().__init__(
                check_id="jira_scoped_token_auth",
                validates_binding=True,
                display_name="Scoped API token signs in to the site",
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
                display_name="Credential signs in to the site",
                remediation=(
                    "Jira Cloud: enter the email of the token's Atlassian account "
                    "and an API token. Jira Data Center: leave the email empty and "
                    "use a personal access token. Check the site URL, and create a "
                    "new token if it expired."
                ),
            )

    def applies(self, form_state: FormState[JiraConnectorConfig]) -> bool:
        return form_state.config.scoped_token == self._scoped

    def run(self, context: CapabilityCheckContext) -> None:
        gateway: JiraSourceOperations = _gateway(context)
        try:
            gateway.get_myself()
            return
        except requests.HTTPError as e:
            # Only the scoped token's tenant_info call raises a raw HTTPError.
            # tenant_info needs no auth: a 4xx means the URL is not a Cloud
            # site. 429 and 5xx fall through as INDETERMINATE.
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
                    "tokens work only with Jira Cloud; check the site URL."
                ) from e
            raise UnexpectedValidationError(
                f"Unexpected response from {config.jira_base_url}: {e}"
            ) from e
        except (requests.ConnectionError, requests.Timeout) as e:
            raise UnexpectedValidationError(
                f"Onyx cannot connect to {self.config(context).jira_base_url}. "
                "Check the site URL."
            ) from e
        except JiraApiError as e:
            if e.status_code == 401 and _SCOPE_MISMATCH_TEXT in (e.text or ""):
                # The token signed in; it only lacks the user scope of myself.
                return
            self._raise_for_sign_in_error(context, gateway, e)
        except (ValueError, KeyError) as e:
            if not self._scoped:
                raise
            # tenant_info returned no cloud id (e.g. an SSO login page).
            raise ConnectorValidationError(
                "Onyx cannot get the Atlassian cloud id of "
                f"{self.config(context).jira_base_url} (`{_TENANT_INFO_PATH}`). "
                "Scoped API tokens work only with Jira Cloud; check the site URL."
            ) from e

    def _raise_for_sign_in_error(
        self,
        context: CapabilityCheckContext,
        gateway: JiraSourceOperations,
        error: JiraApiError,
    ) -> NoReturn:
        config: JiraConnectorConfig = self.config(context)
        is_cloud_credential: bool = is_cloud_gateway(gateway)
        if not is_cloud_credential and (self._scoped or _is_cloud_site(config)):
            raise ConnectorValidationError(
                "Jira Cloud needs the email of the token's Atlassian account with "
                "the API token, but this credential has no email. Edit the "
                "credential and add the email."
            ) from error
        if is_cloud_credential and error.status_code == 404:
            raise ConnectorValidationError(
                f"{config.jira_base_url} has no Jira Cloud REST API (v3). For Jira "
                "Data Center, leave the email empty and use a personal access "
                "token. For Jira Cloud, check the site URL "
                "(https://your-domain.atlassian.net)."
            ) from error
        _raise_for_api_error(
            error,
            denied=(
                "The credential signs in, but Jira does not let its account use "
                "Jira on this site. Give the account Jira product access"
            ),
            not_found=(
                f"Jira has no REST API at {config.jira_base_url}. Check the site URL"
            ),
        )


class _ProjectsVisibleCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="jira_projects_visible",
            validates_binding=True,
            display_name="Projects are visible",
            remediation=(
                "Give the token's account the Browse Projects permission on the "
                "projects to index. Scoped API token: the `read:jira-work` scope."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        try:
            projects: list[dict[str, Any]] = _gateway(context).list_projects()
        except JiraApiError as e:
            config: JiraConnectorConfig = self.config(context)
            _raise_for_api_error(
                e,
                denied="The credential cannot list Jira projects. "
                + _access_hint(
                    config,
                    scope=_INDEXING_SCOPE,
                    user_permission="Browse Projects",
                ),
            )
        if not projects:
            config: JiraConnectorConfig = self.config(context)
            raise InsufficientPermissionsError(
                "No Jira project is visible to this credential. "
                + _access_hint(
                    config,
                    scope=_INDEXING_SCOPE,
                    user_permission="Browse Projects on the projects to index",
                )
            )


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
            display_name="Configured project is readable",
            remediation=(
                "Use the project key, not the project name (e.g. `PROJ`), and give "
                "the token's account Browse Projects on the project."
            ),
        )

    def applies(self, form_state: FormState[JiraConnectorConfig]) -> bool:
        config: JiraConnectorConfig = form_state.config
        return bool(_project_key(config)) and not _jql(config)

    def run(self, context: CapabilityCheckContext) -> None:
        config: JiraConnectorConfig = self.config(context)
        raw_key: str = config.project_key or ""
        project_key: str = raw_key.strip()
        gateway: JiraSourceOperations = _gateway(context)
        try:
            gateway.get_project(project_key=project_key)
        except JiraApiError as e:
            if e.status_code != 404:
                _raise_for_api_error(
                    e,
                    denied=f"The credential cannot read the project `{project_key}`",
                )
            self._raise_not_found(gateway, project_key, e)
        if raw_key != project_key:
            # The connector quotes the key as entered, spaces included.
            raise ConnectorValidationError(
                f"The project key `{raw_key}` has spaces around it. Remove them; "
                "the connector searches for the key exactly as entered."
            )

    def _raise_not_found(
        self, gateway: JiraSourceOperations, project_key: str, error: JiraApiError
    ) -> NoReturn:
        try:
            matches: list[str] = _matching_project_keys(
                gateway.list_projects(), project_key
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
            f"Projects on the project.{hint}"
        ) from error


def _validate_jql_shape(jql: str) -> None:
    """Rejects ORDER BY outside quoted values. The connector wraps the query in
    parentheses and adds a time filter, so ORDER BY makes it invalid."""
    unquoted: str = _QUOTED_PATTERN.sub('""', jql)
    if _ORDER_BY_PATTERN.search(unquoted):
        raise ConnectorValidationError(
            "Remove ORDER BY from the JQL query. Onyx wraps the query in "
            "parentheses and adds its own time filter, and Jira rejects ORDER BY "
            "inside parentheses."
        )


def _search_one_issue(gateway: JiraSourceOperations, jql: str) -> dict[str, Any] | None:
    """The first issue the query matches, with all fields, read through the
    API family the connector uses. Raises ``JiraApiError``."""
    if is_cloud_gateway(gateway):
        page: JiraIssueIdPage = gateway.search_issue_ids(jql=jql, max_results=1)
        if not page.issue_ids:
            return None
        issues: list[dict[str, Any]] = gateway.bulk_fetch_issues(
            issue_ids=page.issue_ids[:1]
        )
        return issues[0] if issues else {}
    issues: list[dict[str, Any]] = gateway.search_issues(
        jql=jql, start_at=0, max_results=1
    )
    return issues[0] if issues else None


class _JqlQueryCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            check_id="jira_jql_query",
            display_name="JQL query is valid",
            remediation=(
                "Test the query in Jira's issue search. Quote values that are "
                'reserved JQL words (e.g. project = "AS"). Use no ORDER BY.'
            ),
        )

    def applies(self, form_state: FormState[JiraConnectorConfig]) -> bool:
        return bool(_jql(form_state.config))

    def run(self, context: CapabilityCheckContext) -> None:
        config: JiraConnectorConfig = self.config(context)
        _validate_jql_shape(_jql(config))
        try:
            issue: dict[str, Any] | None = _search_one_issue(
                _gateway(context), _scope_jql(config)
            )
        except JiraApiError as e:
            _raise_for_api_error(
                e,
                denied="The credential cannot search Jira issues",
                bad_request="Jira rejected the JQL query",
            )
        if issue is None:
            # Not FAILED: the scope can be empty on purpose (issues come later).
            raise UnexpectedValidationError(
                "The JQL query matches no issue that this credential can read, so "
                "Onyx cannot verify it. Check the query if issues exist."
            )


class _IssueReadCheck(_JiraCheck):
    """Reads the first in-scope issue with all its fields, through the same
    search the indexing run uses."""

    def __init__(self) -> None:
        super().__init__(
            check_id="jira_issue_read",
            display_name="Issues are readable",
            remediation=(
                "Give the token's account Browse Projects on the projects to "
                "index, and access to their issue security levels. Scoped API "
                "token: the `read:jira-work` scope."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config: JiraConnectorConfig = self.config(context)
        hint: str = _access_hint(
            config,
            scope=_INDEXING_SCOPE,
            user_permission="Browse Projects on the projects to index",
        )
        try:
            issue: dict[str, Any] | None = _search_one_issue(
                _gateway(context), _scope_jql(config)
            )
        except JiraApiError as e:
            if e.status_code == 400:
                # jira_jql_query / jira_configured_project report a bad scope.
                raise UnexpectedValidationError(
                    "Jira rejected the indexing scope query, so this check cannot "
                    f"run. Fix the scope settings first: {_error_detail(e)}"
                ) from e
            _raise_for_api_error(
                e, denied=f"The credential cannot search Jira issues. {hint}"
            )
        if issue is None:
            # Not FAILED: the scope can be empty on purpose (issues come later).
            raise UnexpectedValidationError(
                "The indexing scope has no issue that this credential can read, "
                f"so Onyx cannot verify that issues are readable. {hint}"
            )
        fields: object = issue.get("fields")
        if not isinstance(fields, dict) or "summary" not in fields:
            raise InsufficientPermissionsError(
                "Jira found an issue but did not return its fields, so issues "
                f"would index without content. {hint}"
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
