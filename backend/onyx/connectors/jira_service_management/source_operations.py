"""Jira Service Management gateway. Every HTTP call lives here.

A credential with an account email is Jira Cloud (basic auth, REST v3).
A credential with a token only is a Server or Data Center personal access
token (bearer auth, REST v2). Service desk reads use ``/rest/servicedeskapi``
on both.

The site URL is admin-supplied and receives the credential, so it passes the
shared SSRF checks before the first request.
"""

import threading
from collections.abc import Mapping
from typing import Any, Literal, overload
from urllib.parse import quote, urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.response import BaseHTTPResponse
from urllib3.util.retry import Retry

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.cross_connector_utils.server_wait import bound_server_wait
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    SourceApiError,
    TimedOutValidationError,
    UnreachableValidationError,
)
from onyx.connectors.jira_service_management.config import (
    JiraServiceManagementCredentialBinding,
)
from onyx.connectors.jira_service_management.keys import ISSUE_KEY as _ISSUE_KEY
from onyx.connectors.jira_service_management.models import (
    CommentPage,
    CustomerRequest,
    IssueRef,
    IssueSearchPage,
    IssueTimestamps,
    JsmUser,
    RequestPage,
    ServiceDesk,
    ServiceDeskPage,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.server.security.models import connector_ssrf_enforced
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from onyx.utils.url import SSRFException, validate_outbound_http_url

logger = setup_logger()

JIRA_USER_EMAIL_KEY: str = "jira_user_email"
JIRA_API_TOKEN_KEY: str = "jira_api_token"

_TIMEOUT_SECONDS: int = 60
_PAGE_SIZE: int = 50
# A walk still paging past this is a server that ignores the offset.
_MAX_PAGES: int = 100_000
_CLOUD_API: str = "3"
_SERVER_API: str = "2"


class _BoundedRetry(Retry):
    """Retry whose server-requested waits go through bound_server_wait."""

    def get_retry_after(self, response: BaseHTTPResponse) -> float | None:
        retry_after = super().get_retry_after(response)
        if retry_after is None:
            return None
        return bound_server_wait(retry_after, "jira_service_management")


# urllib3 honors Retry-After on 429 and backs off on 5xx.
_RETRY: Retry = _BoundedRetry(
    total=5,
    backoff_factor=1,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
)

_REQUEST_EXPAND: str = "requestType,participant,status"


class JsmApiError(SourceApiError):
    """Jira or Jira Service Management returned an error, or the retries ran out."""


def validate_base_url(base_url: str) -> None:
    """Private hosts are reachable only when an admin relaxed SSRF protection.
    Cloud metadata stays blocked either way."""
    enforced: bool = connector_ssrf_enforced(
        get_security_settings().ssrf_protection_level
    )
    try:
        validate_outbound_http_url(
            base_url,
            https_only=True,
            allow_private_network=not enforced,
            block_link_local_only=not enforced,
        )
    except (SSRFException, ValueError) as e:
        raise ConnectorValidationError(f"Invalid Jira URL '{base_url}': {e}") from e


def is_cloud_credential(credentials: Mapping[str, Any]) -> bool:
    """Cloud signs in with an account email. Data Center sends the token alone."""
    email = credentials.get(JIRA_USER_EMAIL_KEY)
    return isinstance(email, str) and bool(email.strip())


def _error_detail(response: requests.Response) -> str:
    try:
        body: Any = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(body, dict):
        messages = body.get("errorMessages") or body.get("errorMessage")
        if isinstance(messages, list) and messages:
            return "; ".join(str(message) for message in messages)[:300]
        if isinstance(messages, str) and messages:
            return messages[:300]
    return str(body)[:300]


def _is_last_page(is_last: bool | None, count: int) -> bool:
    """A page ends the walk when the server says so, or when the flag is
    missing and the page is short."""
    if is_last is True or count == 0:
        return True
    if is_last is None and count < _PAGE_SIZE:
        return True
    return False


def _issue_path(issue_key: str) -> str:
    if _ISSUE_KEY.fullmatch(issue_key) is None:
        raise ConnectorValidationError(
            "Jira returned an issue key the connector will not request."
        )
    return quote(issue_key, safe="-")


class JiraServiceManagementSourceOperations(SourceOperations):
    source = DocumentSource.JIRA_SERVICE_MANAGEMENT
    sdk_modules = ("requests",)
    config_keys = frozenset(JiraServiceManagementCredentialBinding.model_fields)

    _client_cache: tuple[requests.Session, str, bool] | None = None

    def _lock(self) -> threading.Lock:
        return vars(self).setdefault("_build_lock", threading.Lock())

    def _client(self) -> tuple[requests.Session, str, bool]:
        """The session, the site root, and whether the site is Cloud."""
        if self._client_cache is not None:
            return self._client_cache
        with self._lock():
            if self._client_cache is not None:
                return self._client_cache
            binding = JiraServiceManagementCredentialBinding.model_validate(
                self.connector_specific_config or {}
            )
            validate_base_url(binding.jira_base_url)
            credentials = self.credentials_provider.get_credentials()
            token = credentials.get(JIRA_API_TOKEN_KEY)
            if not isinstance(token, str) or not token:
                raise ConnectorMissingCredentialError("Jira Service Management")
            cloud = is_cloud_credential(credentials)
            if cloud:
                email = str(credentials[JIRA_USER_EMAIL_KEY]).strip()
                auth: tuple[str, str] | None = (email, token)
                headers = {"Accept": "application/json"}
            else:
                auth = None
                headers = {
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                }
            root = binding.jira_base_url.rstrip("/")
            session = requests.Session()
            session.auth = auth
            session.headers.update(headers)
            session.mount(root, HTTPAdapter(max_retries=_RETRY))
            self._client_cache = (session, root, cloud)
            return self._client_cache

    @overload
    def _get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        *,
        missing_ok: Literal[False] = False,
    ) -> dict[str, Any]: ...

    @overload
    def _get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        *,
        missing_ok: Literal[True],
    ) -> dict[str, Any] | None: ...

    def _get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        *,
        missing_ok: bool = False,
    ) -> dict[str, Any] | None:
        session, root, _cloud = self._client()
        url = f"{root}{path}"
        try:
            response = session.get(
                url,
                params=params,
                timeout=_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except requests.exceptions.RetryError as e:
            raise JsmApiError(
                f"Jira Service Management did not answer after retries on {path}.",
                status_code=None,
                method="GET",
                url=url,
            ) from e
        except requests.Timeout as e:
            raise TimedOutValidationError(
                "Jira Service Management did not answer in time."
            ) from e
        except requests.ConnectionError as e:
            raise UnreachableValidationError(
                "Onyx could not reach the Jira site. Check the site URL."
            ) from e
        if response.status_code == 401:
            raise CredentialInvalidError(
                "Jira rejected the account. Check the email and API token, "
                "or the personal access token on Data Center."
            )
        if response.status_code == 403:
            raise InsufficientPermissionsError(
                "The account cannot read this Jira Service Management "
                f"resource. {_error_detail(response)}"
            )
        if response.status_code == 429:
            raise RateLimitedValidationError(
                "Jira Service Management rate limited the request. Try again later."
            )
        if response.is_redirect:
            location = response.headers.get("Location", "")
            raise ConnectorValidationError(
                f"Jira redirected {path} to {urlsplit(location).netloc or location}. "
                "Check the site URL."
            )
        if response.status_code == 404 and missing_ok:
            return None
        if response.status_code == 400:
            raise ConnectorValidationError(
                f"Jira rejected the request. {_error_detail(response)}"
            )
        if not response.ok:
            raise JsmApiError(
                f"Jira Service Management request failed ({response.status_code}).",
                status_code=response.status_code,
                method="GET",
                url=url,
                body=_error_detail(response),
            )
        try:
            body = response.json()
        except ValueError as e:
            raise JsmApiError(
                "Jira Service Management returned a response that is not JSON.",
                status_code=response.status_code,
                method="GET",
                url=url,
            ) from e
        if not isinstance(body, dict):
            raise JsmApiError(
                "Jira Service Management returned an unexpected response.",
                status_code=response.status_code,
                method="GET",
                url=url,
            )
        return body

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def get_myself(self) -> JsmUser:
        """The account behind the credential."""
        _session, _root, cloud = self._client()
        version = _CLOUD_API if cloud else _SERVER_API
        return JsmUser.model_validate(self._get(f"/rest/api/{version}/myself"))

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def find_service_desk(self, *, project_key: str) -> ServiceDesk:
        """The service desk whose project key matches, across every page."""
        wanted = project_key.upper()
        start = 0
        seen: set[str] = set()
        for _page in range(_MAX_PAGES):
            payload = self._get(
                "/rest/servicedeskapi/servicedesk",
                {"start": start, "limit": _PAGE_SIZE},
            )
            if payload is None:
                break
            page = ServiceDeskPage.model_validate(payload)
            fresh = [desk for desk in page.values if desk.id not in seen]
            for desk in fresh:
                if desk.project_key.upper() == wanted:
                    return desk
            seen.update(desk.id for desk in page.values)
            if not fresh or _is_last_page(page.is_last_page, len(page.values)):
                break
            start += len(page.values)
        else:
            raise RuntimeError(
                "Jira Service Management kept paging service desks "
                f"past {_MAX_PAGES} pages."
            )
        raise ConnectorValidationError(
            f"No Jira Service Management service desk uses project {wanted}. "
            "Check the project key, and give the account the Service Desk Team role."
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def list_requests(
        self, *, service_desk_id: str, start: int = 0, limit: int = _PAGE_SIZE
    ) -> RequestPage:
        """One page of every request on the service desk, open and closed.

        ``ALL_REQUESTS`` is an agent view. A customer account only receives
        the requests that account can see.
        """
        if not service_desk_id.isdigit():
            raise ConnectorValidationError(
                "Jira returned a service desk id the connector will not request."
            )
        payload = self._get(
            "/rest/servicedeskapi/request",
            {
                "serviceDeskId": service_desk_id,
                "requestOwnership": "ALL_REQUESTS",
                "requestStatus": "ALL_REQUESTS",
                "expand": _REQUEST_EXPAND,
                "start": start,
                "limit": limit,
            },
        )
        return RequestPage.model_validate(payload)

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def get_request(self, *, issue_key: str) -> CustomerRequest | None:
        """The request for one issue, or None when the issue is not a request."""
        payload = self._get(
            f"/rest/servicedeskapi/request/{_issue_path(issue_key)}",
            {"expand": _REQUEST_EXPAND},
            missing_ok=True,
        )
        if payload is None:
            return None
        return CustomerRequest.model_validate(payload)

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def list_comments(
        self, *, issue_key: str, start: int = 0, limit: int = _PAGE_SIZE
    ) -> CommentPage:
        """One page of request comments, public and internal."""
        payload = self._get(
            f"/rest/servicedeskapi/request/{_issue_path(issue_key)}/comment",
            {"start": start, "limit": limit},
        )
        return CommentPage.model_validate(payload)

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def get_issue_timestamps(self, *, issue_key: str) -> IssueTimestamps:
        """The Jira issue's created and updated times.

        A summary or description edit changes ``updated`` without a new
        comment or a status change. The service desk request does not carry
        that time.
        """
        _session, _root, cloud = self._client()
        version = _CLOUD_API if cloud else _SERVER_API
        payload = self._get(
            f"/rest/api/{version}/issue/{_issue_path(issue_key)}",
            {"fields": "updated,created"},
        )
        fields = payload.get("fields")
        updated = fields.get("updated") if isinstance(fields, dict) else None
        if not isinstance(updated, str) or not updated:
            raise JsmApiError(
                "Jira did not return the issue updated time.",
                status_code=200,
                method="GET",
                url=None,
            )
        created = fields.get("created") if isinstance(fields, dict) else None
        return IssueTimestamps(
            updated=updated,
            created=created if isinstance(created, str) else None,
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def search_issues(
        self,
        *,
        jql: str,
        limit: int = _PAGE_SIZE,
        next_page_token: str | None = None,
        start_at: int = 0,
    ) -> IssueSearchPage:
        """One page of issues matching JQL.

        Cloud uses the token search. Server and Data Center use the offset
        search. The caller passes both cursors; the unused one is ignored.
        """
        _session, _root, cloud = self._client()
        if cloud:
            params: dict[str, str | int] = {
                "jql": jql,
                "maxResults": limit,
                "fields": "summary",
            }
            if next_page_token:
                params["nextPageToken"] = next_page_token
            payload = self._get("/rest/api/3/search/jql", params)
            token = payload.get("nextPageToken")
            next_token = token if isinstance(token, str) and token else None
            issues = payload.get("issues", [])
            if not isinstance(issues, list):
                raise JsmApiError(
                    "Jira search returned an unexpected issue list.",
                    status_code=200,
                    method="GET",
                    url=None,
                )
            # A missing next token ends the walk even if isLast is absent.
            return IssueSearchPage(
                issues=[IssueRef.model_validate(issue) for issue in issues],
                is_last=bool(payload.get("isLast")) or next_token is None,
                next_page_token=next_token,
                uses_token=True,
            )
        payload = self._get(
            "/rest/api/2/search",
            {
                "jql": jql,
                "startAt": start_at,
                "maxResults": limit,
                "fields": "summary",
            },
        )
        issues = payload.get("issues", [])
        if not isinstance(issues, list):
            raise JsmApiError(
                "Jira search returned an unexpected issue list.",
                status_code=200,
                method="GET",
                url=None,
            )
        return IssueSearchPage(
            issues=[IssueRef.model_validate(issue) for issue in issues],
            is_last=len(issues) < limit,
            uses_token=False,
        )
