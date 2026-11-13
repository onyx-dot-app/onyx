"""The Jira Service Management source-operations gateway.

JSM tickets are Jira issues, so issue search goes through the Jira gateway
(``JiraSourceOperations``). This gateway owns the Service Desk REST API
(``/rest/servicedeskapi/...``): service desks, request details, request
comments with their visibility flag, and SLAs.

Like the Jira gateway, a credential with an account email is a Cloud
credential (basic auth), and one with a token only is a Server / Data Center
personal access token (bearer auth). A scoped API token reaches Cloud through
``api.atlassian.com``. Operations return raw JSON and raise ``JiraApiError``
for an error response, so callers never handle ``jira`` SDK exceptions.
"""

import threading
from typing import Any

import requests
from jira import JIRA

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.cross_connector_utils.miscellaneous_utils import scoped_url
from onyx.connectors.jira.config import JiraCredentialBinding
from onyx.connectors.jira.source_operations import (
    JIRA_API_TOKEN_KEY,
    JIRA_USER_EMAIL_KEY,
    JiraApiError,
    JiraCloudIdError,
    _translate_errors,
    is_cloud_credential,
    rest_api_version,
)
from onyx.connectors.jira_service_management.models import (
    JsmComment,
    JsmRequest,
    JsmServiceDesk,
    JsmSla,
)
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)

# Connect and read timeout of each request of the ``fast=True`` client.
_FAST_TIMEOUT_SECONDS = 10
# The SDK's defaults, which indexing keeps: no timeout, 3 retries.
_INDEXING_TIMEOUT_SECONDS: int | None = None
_INDEXING_MAX_RETRIES = 3

# The servicedesk comment listing pages by start/limit.
_COMMENT_PAGE_SIZE = 100
_MAX_COMMENT_PAGES = 1000


def _build_client(credentials: dict[str, Any], api_url: str, *, fast: bool) -> JIRA:
    api_token: str = credentials[JIRA_API_TOKEN_KEY]
    options: dict[str, str | bool | Any] = {
        "rest_api_version": rest_api_version(credentials)
    }
    # The SDK retries a connection error, 429 and 503 with sleeps of up to
    # a minute; the fast client raises at once.
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


class JiraServiceManagementSourceOperations(SourceOperations):
    source = DocumentSource.JIRA_SERVICE_MANAGEMENT
    sdk_modules = ("jira",)
    # The gateway reads only the credential-bound fields (site URL, scoped
    # token), which are the Jira binding's fields.
    config_keys = frozenset(JiraCredentialBinding.model_fields)

    _cached_client: JIRA | None = None
    _cached_fast_client: JIRA | None = None

    def _client_build_lock(self) -> threading.Lock:
        """This gateway's lock against duplicate builds; a build makes remote
        calls (serverInfo, and tenant_info for scoped tokens)."""
        return vars(self).setdefault("_build_lock", threading.Lock())

    def _credentials(self) -> dict[str, Any]:
        return self.credentials_provider.get_credentials()

    def _api_url(self) -> str:
        """The URL the client calls. Scoped tokens go through
        ``api.atlassian.com``; resolving its cloud id (``tenant_info``) raises
        ``requests.HTTPError`` on an error response, ``ValueError`` on an
        answer that is not JSON, and ``JiraCloudIdError`` when the JSON holds
        no cloud id."""
        binding = JiraCredentialBinding.model_validate(
            self.connector_specific_config or {}
        )
        jira_base: str = binding.jira_base_url.rstrip("/")
        if not binding.scoped_token:
            return jira_base
        try:
            return scoped_url(jira_base, "jira")
        except KeyError as e:
            raise JiraCloudIdError(
                f"{jira_base}/_edge/tenant_info returned no Atlassian cloud id."
            ) from e

    def _client(self, *, fast: bool = False) -> JIRA:
        cached: JIRA | None = self._cached_fast_client if fast else self._cached_client
        if cached is not None:
            return cached
        with self._client_build_lock():
            cached = self._cached_fast_client if fast else self._cached_client
            if cached is None:
                api_url: str = self._api_url()
                with _translate_errors(fast=fast):
                    cached = _build_client(
                        self._credentials(), api_url, fast=fast
                    )
                if fast:
                    self._cached_fast_client = cached
                else:
                    self._cached_client = cached
        return cached

    def _servicedesk_get(
        self, path: str, params: dict[str, Any] | None = None, *, fast: bool = False
    ) -> Any:
        """One GET on the Service Desk REST API (``/rest/servicedeskapi``),
        which lives outside the versioned ``/rest/api/...`` tree the SDK's
        ``_get_url`` builds."""
        client: JIRA = self._client(fast=fast)
        url: str = f"{self._api_url()}/rest/servicedeskapi/{path}"
        with _translate_errors(fast=fast):
            response: requests.Response = client._session.get(  # ty: ignore[unresolved-attribute]
                url, params=params
            )
            response.raise_for_status()
            return response.json()

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def list_service_desks(self, *, fast: bool = False) -> list[JsmServiceDesk]:
        """The service desks the credential can see (``servicedesk``)."""
        payload: Any = self._servicedesk_get("servicedesk", fast=fast)
        values: Any = payload.get("values", []) if isinstance(payload, dict) else []
        desks: list[JsmServiceDesk] = []
        for value in values:
            if not isinstance(value, dict):
                continue
            project_key: Any = value.get("projectKey")
            desk_id: Any = value.get("id")
            if not isinstance(project_key, str) or not isinstance(desk_id, str):
                continue
            desks.append(
                JsmServiceDesk(
                    id=desk_id,
                    project_key=project_key,
                    project_name=value.get("projectName")
                    if isinstance(value.get("projectName"), str)
                    else None,
                )
            )
        return desks

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def search_issue_keys(
        self, *, project_key: str, max_results: int = 1, fast: bool = False
    ) -> list[str]:
        """Keys of up to ``max_results`` issues in a project, via the Jira JQL
        search (enhanced search on Cloud, the v2 search on Server / Data
        Center). Used to probe request reads on one real ticket."""
        client: JIRA = self._client(fast=fast)
        jql: str = f'project = "{project_key}"'
        if is_cloud_credential(self._credentials()):
            path: str = "search/jql"
            params: dict[str, Any] = {
                "jql": jql,
                "maxResults": max_results,
                "fields": "key",
            }
        else:
            path = "search"
            params = {
                "jql": jql,
                "maxResults": max_results,
                "fields": "key",
                "startAt": 0,
            }
        with _translate_errors(fast=fast):
            response: requests.Response = client._session.get(  # ty: ignore[unresolved-attribute]
                client._get_url(path), params=params  # ty: ignore[unresolved-attribute]
            )
            response.raise_for_status()
            payload: Any = response.json()
        issues: Any = payload.get("issues", []) if isinstance(payload, dict) else []
        if not isinstance(issues, list):
            return []
        return [
            key
            for issue in issues
            if isinstance(issue, dict)
            and isinstance((key := issue.get("key")), str)
        ]

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def get_request(self, *, issue_key: str, fast: bool = False) -> JsmRequest:
        """The service desk request of a Jira issue
        (``request/{issueIdOrKey}``). Raises ``JiraApiError`` (404) when the
        issue is not a request, e.g. the project is not a service desk."""
        payload: Any = self._servicedesk_get(
            f"request/{issue_key}", fast=fast
        )
        if not isinstance(payload, dict):
            raise JiraApiError(
                f"Unexpected servicedesk response for request {issue_key}"
            )
        return JsmRequest.from_raw(payload)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def get_request_comments(
        self, *, issue_key: str, fast: bool = False
    ) -> list[JsmComment]:
        """Every comment of a request (``request/{issueIdOrKey}/comment``),
        each with its ``public`` visibility flag."""
        comments: list[JsmComment] = []
        start = 0
        for _ in range(_MAX_COMMENT_PAGES):
            payload: Any = self._servicedesk_get(
                f"request/{issue_key}/comment",
                params={"start": start, "limit": _COMMENT_PAGE_SIZE},
                fast=fast,
            )
            if not isinstance(payload, dict):
                break
            values: Any = payload.get("values", [])
            if not isinstance(values, list) or not values:
                break
            comments.extend(
                JsmComment.from_raw(value)
                for value in values
                if isinstance(value, dict)
            )
            start += len(values)
            # Cloud answers ``isLastPage``; Server / Data Center only ``size``.
            if payload.get("isLastPage", len(values) < _COMMENT_PAGE_SIZE):
                break
        return comments

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def get_request_slas(self, *, issue_key: str, fast: bool = False) -> list[JsmSla]:
        """The SLA metrics of a request (``request/{issueIdOrKey}/sla``)."""
        payload: Any = self._servicedesk_get(
            f"request/{issue_key}/sla", fast=fast
        )
        values: Any = payload.get("values", []) if isinstance(payload, dict) else []
        if not isinstance(values, list):
            return []
        return [
            JsmSla.from_raw(value) for value in values if isinstance(value, dict)
        ]
