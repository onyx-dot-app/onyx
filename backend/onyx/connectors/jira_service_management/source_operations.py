"""The JSM source-operations gateway.

A service desk is a Jira project, so credential handling, paging and error
translation match the Jira gateway's. This gateway adds the
``rest/servicedeskapi`` calls that describe a service desk and a request type.

Those calls need a Service Desk *agent* licence. A user with only portal access
gets an error response, so an indexing run must not fail on them: the connector
treats an error from a servicedeskapi operation as "metadata absent" and still
indexes the request through the Jira API.

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
from onyx.connectors.exceptions import SourceApiError
from onyx.connectors.jira.config import JiraCredentialBinding
from onyx.connectors.jira.models import JiraIssueIdPage
from onyx.connectors.jira.source_operations import (
    JIRA_API_TOKEN_KEY,
    JIRA_USER_EMAIL_KEY,
)
from onyx.connectors.jira.utils import JIRA_CLOUD_API_VERSION, JIRA_SERVER_API_VERSION
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_SERVICEDESK_API_PREFIX = "rest/servicedeskapi"
# https://developer.atlassian.com/cloud/jira/service-desk/rest/api-group-service-desk/
_MAX_RESULTS = 100
# https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/
_BULK_FETCH_LIMIT = 100
# The ``fast=True`` client gives a check a request timeout and no retries, so a
# slow site cannot hold it.
_FAST_TIMEOUT_SECONDS = 10
_INDEXING_TIMEOUT_SECONDS: int | None = None
_INDEXING_MAX_RETRIES = 3


def _bulk_fetch(
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
    return issues if isinstance(issues, list) else []


class JsmApiError(SourceApiError):
    """A JSM API call returned an error response, or no answer in time."""


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
    handle ``jira`` or ``requests`` exceptions."""
    try:
        yield
    except JIRAError as e:
        raise JsmApiError(
            str(e),
            status_code=getattr(e, "status_code", None),
            method=getattr(e, "request_method", None),
            url=getattr(e, "url", None),
            body=_error_text(e),
        ) from e
    except requests.HTTPError as e:
        response: requests.Response | None = e.response
        raise JsmApiError(
            str(e),
            status_code=response.status_code if response is not None else None,
            method=response.request.method if response is not None else None,
            url=response.url if response is not None else None,
            body=response.text if response is not None else None,
        ) from e
    except requests.Timeout as e:
        raise JsmApiError(
            (
                f"No answer within {_FAST_TIMEOUT_SECONDS}s"
                if fast
                else "The request timed out."
            ),
            status_code=None,
        ) from e


class JiraServiceManagementSourceOperations(SourceOperations):
    source = DocumentSource.JIRA_SERVICE_MANAGEMENT
    sdk_modules = ("jira",)
    # The gateway reads only the credential-bound fields (site URL, scoped
    # token).
    config_keys = frozenset(JiraCredentialBinding.model_fields)

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
        # Version 3 on Cloud, 2 on Server / Data Center. The servicedeskapi
        # endpoints are unversioned, so this only steers the Jira calls.
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
                client._get_url(f"{_SERVICEDESK_API_PREFIX}/{path}"),
                params=dict(params),
            )
            response.raise_for_status()
            return response.json()

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
        untested=(
            "jsm_service_desk proves the project read through servicedeskapi, "
            "which is the call this connector depends on. A plain Jira project "
            "read adds nothing a check could distinguish."
        ),
    )
    def get_project(self, *, project_key: str, fast: bool = False) -> dict[str, Any]:
        """Returns one project. Raises ``JsmApiError`` (404) when it does not
        exist or the credential cannot browse it."""
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
        URL. Raises ``JsmApiError`` when the project is not a service desk, or
        the credential is not a Service Desk agent."""
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
    # Jira operations the inherited indexing path calls. A service desk is a
    # Jira project and a request is a Jira issue, so these are the Jira
    # gateway's operations with the same names and shapes. They live here
    # because a gateway may not inherit another gateway.
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
                raw: Any = _bulk_fetch(client, list(batch), fields)
            raw_issues.extend(raw)
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
