"""The Jira source-operations gateway: every Jira API call goes through here.

A credential with an account email is a Cloud credential (basic auth, REST v3).
A credential with a token only is a Server / Data Center personal access token
(bearer auth, REST v2). A scoped API token reaches Cloud through
``api.atlassian.com``.

Operations return the raw JSON of the Jira API. They raise ``JiraApiError`` for
an error response, so callers never handle ``jira`` SDK exceptions.
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
from onyx.connectors.jira.config import JiraCredentialBinding
from onyx.connectors.jira.models import JiraGroupPage, JiraIssueIdPage
from onyx.connectors.jira.utils import JIRA_CLOUD_API_VERSION, JIRA_SERVER_API_VERSION
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

JIRA_USER_EMAIL_KEY = "jira_user_email"
JIRA_API_TOKEN_KEY = "jira_api_token"

_MAX_RESULTS_FETCH_IDS = 5000
# https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issues/
_JIRA_BULK_FETCH_LIMIT = 100
_GROUP_PICKER_MAX_RESULTS = 9999
_UNTESTED = "Capability checks land in a follow-up PR."


class JiraApiError(Exception):
    """A Jira API call returned an error response.

    ``status_code`` is None when the error has no HTTP status. ``text`` is the
    response body, None when there is none.
    """

    def __init__(
        self, message: str, *, status_code: int | None, text: str | None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.text = text


def rest_api_version(credentials: Mapping[str, Any]) -> str:
    """The REST API version a credential uses: Cloud with an account email,
    Server / Data Center without one."""
    if JIRA_USER_EMAIL_KEY in credentials:
        return JIRA_CLOUD_API_VERSION
    return JIRA_SERVER_API_VERSION


def is_cloud_credential(credentials: Mapping[str, Any]) -> bool:
    """True when the credential uses the Cloud APIs (enhanced search, bulk
    fetch, account ids)."""
    return rest_api_version(credentials) == JIRA_CLOUD_API_VERSION


def _error_text(error: Exception) -> str | None:
    if isinstance(error, JIRAError):
        text: Any = error.text
        return text if isinstance(text, str) or text is None else str(text)
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return error.response.text
    return None


@contextlib.contextmanager
def _translate_errors() -> Iterator[None]:
    """Raises ``JiraApiError`` for SDK and HTTP error responses."""
    try:
        yield
    except JIRAError as e:
        raise JiraApiError(
            str(e), status_code=e.status_code, text=_error_text(e)
        ) from e
    except requests.HTTPError as e:
        raise JiraApiError(
            str(e),
            status_code=e.response.status_code if e.response is not None else None,
            text=_error_text(e),
        ) from e


def _bulk_fetch_request(
    client: JIRA, issue_ids: list[str], fields: str | None
) -> list[dict[str, Any]]:
    """Raw POST to the bulkfetch endpoint. Returns the list of raw issue dicts."""
    payload: dict[str, Any] = {
        "issueIdsOrKeys": issue_ids,
        "fields": fields.split(",") if fields else ["*all"],
    }
    resp: requests.Response = client._session.post(  # ty: ignore[unresolved-attribute]
        client._get_url("issue/bulkfetch"), json=payload
    )
    return resp.json()["issues"]


def _bulk_fetch_batch(
    client: JIRA, issue_ids: list[str], fields: str | None
) -> list[dict[str, Any]]:
    """Fetches one batch (at most ``_JIRA_BULK_FETCH_LIMIT`` issues). On a
    JSONDecodeError, bisects until it succeeds or reaches size 1."""
    try:
        return _bulk_fetch_request(client, issue_ids, fields)
    except requests.exceptions.JSONDecodeError:
        if len(issue_ids) <= 1:
            logger.exception(
                "Jira bulk-fetch response for issue(s) %s could not be decoded as JSON (response too large or truncated).",
                issue_ids,
            )
            raise

        mid: int = len(issue_ids) // 2
        logger.warning(
            "Jira bulk-fetch JSON decode failed for batch of %s issues. Splitting into sub-batches of %s and %s.",
            len(issue_ids),
            mid,
            len(issue_ids) - mid,
        )
        left: list[dict[str, Any]] = _bulk_fetch_batch(client, issue_ids[:mid], fields)
        right: list[dict[str, Any]] = _bulk_fetch_batch(client, issue_ids[mid:], fields)
        return left + right


class JiraSourceOperations(SourceOperations):
    source = DocumentSource.JIRA
    sdk_modules = ("jira",)
    # The gateway reads only the credential-bound fields (site URL, scoped
    # token).
    config_keys = frozenset(JiraCredentialBinding.model_fields)

    _cached_client: JIRA | None = None

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
        return is_cloud_credential(self._credentials())

    def _api_url(self) -> str:
        """The URL the client calls. Scoped tokens go through
        ``api.atlassian.com``; resolving its cloud id (``tenant_info``) raises
        ``requests.HTTPError`` on failure."""
        binding: JiraCredentialBinding = self._binding()
        jira_base: str = binding.jira_base_url.rstrip("/")
        return scoped_url(jira_base, "jira") if binding.scoped_token else jira_base

    def _build_client(self, api_url: str) -> JIRA:
        credentials: dict[str, Any] = self._credentials()
        api_token: str = credentials[JIRA_API_TOKEN_KEY]
        options: dict[str, str | bool | Any] = {
            "rest_api_version": rest_api_version(credentials)
        }
        if JIRA_USER_EMAIL_KEY in credentials:
            return JIRA(
                basic_auth=(credentials[JIRA_USER_EMAIL_KEY], api_token),
                server=api_url,
                options=options,
            )
        return JIRA(token_auth=api_token, server=api_url, options=options)

    def _client(self) -> JIRA:
        if self._cached_client is not None:
            return self._cached_client
        with self._client_build_lock():
            if self._cached_client is None:
                api_url: str = self._api_url()
                with _translate_errors():
                    self._cached_client = self._build_client(api_url)
        return self._cached_client

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_myself(self) -> dict[str, Any]:
        """Returns the user the credential acts as (``myself``)."""
        with _translate_errors():
            return self._client().myself()

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_projects(self) -> list[dict[str, Any]]:
        """Returns the projects the credential can browse."""
        with _translate_errors():
            return [project.raw for project in self._client().projects()]

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=_UNTESTED,
    )
    def get_project(self, *, project_key: str) -> dict[str, Any]:
        """Returns one project. Raises ``JiraApiError`` (404) when it does not
        exist or the credential cannot browse it."""
        with _translate_errors():
            return self._client().project(project_key).raw

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=_UNTESTED,
    )
    def search_issue_ids(
        self, *, jql: str, next_page_token: str | None = None
    ) -> JiraIssueIdPage:
        """Cloud only: one page of issue ids from the enhanced JQL search
        (``search/jql``). The SDK does not support this endpoint."""
        # https://community.atlassian.com/forums/Jira-articles/
        # Avoiding-Pitfalls-A-Guide-to-Smooth-Migration-to-Enhanced-JQL/ba-p/2985433
        client: JIRA = self._client()
        params: dict[str, str | int | None] = {
            "jql": jql,
            "maxResults": _MAX_RESULTS_FETCH_IDS,
            "nextPageToken": next_page_token,
            "fields": "id",
        }
        with _translate_errors():
            response: requests.Response = client._session.get(  # ty: ignore[unresolved-attribute]
                client._get_url("search/jql"), params=params
            )
            response.raise_for_status()
            response_json: dict[str, Any] = response.json()
        return JiraIssueIdPage(
            issue_ids=[str(issue["id"]) for issue in response_json["issues"]],
            next_page_token=response_json.get("nextPageToken"),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=_UNTESTED,
    )
    def bulk_fetch_issues(
        self, *, issue_ids: list[str], fields: str | None = None
    ) -> list[dict[str, Any]]:
        """Cloud only: the raw issues for these ids (``issue/bulkfetch``), in
        batches of at most 100. ``fields`` is a comma-separated list; None
        fetches all fields."""
        client: JIRA = self._client()
        raw_issues: list[dict[str, Any]] = []
        for batch in chunked(issue_ids, _JIRA_BULK_FETCH_LIMIT):
            try:
                with _translate_errors():
                    raw_issues.extend(_bulk_fetch_batch(client, list(batch), fields))
            except Exception as e:
                logger.error("Error fetching issues: %s", e)
                raise
        return raw_issues

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=_UNTESTED,
    )
    def search_issues(
        self,
        *,
        jql: str,
        start_at: int,
        max_results: int,
        fields: str | None = None,
    ) -> list[dict[str, Any]]:
        """Server / Data Center only: one offset page of raw issues from the v2
        JQL search. Cloud removed this API."""
        logger.debug(
            "Fetching Jira issues with JQL: %s, starting at %s, max results: %s",
            jql,
            start_at,
            max_results,
        )
        with _translate_errors():
            issues: Any = self._client().search_issues(
                jql_str=jql,
                startAt=start_at,
                maxResults=max_results,
                fields=fields,
            )
        raw_issues: list[dict[str, Any]] = []
        for issue in issues:
            if not isinstance(issue.raw, dict):
                raise RuntimeError(f"Found Jira object not of type Issue: {issue}")
            raw_issues.append(issue.raw)
        return raw_issues

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_project_permission_scheme(self, *, project_key: str) -> dict[str, Any]:
        """Returns the permission scheme of a project with its grants and
        expanded users. Needs the Administer Projects permission on the
        project, or Administer Jira."""
        with _translate_errors():
            # The SDK resource requests ``expand=user``.
            return self._client().project_permissionscheme(project=project_key).raw

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_project_role(self, *, project_key: str, role_id: str) -> dict[str, Any]:
        """Returns a project role with its actors (users and groups)."""
        with _translate_errors():
            return self._client().project_role(project=project_key, id=role_id).raw

    @source_operation(
        capabilities={CredentialCapability.DOC_PERMISSION_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_user(self, *, user_id: str) -> dict[str, Any]:
        """Returns a user: ``user_id`` is the accountId on Cloud and the
        username on Server / Data Center."""
        with _translate_errors():
            return self._client().user(id=user_id).raw

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_groups(self) -> JiraGroupPage:
        """Returns the group names from ``groups/picker``, sorted."""
        with _translate_errors():
            # The public ``JIRA.groups()`` drops ``total``, which shows whether
            # the listing was cut off.
            response: dict[str, Any] = self._client()._get_json(
                "groups/picker", params={"maxResults": _GROUP_PICKER_MAX_RESULTS}
            )
        return JiraGroupPage(
            group_names=sorted(group["name"] for group in response["groups"]),
            total=response.get("total"),
        )

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_group_members_page(
        self, *, group_name: str, start_at: int, max_results: int
    ) -> dict[str, Any]:
        """Returns one page of the active members of a group
        (``group/member``, Jira 6.0+). The deprecated ``GET /group`` that the SDK
        uses is gone in Jira Server 10.3+
        (https://github.com/pycontribs/jira/pull/2356)."""
        with _translate_errors():
            return self._client()._get_json(
                "group/member",
                params={
                    "groupname": group_name,
                    "includeInactiveUsers": "false",
                    "startAt": start_at,
                    "maxResults": max_results,
                },
            )


def is_cloud_gateway(gateway: JiraSourceOperations) -> bool:
    """True when the gateway's credential uses the Cloud APIs."""
    return gateway._is_cloud()
