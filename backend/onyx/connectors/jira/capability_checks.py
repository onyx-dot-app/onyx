"""Capability checks for the Jira connector.

The indexing checks register in ``registry.py``; the permission-sync and
group-sync checks register in the EE registry
(``ee/onyx/connectors/capability_checks.py``). Each check makes small probes
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
    JiraGroupPage,
    JiraSourceOperations,
    is_cloud_gateway,
)
from onyx.connectors.jira.utils import (
    ATLASSIAN_USER_ROLE_ACTOR_TYPE,
    BROWSE_PROJECTS_PERMISSION,
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
            if self._scoped:
                gateway.list_projects()
            else:
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
        project_key: str = _project_key(config)
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


# Permission sync. The EE registry registers these checks. Doc sync reads the
# Browse Projects grants of each project's permission scheme, the actors of its
# project roles, and the email of each user. Group sync lists the groups and
# the members of each group. Both map Jira users to Onyx users by email.

_PERMISSION_SYNC_SCOPES = "`read:jira-user` and `manage:jira-configuration`"
_SAMPLE_USERS = 5
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
    reads the scheme of every project with indexed issues."""
    project_key = _project_key(config)
    if project_key and not _jql(config):
        return project_key
    if _jql(config):
        try:
            issue = _search_one_issue(_gateway(context), _scope_jql(config))
        except JiraApiError as e:
            raise UnexpectedValidationError(
                "Onyx cannot run the JQL query, so it cannot pick a project to "
                "probe. jira_jql_query reports why."
            ) from e
        project = get_issue_field(issue, "project") if issue else None
        if isinstance(project, dict) and project.get("key"):
            return str(project["key"])
    try:
        projects = _gateway(context).list_projects()
    except JiraApiError as e:
        _raise_for_api_error(e, denied="The credential cannot list Jira projects")
    if not projects:
        raise UnexpectedValidationError(
            "No Jira project is visible, so Onyx cannot read a permission scheme. "
            "jira_projects_visible reports why."
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
    role_id = holder.get("value") or holder.get("parameter")
    return str(role_id) if role_id else None


def _read_permission_scheme(
    context: CapabilityCheckContext, config: JiraConnectorConfig, project_key: str
) -> dict[str, Any]:
    try:
        scheme = _gateway(context).get_project_permission_scheme(
            project_key=project_key
        )
    except JiraApiError as e:
        _raise_for_api_error(
            e,
            denied=(
                "The credential cannot read the permission scheme of the project "
                f"`{project_key}`. {_perm_sync_hint(config, _ADMIN_HINT)}"
            ),
            not_found=(
                f"Jira does not return the permission scheme of the project "
                f"`{project_key}` to this credential. "
                f"{_perm_sync_hint(config, _ADMIN_HINT)}"
            ),
        )
    if not isinstance(scheme.get("permissions"), list):
        raise InsufficientPermissionsError(
            f"Jira returned the permission scheme of the project `{project_key}` "
            f"without its grants. {_perm_sync_hint(config, _ADMIN_HINT)}"
        )
    return scheme


def _read_scheme_for_dependent_check(
    context: CapabilityCheckContext, config: JiraConnectorConfig
) -> tuple[str, dict[str, Any]]:
    """The probe project and its scheme, for a check that needs the scheme
    first. A failed read is jira_permission_scheme_read's failure."""
    try:
        project_key = _probe_project_key(context, config)
        return project_key, _read_permission_scheme(context, config, project_key)
    except ConnectorValidationError as e:
        raise UnexpectedValidationError(
            "Onyx cannot read the permission scheme, so this check cannot run. "
            "jira_permission_scheme_read reports why."
        ) from e


class _PermissionSchemeReadCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="jira_permission_scheme_read",
            display_name="Project permission schemes are readable",
            remediation=(
                f"{_ADMIN_HINT} Scoped API token: the {_PERMISSION_SYNC_SCOPES} scopes."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        project_key = _probe_project_key(context, config)
        scheme = _read_permission_scheme(context, config, project_key)
        if not _browse_holders(scheme):
            raise InsufficientPermissionsError(
                f"The permission scheme of the project `{project_key}` grants "
                "Browse Projects to nobody that Jira shows to this credential. "
                f"{_perm_sync_hint(config, _ADMIN_HINT)}"
            )


class _ProjectAccessMappableCheck(_JiraCheck):
    """Warns when Browse Projects is granted only through holders that have no
    static Onyx equivalent (Reporter, Assignee, Project Lead, user fields)."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="jira_project_access_mappable",
            display_name="Project access maps to Onyx",
            required=False,
            remediation=(
                "Grant Browse Projects to users, groups or project roles. Onyx "
                "cannot map Reporter, Assignee, Project Lead or user-field grants, "
                "so those users get no access in Onyx."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        project_key, scheme = _read_scheme_for_dependent_check(context, config)
        holder_types = {str(holder.get("type")) for holder in _browse_holders(scheme)}
        unsupported = sorted(holder_types - SUPPORTED_STATIC_HOLDER_TYPES)
        if unsupported:
            raise ConnectorValidationError(
                f"The project `{project_key}` grants Browse Projects through "
                f"{', '.join(unsupported)}. Onyx cannot map these grants, so the "
                "users they cover get no access to the project's issues in Onyx."
            )


def _role_actor_user(actor: dict[str, Any]) -> dict[str, Any] | None:
    """The user of a role actor: nested ``actorUser`` on Cloud, the flat actor
    on Data Center."""
    actor_user = actor.get("actorUser")
    if isinstance(actor_user, dict):
        return actor_user
    if actor.get("type") == ATLASSIAN_USER_ROLE_ACTOR_TYPE:
        return actor
    return None


def _user_lookup_id(gateway: JiraSourceOperations, user: dict[str, Any]) -> str | None:
    fields = (
        ("accountId", "name", "key")
        if is_cloud_gateway(gateway)
        else (
            "name",
            "key",
            "accountId",
        )
    )
    for field in fields:
        value = user.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _read_first_role(
    context: CapabilityCheckContext,
    config: JiraConnectorConfig,
    project_key: str,
    scheme: dict[str, Any],
) -> dict[str, Any] | None:
    """The first project role that holds Browse Projects, or None when no role
    does. Raises the validation family on a failed read."""
    role_ids = [
        role_id
        for holder in _browse_holders(scheme)
        if holder.get("type") == HOLDER_TYPE_PROJECT_ROLE
        and (role_id := _role_id(holder))
    ]
    if not role_ids:
        return None
    try:
        return _gateway(context).get_project_role(
            project_key=project_key, role_id=role_ids[0]
        )
    except JiraApiError as e:
        _raise_for_api_error(
            e,
            denied=(
                f"The credential cannot read the roles of the project "
                f"`{project_key}`. {_perm_sync_hint(config, _ADMIN_HINT)}"
            ),
            not_found=(
                f"Jira does not return the role {role_ids[0]} of the project "
                f"`{project_key}` to this credential. "
                f"{_perm_sync_hint(config, _ADMIN_HINT)}"
            ),
        )


class _ProjectRolesReadCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="jira_project_roles_read",
            display_name="Project roles are readable",
            remediation=(
                f"{_ADMIN_HINT} Scoped API token: the {_PERMISSION_SYNC_SCOPES} scopes."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        project_key, scheme = _read_scheme_for_dependent_check(context, config)
        role = _read_first_role(context, config, project_key, scheme)
        if role is not None and not isinstance(role.get("actors"), list):
            raise InsufficientPermissionsError(
                f"Jira returned a role of the project `{project_key}` without its "
                f"members. {_perm_sync_hint(config, _ADMIN_HINT)}"
            )


class _PermissionUserEmailsCheck(_JiraCheck):
    """People who hold Browse Projects, directly or through a project role,
    have emails. Permission sync maps them to Onyx users by email."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.DOC_PERMISSION_SYNC,
            check_id="jira_permission_user_emails",
            display_name="Users in permissions have emails",
            remediation=(
                "Make user emails visible to the token's account. "
                f"Cloud: {_CLOUD_EMAIL_HINT} Data Center: {_DC_EMAIL_HINT}"
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        gateway = _gateway(context)
        project_key, scheme = _read_scheme_for_dependent_check(context, config)
        # Direct user grants carry the expanded user.
        emails = [
            holder["user"].get("emailAddress")
            for holder in _browse_holders(scheme)
            if holder.get("type") == HOLDER_TYPE_USER
            and isinstance(holder.get("user"), dict)
        ]
        try:
            role = _read_first_role(context, config, project_key, scheme)
        except ConnectorValidationError as e:
            raise UnexpectedValidationError(
                "Onyx cannot read the project roles, so this check cannot run. "
                "jira_project_roles_read reports why."
            ) from e
        actors = role.get("actors") if role is not None else None
        role_users = [
            user
            for actor in actors or []
            if isinstance(actor, dict) and (user := _role_actor_user(actor))
        ]
        for user in role_users[:_SAMPLE_USERS]:
            lookup_id = _user_lookup_id(gateway, user)
            if not lookup_id:
                continue
            try:
                details = gateway.get_user(user_id=lookup_id)
            except JiraApiError as e:
                _raise_for_api_error(
                    e,
                    denied=(
                        "The credential cannot read Jira users. "
                        f"{_perm_sync_hint(config, _GROUP_ACCESS_HINT)}"
                    ),
                )
            account_type = details.get("accountType")
            if account_type is not None and account_type != _ATLASSIAN_ACCOUNT_TYPE:
                # Apps and customers never map to Onyx users.
                continue
            emails.append(details.get("emailAddress"))
        if emails and not any(emails):
            raise InsufficientPermissionsError(
                f"No user who can browse the project `{project_key}` has a visible "
                "email, so their access cannot map to Onyx users. "
                f"{_email_hint(gateway)}"
            )


def _list_groups(
    context: CapabilityCheckContext, config: JiraConnectorConfig
) -> JiraGroupPage:
    try:
        return _gateway(context).list_groups()
    except JiraApiError as e:
        _raise_for_api_error(
            e,
            denied=(
                "The credential cannot list Jira groups. "
                f"{_perm_sync_hint(config, _GROUP_ACCESS_HINT)}"
            ),
        )


def _list_groups_for_dependent_check(
    context: CapabilityCheckContext, config: JiraConnectorConfig
) -> list[str]:
    try:
        group_names = _list_groups(context, config).group_names
    except ConnectorValidationError as e:
        raise UnexpectedValidationError(
            "Onyx cannot list Jira groups, so this check cannot run. "
            "jira_group_listing reports why."
        ) from e
    if not group_names:
        raise UnexpectedValidationError(
            "Jira listed no groups, so Onyx cannot read group members. "
            "jira_group_listing reports why."
        )
    return group_names


def _sample_group_members(
    context: CapabilityCheckContext, config: JiraConnectorConfig
) -> list[dict[str, Any]]:
    """The first page of members of the first groups that have members."""
    gateway = _gateway(context)
    for group_name in _list_groups_for_dependent_check(context, config)[
        :_SAMPLE_GROUPS
    ]:
        try:
            page = gateway.get_group_members_page(
                group_name=group_name,
                start_at=0,
                max_results=_GROUP_MEMBER_PAGE_SIZE,
            )
        except JiraApiError as e:
            if e.status_code == 404 and "does not exist" in (e.text or ""):
                # The group was deleted after the listing; group sync skips it.
                continue
            _raise_for_api_error(
                e,
                denied=(
                    f"The credential cannot read the members of the group "
                    f"`{group_name}`. {_perm_sync_hint(config, _GROUP_ACCESS_HINT)}"
                ),
                not_found=(
                    "Jira has no group-member API (GET /group/member, Jira 6.0+). "
                    "Upgrade Jira"
                ),
            )
        members = page.get("values")
        if isinstance(members, list) and members:
            return members
    return []


class _GroupListingCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="jira_group_listing",
            display_name="Groups can be listed",
            remediation=(
                f"{_GROUP_ACCESS_HINT} Scoped API token: the "
                f"{_PERMISSION_SYNC_SCOPES} scopes."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        if not _list_groups(context, config).group_names:
            # Group sync fails when the listing is empty.
            raise InsufficientPermissionsError(
                "Jira listed no groups, and group sync fails without groups. "
                f"{_perm_sync_hint(config, _GROUP_ACCESS_HINT)}"
            )


class _GroupListingCompleteCheck(_JiraCheck):
    """``groups/picker`` returns at most its result limit, which a site can set
    lower than the number of groups."""

    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="jira_group_listing_complete",
            display_name="Group listing is complete",
            required=False,
            remediation=(
                "Group sync skips the groups after the limit, so their members "
                "lose access in Onyx. A Jira administrator can raise the "
                "jira.ajax.autocomplete.limit setting (Data Center)."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        try:
            page = _list_groups(context, config)
        except ConnectorValidationError as e:
            raise UnexpectedValidationError(
                "Onyx cannot list Jira groups, so this check cannot run. "
                "jira_group_listing reports why."
            ) from e
        if page.total is not None and page.total > len(page.group_names):
            raise ConnectorValidationError(
                f"Jira matched {page.total} groups but returned only "
                f"{len(page.group_names)}, so group sync misses "
                f"{page.total - len(page.group_names)} groups."
            )


class _GroupMembershipCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="jira_group_membership",
            display_name="Group members are readable",
            remediation=(
                f"{_GROUP_ACCESS_HINT} Scoped API token: the `read:jira-user` "
                "scope, or the granular `read:group:jira`, `read:user:jira` and "
                "`read:avatar:jira` scopes."
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        if not _sample_group_members(context, config):
            # The reads succeeded: the first groups can be empty.
            raise UnexpectedValidationError(
                "The first listed groups have no members, so Onyx cannot verify "
                "that group members are readable."
            )


class _GroupMemberEmailsCheck(_JiraCheck):
    def __init__(self) -> None:
        super().__init__(
            capability=CredentialCapability.EXTERNAL_GROUP_SYNC,
            check_id="jira_group_member_emails",
            display_name="Group members have emails",
            remediation=(
                "Make user emails visible to the token's account. "
                f"Cloud: {_CLOUD_EMAIL_HINT} Data Center: {_DC_EMAIL_HINT}"
            ),
        )

    def run(self, context: CapabilityCheckContext) -> None:
        config = self.config(context)
        try:
            members = _sample_group_members(context, config)
        except ConnectorValidationError as e:
            raise UnexpectedValidationError(
                "Onyx cannot read group members, so this check cannot run. "
                "jira_group_membership reports why."
            ) from e
        # Group sync skips app and customer accounts.
        people = [
            member
            for member in members
            if member.get("accountType") in (None, _ATLASSIAN_ACCOUNT_TYPE)
        ]
        if people and not any(member.get("emailAddress") for member in people):
            raise InsufficientPermissionsError(
                "No member of the sampled group has a visible email, so group "
                f"members cannot map to Onyx users. {_email_hint(_gateway(context))}"
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
