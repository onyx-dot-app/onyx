"""The JSM source-operations gateway.

A service desk is a Jira project, so credential handling and error translation
match the Jira gateway's. This gateway adds the ``rest/servicedeskapi`` calls
that describe a service desk and a request type.

**URL construction.** ``servicedeskapi`` is *unversioned*: it lives at
``{server}/rest/servicedeskapi/...``, not under ``/rest/api/3/``. The SDK's
``JIRA._get_url`` / ``_get_json`` default to ``JIRA_BASE_URL``, which is
``{server}/rest/{rest_path}/{rest_api_version}/{path}``, so a relative
``servicedeskapi`` path would resolve to
``/rest/rest/api/3/rest/servicedeskapi/...``. Every call here therefore builds
an absolute URL from the client's server, and passes it to
``client._session`` directly.

**Licence.** The servicedeskapi needs a Service Desk *agent* licence. A user
with only portal access gets an error response, so an indexing run must not
fail on it: the connector treats an error from a servicedeskapi operation as
"metadata absent" and still indexes the request through the Jira API.

The gateway subclasses ``SourceOperations`` directly, as every gateway must.
Shared logic lives in the module-level helpers below.
"""

import contextlib
import threading
from collections.abc import Iterator, Mapping
from typing import Any

import requests
from jira import JIRA
from jira.exceptions import JIRAError
from more_itertools import chunked

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.cross_connector_utils.miscellaneous_utils import scoped_url
from onyx.connectors.jira.config import (
    JiraConnectorConfig,
    JiraCredentialBinding,
)
from onyx.connectors.jira.models import JiraGroupPage, JiraIssueIdPage
from onyx.connectors.jira.source_operations import (
    JIRA_API_TOKEN_KEY,
    JIRA_USER_EMAIL_KEY,
    JiraApiError,
    JiraTimeoutError,
)
from onyx.connectors.jira.utils import JIRA_CLOUD_API_VERSION, JIRA_SERVER_API_VERSION
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Unversioned on purpose: see the module docstring.
_SERVICEDESK_API = "rest/servicedeskapi"
_MAX_RESULTS = 100
_BULK_FETCH_LIMIT = 100
_GROUP_PICKER_MAX_RESULTS = 9999
_FAST_TIMEOUT_SECONDS = 10
_INDEXING_TIMEOUT_SECONDS: int | None = None
_INDEXING_MAX_RETRIES = 3


class JsmApiError(JiraApiError):
    """A JSM API call returned an error response, or no answer in time.

    Subclasses ``JiraApiError`` so the inherited Jira validation and error
    handling classify a JSM failure exactly as it classifies a Jira one
    (401 credential expired, 403 insufficient permissions, 429 rate limited).
    """


class JsmTimeoutError(JsmApiError, JiraTimeoutError):
    """A ``fast=True`` call got no answer within its request timeout."""


def _error_text(error: Exception) -> str | None:
    if isinstance(error, requests.HTTPError) and error.response is not None:
        try:
            return error.response.text
        except Exception:
            return None
    return None


@contextlib.contextmanager
def _translate_errors(*, fast: bool = False) -> Iterator[None]:
    """Turn every client exception into a ``JsmApiError``, so callers never
    handle ``jira`` or ``requests`` exceptions.

    ``str(JIRAError)`` prints the request and the response headers, which carry
    the Basic credential and the session cookie. The message here is built from
    the status and the URL only; the response body (which holds Jira's own
    error text and never the credential) is the ``body``.
    """
    try:
        yield
    except JIRAError as e:
        status: int | None = getattr(e, "status_code", None)
        url: str | None = getattr(e, "url", None)
        method: str | None = getattr(e, "request_method", None)
        # ``e.text`` is the response body; never fall back to ``str(e)``.
        body: str | None = getattr(e, "text", None)
        raise JsmApiError(
            f"Jira answered {method or 'the request'} {url or ''} with HTTP "
            f"{status if status is not None else 'no status'}.".strip(),
            status_code=status,
            method=method,
            url=url,
            body=body,
        ) from e
    except requests.HTTPError as e:
        response: requests.Response | None = e.response
        raise JsmApiError(
            str(e),
            status_code=response.status_code if response is not None else None,
            method=response.request.method if response is not None else None,
            url=response.url if response is not None else None,
            body=_error_text(e),
        ) from e
    except requests.ConnectionError as e:
        raise JsmApiError(
            "Could not connect to the Jira site.",
            status_code=None,
            url=getattr(getattr(e, "request", None), "url", None),
        ) from e
    except requests.Timeout as e:
        raise JsmTimeoutError(
            (
                f"No answer within {_FAST_TIMEOUT_SECONDS}s."
                if fast
                else "The request timed out."
            ),
            status_code=None,
        ) from e


def _servicedesk_url(client: JIRA, path: str) -> str:
    """The absolute servicedeskapi URL for ``path``, on the client's server.

    ``JIRA._get_url`` would add ``/rest/api/<version>/``, which this API does
    not use.
    """
    server: Any = client._options["server"]
    return f"{str(server).rstrip('/')}/{_SERVICEDESK_API}/{path.lstrip('/')}"


def _fetch_bulk(
    client: JIRA, issue_ids: list[str], fields: str | None
) -> list[dict[str, Any]]:
    """Raw POST to the bulkfetch endpoint. Returns the raw issue dicts."""
    response: requests.Response = client._session.post(  # ty: ignore[unresolved-attribute]
        client._get_url("issue/bulkfetch"),
        json={
            "issueIdsOrKeys": issue_ids,
            "fields": fields.split(",") if fields else ["*all"],
        },
    )
    response.raise_for_status()
    body: Any = response.json()
    issues: Any = body.get("issues") if isinstance(body, dict) else None
    if not isinstance(issues, list):
        # Returning [] here would silently drop a whole batch from the index.
        raise JsmApiError(
            "Jira bulkfetch answered without an issues list.",
            status_code=response.status_code,
            method=response.request.method,
            url=response.url,
            body=response.text[:500],
        )
    return issues


def _fetch_bulk_batched(
    client: JIRA, issue_ids: list[str], fields: str | None
) -> list[dict[str, Any]]:
    """One batch. A JSON decode failure (a truncated all-fields response) is
    bisected until it succeeds or reaches a single issue, as the Jira
    gateway does."""
    try:
        return _fetch_bulk(client, issue_ids, fields)
    except requests.exceptions.JSONDecodeError:
        if len(issue_ids) <= 1:
            logger.exception(
                "Jira bulk-fetch response for issue(s) %s could not be decoded "
                "as JSON (response too large or truncated).",
                issue_ids,
            )
            raise
        mid: int = len(issue_ids) // 2
        left = _fetch_bulk_batched(client, issue_ids[:mid], fields)
        right = _fetch_bulk_batched(client, issue_ids[mid:], fields)
        return left + right


class JiraServiceManagementSourceOperations(SourceOperations):
    source = DocumentSource.JIRA_SERVICE_MANAGEMENT
    sdk_modules = ("jira",)
    # The gateway reads only the credential-bound fields (site URL, scoped
    # token).
    config_keys = frozenset(
        JiraConnectorConfig.credential_binding_class().model_fields  # ty: ignore[unresolved-attribute]
    )

    _cached_client: JIRA | None = None
    _cached_fast_client: JIRA | None = None

    def _client_build_lock(self) -> threading.Lock:
        """This gateway's lock against duplicate builds; a build makes remote
        calls (serverInfo, and tenant_info for scoped tokens)."""
        return vars(self).setdefault("_build_lock", threading.Lock())

    def _binding(self) -> JiraCredentialBinding:
        return JiraCredentialBinding.model_validate(
            self.connector_specific_config or {}
        )

    def _credentials(self) -> dict[str, Any]:
        return self.credentials_provider.get_credentials()

    def _is_cloud(self) -> bool:
        """True when the credential uses the Cloud APIs."""
        return JIRA_USER_EMAIL_KEY in self._credentials()

    def _api_url(self) -> str:
        """The URL the client calls. Scoped tokens go through
        ``api.atlassian.com``."""
        binding: JiraCredentialBinding = self._binding()
        jira_base: str = binding.jira_base_url.rstrip("/")
        if not binding.scoped_token:
            return jira_base
        try:
            return scoped_url(jira_base, "jira")
        except KeyError as e:
            raise JsmApiError(
                f"{jira_base}/_edge/tenant_info returned no Atlassian cloud id.",
                status_code=None,
            ) from e

    def _build_client(self, api_url: str, *, fast: bool) -> JIRA:
        credentials: dict[str, Any] = self._credentials()
        api_token: str = credentials[JIRA_API_TOKEN_KEY]
        options: dict[str, str | bool | Any] = {
            "rest_api_version": (
                JIRA_CLOUD_API_VERSION
                if JIRA_USER_EMAIL_KEY in credentials
                else JIRA_SERVER_API_VERSION
            )
        }
        timeout: int | None = (
            _FAST_TIMEOUT_SECONDS if fast else _INDEXING_TIMEOUT_SECONDS
        )
        max_retries: int = 0 if fast else _INDEXING_MAX_RETRIES
        if JIRA_USER_EMAIL_KEY in credentials:
            return JIRA(
                basic_auth=(credentials[JIRA_USER_EMAIL_KEY], api_token),
                server=api_url,
                options=options,
                timeout=timeout,
                max_retries=max_retries,
            )
        return JIRA(
            token_auth=api_token,
            server=api_url,
            options=options,
            timeout=timeout,
            max_retries=max_retries,
        )

    def _client(self, *, fast: bool = False) -> JIRA:
        cached: JIRA | None = self._cached_fast_client if fast else self._cached_client
        if cached is not None:
            return cached
        with self._client_build_lock():
            cached = self._cached_fast_client if fast else self._cached_client
            if cached is None:
                api_url: str = self._api_url()
                with _translate_errors(fast=fast):
                    cached = self._build_client(api_url, fast=fast)
                if fast:
                    self._cached_fast_client = cached
                else:
                    self._cached_client = cached
        return cached

    def _get(self, path: str, params: Mapping[str, Any], *, fast: bool) -> Any:
        """One servicedeskapi GET, unwrapped to JSON."""
        client: JIRA = self._client(fast=fast)
        with _translate_errors(fast=fast):
            response: requests.Response = client._session.get(  # ty: ignore[unresolved-attribute]
                _servicedesk_url(client, path),
                params=dict(params),
            )
            response.raise_for_status()
            return response.json()

    # ------------------------------------------------------------------
    # Service desk operations.
    # ------------------------------------------------------------------

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_myself(self, *, fast: bool = False) -> dict[str, Any]:
        """Returns the user the credential acts as (``myself``)."""
        with _translate_errors(fast=fast):
            return self._client(fast=fast).myself()

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def get_project(self, *, project_key: str, fast: bool = False) -> dict[str, Any]:
        """Returns one Jira project."""
        with _translate_errors(fast=fast):
            return self._client(fast=fast).project(project_key).raw

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def get_service_desk(
        self, *, project_key: str, fast: bool = False
    ) -> dict[str, Any]:
        """Returns the service desk of this project: its id, name and portal
        URL. Raises ``JsmApiError`` (404) when the project is not a service
        desk, or when the credential is not a Service Desk agent."""
        body: Any = self._get(
            "servicedesk", {"projectKey": project_key, "limit": 1}, fast=fast
        )
        values: Any = body.get("values") if isinstance(body, dict) else None
        if not isinstance(values, list) or not values:
            raise JsmApiError(
                f"{project_key} is not a Jira Service Management project.",
                status_code=404,
            )
        desk: Any = values[0]
        return desk if isinstance(desk, dict) else {}

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=(
            "Runs once per request that carries a request-type field, so a check "
            "needs a site whose requests have one. jsm_metadata proves the "
            "servicedeskapi path it shares."
        ),
    )
    def get_request_type(
        self, *, service_desk_id: str, request_type_id: str, fast: bool = False
    ) -> dict[str, Any]:
        """Returns the request type of a request: its name and its group."""
        body: Any = self._get(
            f"servicedesk/{service_desk_id}/requesttype/{request_type_id}",
            {},
            fast=fast,
        )
        return body if isinstance(body, dict) else {}

    # ------------------------------------------------------------------
    # Jira operations the inherited indexing and permission-sync paths call.
    # A service desk is a Jira project and a request is a Jira issue, so these
    # are the Jira gateway's operations with the same names and shapes. They
    # live here because a gateway may not inherit another gateway.
    # ------------------------------------------------------------------

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def search_issue_ids(
        self,
        *,
        jql: str,
        next_page_token: str | None = None,
        max_results: int = _MAX_RESULTS,
        fast: bool = False,
    ) -> JiraIssueIdPage:
        """Cloud only: one page of issue ids from the enhanced JQL search
        (``search/jql``)."""
        client: JIRA = self._client(fast=fast)
        with _translate_errors(fast=fast):
            response: requests.Response = client._session.get(  # ty: ignore[unresolved-attribute]
                client._get_url("search/jql"),
                params={
                    "jql": jql,
                    "maxResults": max_results,
                    "nextPageToken": next_page_token,
                    "fields": "id",
                },
            )
            response.raise_for_status()
            body: Any = response.json()
        issues: Any = body.get("issues") if isinstance(body, dict) else None
        return JiraIssueIdPage(
            issue_ids=[
                str(issue["id"]) for issue in (issues or []) if isinstance(issue, dict)
            ],
            next_page_token=body.get("nextPageToken")
            if isinstance(body, dict)
            else None,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def bulk_fetch_issues(
        self, *, issue_ids: list[str], fields: str | None = None, fast: bool = False
    ) -> list[dict[str, Any]]:
        """Cloud only: the raw issues for these ids (``issue/bulkfetch``), in
        batches of at most 100."""
        client: JIRA = self._client(fast=fast)
        raw_issues: list[dict[str, Any]] = []
        for batch in chunked(issue_ids, _BULK_FETCH_LIMIT):
            with _translate_errors(fast=fast):
                raw_issues.extend(_fetch_bulk_batched(client, list(batch), fields))
        return raw_issues

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=(
            "Server / Data Center only. The Cloud search that jsm_request_read "
            "proves (search_issue_ids + bulk_fetch_issues) is the path a Cloud "
            "service desk uses, and JSM is a Cloud product."
        ),
    )
    def search_issues(
        self,
        *,
        jql: str,
        start_at: int,
        max_results: int,
        fields: str | None = None,
        fast: bool = False,
    ) -> list[dict[str, Any]]:
        """Server / Data Center only: one offset page of raw issues from the v2
        search endpoint."""
        client: JIRA = self._client(fast=fast)
        with _translate_errors(fast=fast):
            if fields is None:
                found = client.search_issues(
                    jql, startAt=start_at, maxResults=max_results
                )
            else:
                found = client.search_issues(
                    jql, startAt=start_at, maxResults=max_results, fields=fields
                )
        return [issue.raw for issue in found]

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "JSM has no separate perm-sync check registration; it inherits the "
            "Jira permission model. These operations run during a perm-synced "
            "indexing run of this connector, and "
            "test_jsm_gateway_serves_the_inherited_permission_path asserts the "
            "inherited permission read reaches them."
        ),
    )
    def get_project_permission_scheme(
        self, *, project_key: str, fast: bool = False
    ) -> dict[str, Any]:
        """Returns the permission scheme of a project with its grants and
        expanded users."""
        with _translate_errors(fast=fast):
            # The SDK resource requests ``expand=user``.
            return (
                self._client(fast=fast)
                .project_permissionscheme(project=project_key)
                .raw
            )

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "JSM has no separate perm-sync check registration; it inherits the "
            "Jira permission model. These operations run during a perm-synced "
            "indexing run of this connector, and "
            "test_jsm_gateway_serves_the_inherited_permission_path asserts the "
            "inherited permission read reaches them."
        ),
    )
    def get_project_role(
        self, *, project_key: str, role_id: str, fast: bool = False
    ) -> dict[str, Any]:
        """Returns a project role with its actors (users and groups)."""
        with _translate_errors(fast=fast):
            return (
                self._client(fast=fast)
                .project_role(project=project_key, id=role_id)
                .raw
            )

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "JSM has no separate perm-sync check registration; it inherits the "
            "Jira permission model. These operations run during a perm-synced "
            "indexing run of this connector, and "
            "test_jsm_gateway_serves_the_inherited_permission_path asserts the "
            "inherited permission read reaches them."
        ),
    )
    def get_user(self, *, user_id: str, fast: bool = False) -> dict[str, Any]:
        """Returns a user: ``user_id`` is the accountId on Cloud and the
        username on Server / Data Center."""
        with _translate_errors(fast=fast):
            return self._client(fast=fast).user(id=user_id).raw

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "JSM has no separate perm-sync check registration; it inherits the "
            "Jira permission model. These operations run during a perm-synced "
            "indexing run of this connector, and "
            "test_jsm_gateway_serves_the_inherited_permission_path asserts the "
            "inherited permission read reaches them."
        ),
    )
    def list_groups(self, *, fast: bool = False) -> JiraGroupPage:
        """Returns the group names from ``groups/picker``, sorted."""
        with _translate_errors(fast=fast):
            response: dict[str, Any] = self._client(fast=fast)._get_json(
                "groups/picker", params={"maxResults": _GROUP_PICKER_MAX_RESULTS}
            )
        return JiraGroupPage(
            group_names=sorted(group["name"] for group in response["groups"]),
            total=response.get("total"),
        )

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "JSM has no separate perm-sync check registration; it inherits the "
            "Jira permission model. These operations run during a perm-synced "
            "indexing run of this connector, and "
            "test_jsm_gateway_serves_the_inherited_permission_path asserts the "
            "inherited permission read reaches them."
        ),
    )
    def get_group_members_page(
        self,
        *,
        group_name: str,
        start_at: int,
        max_results: int,
        fast: bool = False,
    ) -> dict[str, Any]:
        """Returns one page of the active members of a group
        (``group/member``)."""
        with _translate_errors(fast=fast):
            return self._client(fast=fast)._get_json(
                "group/member",
                params={
                    "groupname": group_name,
                    "includeInactiveUsers": "false",
                    "startAt": start_at,
                    "maxResults": max_results,
                },
            )
