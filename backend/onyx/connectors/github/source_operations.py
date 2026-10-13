"""Source operations for the GitHub connector.

This is the only module in ``github/`` and in the EE GitHub permission sync
that imports PyGithub. PyGithub objects make network calls when a caller reads
an attribute that the first response did not have. So the operations call the
REST API through PyGithub's requester (auth, base URL, retries) and return
plain data (``github/models.py``), never PyGithub objects.

SDK errors leave the gateway as ``GitHubApiError``, and rate limits (primary
and secondary) as ``GitHubRateLimitError``. Generator operations translate
errors raised while the caller iterates.
"""

import base64
import functools
import inspect
import threading
import urllib.parse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, ParamSpec, TypeVar, cast

from github import Auth, Github, GithubException, RateLimitExceededException
from github.GithubRetry import GithubRetry
from github.Requester import Requester
from urllib3.response import BaseHTTPResponse
from urllib3.util.retry import Retry

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.cross_connector_utils.server_wait import bound_server_wait
from onyx.connectors.github.models import (
    GitHubBranch,
    GitHubCursorItem,
    GitHubFileContent,
    GitHubGitTree,
    GitHubIssue,
    GitHubOrganizationRef,
    GitHubPullRequest,
    GitHubRepository,
    GitHubTokenInfo,
    GitHubTokenKind,
    GitHubTreeEntry,
    GitHubUser,
)
from onyx.connectors.github.utils import resolve_github_base_url
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

_P = ParamSpec("_P")
_R = TypeVar("_R")

GITHUB_ACCESS_TOKEN_KEY = "github_access_token"

# The largest page GitHub allows.
_PER_PAGE = 100
_RATE_LIMITED_STATUS = 429
_FINE_GRAINED_TOKEN_PREFIX = "github_pat_"
_CLASSIC_TOKEN_PREFIX = "ghp_"
_SCOPES_HEADER = "x-oauth-scopes"
_ACCEPTED_SCOPES_HEADER = "x-accepted-oauth-scopes"
_ACCEPTED_PERMISSIONS_HEADER = "x-accepted-github-permissions"
_RATE_LIMIT_REMAINING_HEADER = "x-ratelimit-remaining"
_RETRY_AFTER_HEADER = "retry-after"
_SSO_HEADER = "x-github-sso"

_ALL_CAPABILITIES = frozenset(CredentialCapability)
_PERM_SYNC_CHECKS_PENDING = (
    "Not yet tested: the permission-sync checks land in the next PR."
)
_CURSOR_FALLBACK = (
    "Used only when GitHub refuses offset pages for a large listing; it reads "
    "the same endpoint as the offset listing that the checks probe."
)


class BoundedGithubRetry(GithubRetry):
    """GithubRetry whose server-requested waits go through bound_server_wait."""

    def increment(self, *args: Any, **kwargs: Any) -> Retry:
        retry = super().increment(*args, **kwargs)
        # GithubRetry replaces get_backoff_time with a wait until the rate
        # limit resets.
        backoff = bound_server_wait(retry.get_backoff_time(), "github")
        retry.get_backoff_time = lambda: backoff  # ty: ignore[invalid-assignment]
        return retry

    def get_retry_after(self, response: BaseHTTPResponse) -> float | None:
        retry_after = super().get_retry_after(response)
        if retry_after is None:
            return None
        return bound_server_wait(retry_after, "github")


class GitHubApiError(Exception):
    """A GitHub API call returned an error response.

    ``github_message`` is the ``message`` of the error body. The two
    ``accepted_*`` values come from the response headers: the OAuth scopes
    (classic token) or the fine-grained permissions that the endpoint accepts.
    ``sso_required`` is True when a SAML organization has not authorized the
    token.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        github_message: str | None = None,
        accepted_scopes: str | None = None,
        accepted_permissions: str | None = None,
        sso_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.github_message = github_message
        self.accepted_scopes = accepted_scopes
        self.accepted_permissions = accepted_permissions
        self.sso_required = sso_required


class GitHubRateLimitError(GitHubApiError):
    """GitHub rate limited the call, after the client's own retries.
    ``secondary`` is True for a secondary (abuse) rate limit."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        github_message: str | None = None,
        secondary: bool,
    ) -> None:
        super().__init__(
            message, status_code=status_code, github_message=github_message
        )
        self.secondary = secondary


def _header(headers: Any, name: str) -> str | None:
    if not isinstance(headers, dict):
        return None
    value: Any = headers.get(name)
    return str(value) if value is not None else None


def _github_message(error: GithubException) -> str | None:
    data: Any = error.data
    if isinstance(data, dict) and isinstance(data.get("message"), str):
        return data["message"]
    return error.message


def _translate(error: GithubException) -> GitHubApiError:
    headers: Any = error.headers
    github_message: str | None = _github_message(error)
    lowered: str = (github_message or "").lower()
    if (
        isinstance(error, RateLimitExceededException)
        or error.status == _RATE_LIMITED_STATUS
        or (
            error.status == 403
            and _header(headers, _RATE_LIMIT_REMAINING_HEADER) == "0"
        )
    ):
        return GitHubRateLimitError(
            str(error),
            status_code=error.status,
            github_message=github_message,
            secondary=(
                Requester.isSecondaryRateLimitError(lowered)
                or _header(headers, _RETRY_AFTER_HEADER) is not None
            ),
        )
    return GitHubApiError(
        str(error),
        status_code=error.status,
        github_message=github_message,
        accepted_scopes=_header(headers, _ACCEPTED_SCOPES_HEADER),
        accepted_permissions=_header(headers, _ACCEPTED_PERMISSIONS_HEADER),
        sso_required=bool(_header(headers, _SSO_HEADER)),
    )


@contextmanager
def _github_errors() -> Iterator[None]:
    try:
        yield
    except GithubException as error:
        raise _translate(error) from error


def _translated(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Raises the gateway's errors in place of the SDK's. A generator operation
    is wrapped for the whole iteration, since its calls run lazily."""
    if inspect.isgeneratorfunction(func):

        @functools.wraps(func)
        def generator(*args: Any, **kwargs: Any) -> Iterator[Any]:
            with _github_errors():
                yield from func(*args, **kwargs)

        return cast(Callable[_P, _R], generator)

    @functools.wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with _github_errors():
            return func(*args, **kwargs)

    return wrapper


def _next_link(headers: dict[str, Any]) -> str | None:
    """The ``next`` URL of a ``Link`` header, as PyGithub parses it."""
    link: Any = headers.get("link")
    if not isinstance(link, str):
        return None
    for part in link.split(", "):
        url, rel, *_rest = part.split("; ")
        if rel == 'rel="next"':
            return url[1:-1]
    return None


def _quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _token_kind(token: str, scopes: list[str] | None) -> GitHubTokenKind:
    if token.startswith(_FINE_GRAINED_TOKEN_PREFIX):
        return GitHubTokenKind.FINE_GRAINED
    if scopes is not None or token.startswith(_CLASSIC_TOKEN_PREFIX):
        return GitHubTokenKind.CLASSIC
    return GitHubTokenKind.OTHER


def _listing_params(state: str) -> dict[str, Any]:
    """The query of a pull request or issue listing: newest update first."""
    return {"state": state, "sort": "updated", "direction": "desc"}


class GitHubSourceOperations(SourceOperations):
    source = DocumentSource.GITHUB
    sdk_modules = ("github",)
    # The gateway reads only the credential.
    config_keys = frozenset()

    _cached_client: Github | None = None

    def _client_build_lock(self) -> threading.Lock:
        """Guards the first client build, which validates the base URL."""
        return vars(self).setdefault("_build_lock", threading.Lock())

    def _token(self) -> str:
        token: Any = self.credentials_provider.get_credentials().get(
            GITHUB_ACCESS_TOKEN_KEY
        )
        if not isinstance(token, str) or not token:
            raise ConnectorMissingCredentialError("GitHub (no access token)")
        return token

    def _client(self) -> Github:
        if self._cached_client is not None:
            return self._cached_client
        with self._client_build_lock():
            if self._cached_client is None:
                credentials: dict[str, Any] = (
                    self.credentials_provider.get_credentials()
                )
                base_url: str | None = resolve_github_base_url(credentials)
                kwargs: dict[str, Any] = {"base_url": base_url} if base_url else {}
                self._cached_client = Github(
                    auth=Auth.Token(self._token()),
                    per_page=_PER_PAGE,
                    retry=BoundedGithubRetry(),
                    **kwargs,
                )
        return self._cached_client

    def _get(
        self, url: str, params: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], Any]:
        """One GET through PyGithub's requester. Returns the response headers
        (lowercase names) and the decoded JSON."""
        return self._client().requester.requestJsonAndCheck(
            "GET", url, parameters=params
        )

    def _paginate(
        self,
        url: str,
        params: dict[str, Any] | None,
        *,
        skip: int = 0,
    ) -> Iterator[tuple[dict[str, Any], str | None]]:
        """Yields each raw item of a listing with the URL of the page after
        its page. Follows the ``Link`` header, as PyGithub does. ``params``
        apply to the first request only: next URLs carry their own query."""
        next_url: str | None = url
        request_params: dict[str, Any] | None = (
            {**(params or {}), "per_page": _PER_PAGE} if params is not None else None
        )
        skipped: int = 0
        while next_url is not None:
            headers, data = self._get(next_url, request_params)
            page: list[Any] = data if isinstance(data, list) else []
            next_url = _next_link(headers) if page else None
            request_params = None
            for raw in page:
                if raw is None:
                    continue
                if skipped < skip:
                    skipped += 1
                    continue
                yield raw, next_url

    def _list_page(
        self, url: str, params: dict[str, Any], page: int
    ) -> list[dict[str, Any]]:
        """One offset page of a listing, as PyGithub's ``get_page``: page 0
        sends no ``page`` parameter."""
        page_params: dict[str, Any] = {**params, "per_page": _PER_PAGE}
        if page != 0:
            page_params["page"] = page + 1
        _headers, data = self._get(url, page_params)
        return [raw for raw in (data if isinstance(data, list) else []) if raw]

    def _list_repositories(self, url: str, limit: int | None) -> list[GitHubRepository]:
        repositories: list[GitHubRepository] = []
        for raw, _next_url in self._paginate(url, {}):
            repositories.append(GitHubRepository.from_raw(raw))
            if limit is not None and len(repositories) >= limit:
                break
        return repositories

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    @_translated
    def get_token_info(self) -> GitHubTokenInfo:
        """The account the token acts as (``GET /user``), the token kind and,
        for a classic token, its OAuth scopes."""
        headers, data = self._get("/user")
        scopes_header: str | None = _header(headers, _SCOPES_HEADER)
        scopes: list[str] | None = (
            [scope.strip() for scope in scopes_header.split(",") if scope.strip()]
            if scopes_header is not None
            else None
        )
        return GitHubTokenInfo(
            login=data["login"],
            kind=_token_kind(self._token(), scopes),
            scopes=scopes,
        )

    @source_operation(
        capabilities=_ALL_CAPABILITIES,
        consumes=OperationConsumes.CREDENTIAL,
        untested=(
            "Called only after a rate-limit error, to wait until the limit "
            "resets; it changes no verdict."
        ),
    )
    @_translated
    def get_rate_limit_reset(self) -> datetime:
        """When the core rate limit resets (``GET /rate_limit``)."""
        _headers, data = self._get("/rate_limit")
        reset: int = data["resources"]["core"]["reset"]
        return datetime.fromtimestamp(reset, tz=timezone.utc)

    @source_operation(
        capabilities=_ALL_CAPABILITIES,
        consumes=OperationConsumes.BOTH,
        untested=_PERM_SYNC_CHECKS_PENDING,
    )
    @_translated
    def get_organization(self, *, login: str) -> GitHubOrganizationRef:
        """An organization (``GET /orgs/{login}``). Raises ``GitHubApiError``
        (404) when ``login`` is not an organization."""
        _headers, data = self._get(f"/orgs/{_quote(login)}")
        return GitHubOrganizationRef(id=data["id"], login=data["login"])

    @source_operation(
        capabilities=_ALL_CAPABILITIES,
        consumes=OperationConsumes.BOTH,
        untested=_PERM_SYNC_CHECKS_PENDING,
    )
    @_translated
    def list_organization_repositories(
        self, *, org_login: str, limit: int | None = None
    ) -> list[GitHubRepository]:
        """The organization's repositories that the token can see
        (``GET /orgs/{org}/repos``). ``limit`` stops the listing early."""
        return self._list_repositories(f"/orgs/{_quote(org_login)}/repos", limit)

    @source_operation(
        capabilities=_ALL_CAPABILITIES,
        consumes=OperationConsumes.BOTH,
        untested=_PERM_SYNC_CHECKS_PENDING,
    )
    @_translated
    def list_user_repositories(
        self, *, login: str, limit: int | None = None
    ) -> list[GitHubRepository]:
        """A user's repositories (``GET /users/{login}/repos``). GitHub lists
        only public repositories here, also for the token's own user."""
        return self._list_repositories(f"/users/{_quote(login)}/repos", limit)

    @source_operation(
        capabilities=_ALL_CAPABILITIES,
        consumes=OperationConsumes.BOTH,
        untested=_PERM_SYNC_CHECKS_PENDING,
    )
    @_translated
    def get_repository(self, *, owner: str, name: str) -> GitHubRepository:
        """One repository (``GET /repos/{owner}/{name}``). GitHub answers 404
        for a private repository that the token cannot see."""
        _headers, data = self._get(f"/repos/{_quote(owner)}/{_quote(name)}")
        return GitHubRepository.from_raw(data)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=(
            "Re-reads, by id, a repository that a listing returned during "
            "indexing; the repository checks probe the same access."
        ),
    )
    @_translated
    def get_repository_by_id(self, *, repo_id: int) -> GitHubRepository:
        """One repository by id (``GET /repositories/{id}``)."""
        _headers, data = self._get(f"/repositories/{repo_id}")
        return GitHubRepository.from_raw(data)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    @_translated
    def list_root_contents(self, *, repo_full_name: str) -> list[str]:
        """The names in the repository's root directory
        (``GET /repos/{repo}/contents/``)."""
        _headers, data = self._get(f"/repos/{repo_full_name}/contents/")
        entries: list[Any] = data if isinstance(data, list) else [data]
        return [
            str(entry.get("name"))
            for entry in entries
            if isinstance(entry, dict) and entry.get("name")
        ]

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    @_translated
    def get_branch(self, *, repo_full_name: str, branch: str) -> GitHubBranch:
        """One branch. Raises ``GitHubApiError`` (404) when it does not
        exist."""
        _headers, data = self._get(
            f"/repos/{repo_full_name}/branches/{urllib.parse.quote(branch)}"
        )
        return GitHubBranch(name=data["name"])

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    @_translated
    def list_pull_requests(
        self, *, repo_full_name: str, state: str, page: int
    ) -> list[GitHubPullRequest]:
        """One offset page of pull requests, newest update first. GitHub
        answers 422 when a large listing needs cursor pagination."""
        return [
            GitHubPullRequest.from_raw(raw, detailed=False)
            for raw in self._list_page(
                f"/repos/{repo_full_name}/pulls", _listing_params(state), page
            )
        ]

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=_CURSOR_FALLBACK,
    )
    @_translated
    def iter_pull_requests_by_cursor(
        self,
        *,
        repo_full_name: str,
        state: str,
        cursor_url: str | None = None,
        skip: int = 0,
    ) -> Iterator[GitHubCursorItem[GitHubPullRequest]]:
        """Pull requests by cursor pagination, from ``cursor_url`` or from the
        first page. ``skip`` drops that many items first."""
        for raw, next_url in self._paginate(
            cursor_url or f"/repos/{repo_full_name}/pulls",
            None if cursor_url else _listing_params(state),
            skip=skip,
        ):
            yield GitHubCursorItem(
                item=GitHubPullRequest.from_raw(raw, detailed=False),
                next_url=next_url,
            )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    @_translated
    def get_pull_request(
        self, *, repo_full_name: str, number: int
    ) -> GitHubPullRequest:
        """One pull request with the fields a listing leaves out (merged,
        commits, changed files, merged by)."""
        _headers, data = self._get(f"/repos/{repo_full_name}/pulls/{number}")
        return GitHubPullRequest.from_raw(data, detailed=True)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    @_translated
    def list_issues(
        self, *, repo_full_name: str, state: str, page: int
    ) -> list[GitHubIssue]:
        """One offset page of issues (pull requests included), newest update
        first."""
        return [
            GitHubIssue.from_raw(raw, repo_full_name=repo_full_name, detailed=False)
            for raw in self._list_page(
                f"/repos/{repo_full_name}/issues", _listing_params(state), page
            )
        ]

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=_CURSOR_FALLBACK,
    )
    @_translated
    def iter_issues_by_cursor(
        self,
        *,
        repo_full_name: str,
        state: str,
        cursor_url: str | None = None,
        skip: int = 0,
    ) -> Iterator[GitHubCursorItem[GitHubIssue]]:
        """Issues by cursor pagination, from ``cursor_url`` or from the first
        page. ``skip`` drops that many items first."""
        for raw, next_url in self._paginate(
            cursor_url or f"/repos/{repo_full_name}/issues",
            None if cursor_url else _listing_params(state),
            skip=skip,
        ):
            yield GitHubCursorItem(
                item=GitHubIssue.from_raw(
                    raw, repo_full_name=repo_full_name, detailed=False
                ),
                next_url=next_url,
            )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    @_translated
    def get_issue(self, *, repo_full_name: str, number: int) -> GitHubIssue:
        """One issue with the fields a listing leaves out (closed by)."""
        _headers, data = self._get(f"/repos/{repo_full_name}/issues/{number}")
        return GitHubIssue.from_raw(data, repo_full_name=repo_full_name, detailed=True)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    @_translated
    def get_git_tree(self, *, repo_full_name: str, ref: str) -> GitHubGitTree:
        """The recursive tree of a branch, tag or commit. GitHub answers 404
        for an unknown ref and 409 for an empty repository."""
        _headers, data = self._get(
            f"/repos/{repo_full_name}/git/trees/{urllib.parse.quote(ref)}",
            {"recursive": 1},
        )
        return GitHubGitTree(
            entries=[
                GitHubTreeEntry(
                    path=entry["path"], type=entry["type"], size=entry.get("size")
                )
                for entry in data.get("tree") or []
            ],
            truncated=bool(data.get("truncated")),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    @_translated
    def get_file_content(
        self, *, repo_full_name: str, path: str, ref: str
    ) -> GitHubFileContent:
        """The content of one file. Raises ``ValueError`` for a directory."""
        _headers, data = self._get(
            f"/repos/{repo_full_name}/contents/{urllib.parse.quote(path)}",
            {"ref": ref},
        )
        if not isinstance(data, dict):
            raise ValueError(f"Expected a file at {path}, got a directory")
        encoding: Any = data.get("encoding")
        content: Any = data.get("content")
        return GitHubFileContent(
            content=(
                base64.b64decode(bytearray(content, "utf-8"))
                if encoding == "base64" and isinstance(content, str)
                else None
            ),
            encoding=encoding if isinstance(encoding, str) else None,
        )

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_PERM_SYNC_CHECKS_PENDING,
    )
    @_translated
    def get_user(self, *, login: str) -> GitHubUser:
        """A user's profile (``GET /users/{login}``), with the public email.
        Indexing also reads the name and email of authors, but skips a user it
        cannot read, so only group sync needs this."""
        _headers, data = self._get(f"/users/{_quote(login)}")
        return GitHubUser(
            login=data["login"], name=data.get("name"), email=data.get("email")
        )

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.BOTH,
        untested=_PERM_SYNC_CHECKS_PENDING,
    )
    @_translated
    def list_repository_collaborators(self, *, repo_full_name: str) -> list[str]:
        """The logins of everyone with access to the repository, from any
        grant (``GET /repos/{repo}/collaborators``). GitHub requires push
        access to the repository."""
        return [
            raw["login"]
            for raw, _next_url in self._paginate(
                f"/repos/{repo_full_name}/collaborators", {}
            )
        ]

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.BOTH,
        untested=_PERM_SYNC_CHECKS_PENDING,
    )
    @_translated
    def list_organization_members(self, *, org_login: str) -> list[str]:
        """The logins of the organization's members
        (``GET /orgs/{org}/members?filter=all``). Without ``read:org`` or
        membership, GitHub lists only the public members."""
        return [
            raw["login"]
            for raw, _next_url in self._paginate(
                f"/orgs/{_quote(org_login)}/members", {"filter": "all"}
            )
        ]
