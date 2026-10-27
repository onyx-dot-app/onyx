"""Asana source-operations gateway: every Asana API call lives here.

The ``asana`` SDK pages a listing when the caller asks for the next item, so
the listings iterate inside the gateway and SDK errors leave from the
iteration too. A rejected token, a denied request, a rate limit and a
transport failure leave as validation errors; any other error status leaves
as ``AsanaApiError``.
"""

from collections.abc import Callable, Iterator
from typing import Any, TypeVar

import asana
from asana.rest import ApiException
from urllib3.exceptions import HTTPError, MaxRetryError
from urllib3.exceptions import TimeoutError as Urllib3TimeoutError

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.exceptions import (
    CredentialInvalidError,
    InsufficientPermissionsError,
    RateLimitedValidationError,
    SourceApiError,
    TimedOutValidationError,
    UnreachableValidationError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)

T = TypeVar("T")

ASANA_API_TOKEN: str = "asana_api_token_secret"
NEW_TOKEN_LINE: str = (
    "In Asana, open My settings > Apps > Manage Developer Apps, create a "
    "personal access token, and paste it in the account."
)

_API_ROOT: str = "https://app.asana.com/api/1.0"
# (connect, read) seconds for every request.
_REQUEST_TIMEOUT: tuple[int, int] = (10, 60)
# Asana answers at most this many records in one page.
_MAX_PAGE_SIZE: int = 100


class AsanaApiError(SourceApiError):
    """Asana answered an error status the gateway does not map itself, e.g.
    404 for an item that does not exist or that the token cannot see, and
    400 for an ID that is not a number."""

    def __init__(self, *, status_code: int, path: str, body: str | None) -> None:
        super().__init__(
            f"Asana answered {status_code} to GET {path}",
            status_code=status_code,
            method="GET",
            url=f"{_API_ROOT}{path}",
            body=body,
        )

    @property
    def not_found(self) -> bool:
        return self.status_code in (400, 404)


def _call(path: str, call: Callable[[], T]) -> T:
    try:
        return call()
    except ApiException as e:
        # The SDK wraps a connection or TLS failure as status 0.
        if not e.status:
            raise UnreachableValidationError(
                f"Onyx cannot connect to Asana for GET {path}: {e.reason}"
            ) from e
        raw: Any = e.body
        body: str | None = raw.decode("utf-8", errors="replace") if raw else None
        # The cause of a mapped error, so a check's Error Details show the
        # request and Asana's body.
        api_error = AsanaApiError(status_code=int(e.status), path=path, body=body)
        if api_error.status_code == 401:
            raise CredentialInvalidError(
                "Asana rejected the personal access token (HTTP 401).",
                summary="Asana rejected the token",
                description=(
                    "The token is wrong, expired or revoked. (HTTP 401)\n"
                    f"{NEW_TOKEN_LINE}"
                ),
            ) from api_error
        if api_error.status_code == 403:
            raise InsufficientPermissionsError(
                f"The Asana token cannot read {path} (HTTP 403).",
                summary="Asana denied access",
                description=(
                    f"Asana refused to read {path} for this token. (HTTP 403)\n"
                    "Give the token's user access in Asana."
                ),
            ) from api_error
        if api_error.status_code == 429:
            raise RateLimitedValidationError(
                "Asana rate limited the request. Try again in a minute.",
                summary="Rate limited by Asana",
                description=(
                    "Asana refused the request because of its rate limit. (HTTP 429)\n"
                    "Wait a minute, then re-run."
                ),
            ) from api_error
        raise api_error from e
    except HTTPError as e:
        if isinstance(e, Urllib3TimeoutError) or (
            isinstance(e, MaxRetryError) and isinstance(e.reason, Urllib3TimeoutError)
        ):
            raise TimedOutValidationError(
                f"Asana did not answer GET {path} in time."
            ) from e
        raise UnreachableValidationError(
            f"Onyx cannot connect to Asana for GET {path}: {e}"
        ) from e


def _items(path: str, items: Iterator[Any]) -> Iterator[dict[str, Any]]:
    while True:
        item: Any = _call(path, lambda: next(items, None))
        if item is None:
            return
        yield item


def _opts(opt_fields: str | None, **params: str | None) -> dict[str, Any]:
    opts: dict[str, Any] = {key: value for key, value in params.items() if value}
    if opt_fields:
        opts["opt_fields"] = opt_fields
    return opts


def _listing_kwargs(limit: int | None) -> dict[str, Any]:
    """``limit`` caps the items read, so a probe reads one page of that size."""
    kwargs: dict[str, Any] = {"_request_timeout": _REQUEST_TIMEOUT}
    if limit is not None:
        kwargs["item_limit"] = limit
    return kwargs


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
        return _call(
            "/users/me",
            lambda: users.get_user(
                "me",
                _opts("name,email,workspaces.name"),
                _request_timeout=_REQUEST_TIMEOUT,
            ),
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
    )
    def get_workspace(self, *, workspace_gid: str) -> dict[str, Any]:
        workspaces = self._clients().workspaces
        return _call(
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
        return _call(
            f"/teams/{team_gid}",
            lambda: teams.get_team(
                team_gid,
                _opts("name,organization"),
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
        """One project. Without ``opt_fields``, Asana answers the full record."""
        projects = self._clients().projects
        return _call(
            f"/projects/{project_gid}",
            lambda: projects.get_project(
                project_gid, _opts(opt_fields), _request_timeout=_REQUEST_TIMEOUT
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
        archived: bool | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Every project of the workspace that the token's user can see,
        or only the archived or the live ones."""
        projects = self._clients().projects
        path: str = "/projects"
        opts: dict[str, Any] = _opts(opt_fields, workspace=workspace_gid)
        if archived is not None:
            opts["archived"] = "true" if archived else "false"
        return _items(
            path,
            _call(
                path,
                lambda: iter(projects.get_projects(opts, **_listing_kwargs(limit))),
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
        path: str = f"/projects/{project_gid}/tasks"
        return _items(
            path,
            _call(
                path,
                lambda: iter(
                    tasks.get_tasks_for_project(
                        project_gid,
                        _opts(opt_fields, modified_since=modified_since),
                        **_listing_kwargs(limit),
                    )
                ),
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
        path: str = f"/tasks/{task_gid}/stories"
        return _items(
            path,
            _call(
                path,
                lambda: iter(
                    stories.get_stories_for_task(task_gid, {}, **_listing_kwargs(limit))
                ),
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
        return _call(
            f"/stories/{story_gid}",
            lambda: stories.get_story(
                story_gid, _opts(opt_fields), _request_timeout=_REQUEST_TIMEOUT
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
        return _call(
            f"/users/{user_gid}",
            lambda: users.get_user(
                user_gid, _opts(opt_fields), _request_timeout=_REQUEST_TIMEOUT
            ),
        )
