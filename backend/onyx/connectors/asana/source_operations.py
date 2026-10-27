"""Asana source-operations gateway: every Asana API call lives here.

The ``asana`` SDK pages a listing when the caller asks for the next item, so
the listings iterate inside the gateway and SDK errors leave as
``AsanaApiError`` from the iteration too.
"""

import json
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

import asana
from asana.rest import ApiException
from urllib3.exceptions import HTTPError, MaxRetryError
from urllib3.exceptions import TimeoutError as Urllib3TimeoutError

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.exceptions import SourceApiError
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)

T = TypeVar("T")

ASANA_API_TOKEN: str = "asana_api_token_secret"

_API_ROOT: str = "https://app.asana.com/api/1.0"
# (connect, read) seconds for every request.
_REQUEST_TIMEOUT: tuple[int, int] = (10, 60)
# Asana answers at most this many records in one page.
_MAX_PAGE_SIZE: int = 100


class AsanaApiError(SourceApiError):
    """Asana answered with an error status, or the request failed before it
    answered (no status then)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None,
        method: str,
        url: str,
        body: str | None = None,
        asana_message: str | None = None,
        timed_out: bool = False,
    ) -> None:
        super().__init__(
            message, status_code=status_code, method=method, url=url, body=body
        )
        # The first message in Asana's ``errors`` list, e.g. "Not a
        # recognized ID: abc".
        self.asana_message = asana_message
        self.timed_out = timed_out

    @property
    def is_rate_limited(self) -> bool:
        return self.status_code == 429


def _asana_message(body: str | None) -> str | None:
    if not body:
        return None
    try:
        parsed: Any = json.loads(body)
    except ValueError:
        return None
    errors: Any = parsed.get("errors") if isinstance(parsed, dict) else None
    if not isinstance(errors, list) or not errors or not isinstance(errors[0], dict):
        return None
    message: Any = errors[0].get("message")
    return str(message) if message else None


def _translated(method: str, path: str, call: Callable[[], T]) -> T:
    url: str = f"{_API_ROOT}{path}"
    try:
        return call()
    except ApiException as e:
        raw: Any = e.body
        body: str | None = (
            raw.decode("utf-8", errors="replace")
            if isinstance(raw, bytes)
            else (str(raw) if raw else None)
        )
        asana_message: str | None = _asana_message(body)
        raise AsanaApiError(
            f"Asana answered {e.status} to {method} {path}"
            + (f": {asana_message}" if asana_message else f" ({e.reason})"),
            status_code=e.status,
            method=method,
            url=url,
            body=body,
            asana_message=asana_message,
        ) from e
    except HTTPError as e:
        timed_out: bool = isinstance(e, Urllib3TimeoutError) or (
            isinstance(e, MaxRetryError) and isinstance(e.reason, Urllib3TimeoutError)
        )
        raise AsanaApiError(
            f"Asana request {method} {path} failed: {e}",
            status_code=None,
            method=method,
            url=url,
            timed_out=timed_out,
        ) from e


def _items(path: str, items: Iterator[Any]) -> Iterator[dict[str, Any]]:
    while True:
        item: Any = _translated("GET", path, lambda: next(items, None))
        if item is None:
            return
        yield item


def _listing_opts(
    opt_fields: str | None, limit: int | None, **params: str | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The SDK ``opts`` and keyword arguments of a listing. ``limit`` caps the
    items read, so a probe reads one page of that size."""
    opts: dict[str, Any] = {key: value for key, value in params.items() if value}
    if opt_fields:
        opts["opt_fields"] = opt_fields
    kwargs: dict[str, Any] = {"_request_timeout": _REQUEST_TIMEOUT}
    if limit is not None:
        opts["limit"] = min(limit, _MAX_PAGE_SIZE)
        kwargs["item_limit"] = limit
    return opts, kwargs


def _record_opts(opt_fields: str | None) -> dict[str, Any]:
    return {"opt_fields": opt_fields} if opt_fields else {}


class _AsanaClients:
    def __init__(self, api_token: str) -> None:
        configuration = asana.Configuration()
        configuration.access_token = api_token
        api_client = asana.ApiClient(configuration)
        self.projects = asana.ProjectsApi(api_client)
        self.stories = asana.StoriesApi(api_client)
        self.tasks = asana.TasksApi(api_client)
        self.teams = asana.TeamsApi(api_client)
        self.users = asana.UsersApi(api_client)
        self.workspaces = asana.WorkspacesApi(api_client)


class AsanaSourceOperations(SourceOperations):
    source = DocumentSource.ASANA
    sdk_modules = ("asana",)
    # Operations take the workspace, team and project ids as arguments.
    config_keys = frozenset()

    _clients_cache: _AsanaClients | None = None

    def _clients(self) -> _AsanaClients:
        if self._clients_cache is None:
            credentials: dict[str, Any] = self.credentials_provider.get_credentials()
            api_token: str | None = credentials.get(ASANA_API_TOKEN)
            if not api_token:
                raise ConnectorMissingCredentialError("Asana")
            self._clients_cache = _AsanaClients(api_token)
        return self._clients_cache

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_me(self) -> dict[str, Any]:
        """The token's own user, with the workspaces it is a member of."""
        users = self._clients().users
        return _translated(
            "GET",
            "/users/me",
            lambda: users.get_user(
                "me",
                {"opt_fields": "name,email,workspaces.name"},
                _request_timeout=_REQUEST_TIMEOUT,
            ),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def get_workspace(self, *, workspace_gid: str) -> dict[str, Any]:
        workspaces = self._clients().workspaces
        return _translated(
            "GET",
            f"/workspaces/{workspace_gid}",
            lambda: workspaces.get_workspace(
                workspace_gid, {}, _request_timeout=_REQUEST_TIMEOUT
            ),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def get_team(self, *, team_gid: str) -> dict[str, Any]:
        """One team, with the workspace (``organization``) it belongs to."""
        teams = self._clients().teams
        return _translated(
            "GET",
            f"/teams/{team_gid}",
            lambda: teams.get_team(
                team_gid,
                {"opt_fields": "name,organization.name"},
                _request_timeout=_REQUEST_TIMEOUT,
            ),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def get_project(
        self, *, project_gid: str, opt_fields: str | None = None
    ) -> dict[str, Any]:
        """One project. Without ``opt_fields``, Asana answers the full
        record."""
        projects = self._clients().projects
        return _translated(
            "GET",
            f"/projects/{project_gid}",
            lambda: projects.get_project(
                project_gid,
                _record_opts(opt_fields),
                _request_timeout=_REQUEST_TIMEOUT,
            ),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def iterate_projects(
        self,
        *,
        workspace_gid: str,
        opt_fields: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Every project of the workspace that the token's user can see."""
        projects = self._clients().projects
        opts, kwargs = _listing_opts(opt_fields, limit, workspace=workspace_gid)
        path: str = "/projects"
        return _items(
            path,
            _translated(
                "GET", path, lambda: iter(projects.get_projects(opts, **kwargs))
            ),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def iterate_project_tasks(
        self,
        *,
        project_gid: str,
        opt_fields: str | None = None,
        modified_since: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """The tasks of one project, optionally only those modified since an
        ISO 8601 time."""
        tasks = self._clients().tasks
        opts, kwargs = _listing_opts(opt_fields, limit, modified_since=modified_since)
        path: str = f"/projects/{project_gid}/tasks"
        return _items(
            path,
            _translated(
                "GET",
                path,
                lambda: iter(tasks.get_tasks_for_project(project_gid, opts, **kwargs)),
            ),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def iterate_task_stories(
        self, *, task_gid: str, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """The compact stories (comments and activity) of one task."""
        stories = self._clients().stories
        opts, kwargs = _listing_opts(None, limit)
        path: str = f"/tasks/{task_gid}/stories"
        return _items(
            path,
            _translated(
                "GET",
                path,
                lambda: iter(stories.get_stories_for_task(task_gid, opts, **kwargs)),
            ),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_story(
        self, *, story_gid: str, opt_fields: str | None = None
    ) -> dict[str, Any]:
        stories = self._clients().stories
        return _translated(
            "GET",
            f"/stories/{story_gid}",
            lambda: stories.get_story(
                story_gid, _record_opts(opt_fields), _request_timeout=_REQUEST_TIMEOUT
            ),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_user(
        self, *, user_gid: str, opt_fields: str | None = None
    ) -> dict[str, Any]:
        users = self._clients().users
        return _translated(
            "GET",
            f"/users/{user_gid}",
            lambda: users.get_user(
                user_gid, _record_opts(opt_fields), _request_timeout=_REQUEST_TIMEOUT
            ),
        )
