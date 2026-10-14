"""YouTrack source-operations gateway: every YouTrack REST call lives here.

YouTrack Cloud and self-hosted Server share one REST API under
`<base_url>/api`, authenticated with a permanent token. The base URL is
admin-supplied and receives the token, so it passes the shared SSRF checks
before the first request.
"""

from collections.abc import Iterator
from typing import Any, TypeVar
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel
from requests.adapters import HTTPAdapter
from urllib3.response import BaseHTTPResponse
from urllib3.util.retry import Retry

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.connector_config import BaseUrlCredentialBinding
from onyx.connectors.cross_connector_utils.outbound import validate_connector_url
from onyx.connectors.cross_connector_utils.server_wait import bound_server_wait
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    CredentialInvalidError,
    InsufficientPermissionsError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.connectors.youtrack.models import (
    YouTrackAssignedRole,
    YouTrackComment,
    YouTrackIssue,
    YouTrackIssueAccess,
    YouTrackOrganization,
    YouTrackProject,
    YouTrackRef,
    YouTrackRole,
    YouTrackSlimIssue,
    YouTrackUser,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

YOUTRACK_TOKEN: str = "youtrack_token"

_TIMEOUT_SECONDS: int = 60


class _BoundedRetry(Retry):
    """Retry whose server-requested waits go through bound_server_wait."""

    def get_retry_after(self, response: BaseHTTPResponse) -> float | None:
        retry_after = super().get_retry_after(response)
        if retry_after is None:
            return None
        return bound_server_wait(retry_after, "youtrack")


# urllib3 honors Retry-After on 429 and backs off on 5xx.
_RETRY: Retry = _BoundedRetry(
    total=8,
    backoff_factor=2,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
)
# A full issue carries comments and custom fields, so it pages smaller than
# the three-field slim walk.
ISSUE_PAGE_SIZE: int = 100
SLIM_PAGE_SIZE: int = 1000
_LISTING_PAGE_SIZE: int = 500
# Each page re-reads the last tenth of the previous one, which absorbs that
# many deletions between two requests.
_PAGE_OVERLAP_DIVISOR: int = 10
# A walk still paging past this is a server that ignores $skip.
_MAX_PAGES: int = 100_000
# Listings (projects, users, one issue's comments) are held in memory whole.
_MAX_LISTED_ITEMS: int = 250_000

_USER_FIELDS: str = "id,login,fullName,email,banned,guest,userType(id)"
_PROJECT_FIELDS: str = "id,shortName,name,archived,projectType(id)"
_COMMENT_FIELDS: str = "id,text,deleted,visibility($type)"
_ISSUE_FIELDS: str = (
    "id,idReadable,summary,description,created,updated,resolved,commentsCount,"
    f"project({_PROJECT_FIELDS}),reporter({_USER_FIELDS}),"
    "customFields($type,name,value(name,fullName,presentation,text),"
    "projectCustomField(isPublic)),"
    f"comments({_COMMENT_FIELDS})"
)
_SLIM_ISSUE_FIELDS: str = f"id,created,project({_PROJECT_FIELDS})"
_ISSUE_ACCESS_FIELDS: str = (
    f"id,project({_PROJECT_FIELDS}),reporter(id),"
    "visibility($type,permittedGroups(id),permittedUsers(id))"
)
_ASSIGNED_ROLE_FIELDS: str = (
    "id,role(id),holder($type,id),scope($type,project(id),organization(id))"
)


ModelT = TypeVar("ModelT", bound=BaseModel)


class YouTrackRequestError(RuntimeError):
    """YouTrack answered with an error status, or kept failing until the
    retries ran out (no status then)."""

    def __init__(self, status_code: int | None, detail: str) -> None:
        super().__init__(f"YouTrack request failed ({status_code}): {detail}")
        self.status_code = status_code


def validate_base_url(base_url: str) -> None:
    validate_connector_url(base_url, "YouTrack URL", https_only=True)


def _api_root(base_url: str) -> str:
    """Cloud serves the API at `<instance>/api`, Server under its context path,
    which the admin includes in the base URL (e.g. `https://host/youtrack`)."""
    return f"{base_url.rstrip('/')}/api"


def _error_detail(response: requests.Response) -> str:
    try:
        body: dict[str, Any] = response.json()
    except ValueError:
        return response.text[:500]
    return str(body.get("error_description") or body.get("error") or body)[:500]


class YouTrackSourceOperations(SourceOperations):
    source = DocumentSource.YOUTRACK
    sdk_modules = ("requests",)
    config_keys = frozenset(BaseUrlCredentialBinding.model_fields)

    _session_cache: tuple[requests.Session, str] | None = None

    def _session(self) -> tuple[requests.Session, str]:
        """The authenticated session and the API root it may call."""
        if self._session_cache is not None:
            return self._session_cache
        binding: BaseUrlCredentialBinding = BaseUrlCredentialBinding.model_validate(
            self.connector_specific_config or {}
        )
        validate_base_url(binding.base_url)
        credentials: dict[str, Any] = self.credentials_provider.get_credentials()
        token: str | None = credentials.get(YOUTRACK_TOKEN)
        if not token:
            raise ConnectorMissingCredentialError("YouTrack")
        api_root: str = _api_root(binding.base_url)
        session = requests.Session()
        session.headers.update(
            {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        )
        # Mounted on the API root only, so a redirect elsewhere gets no retries.
        session.mount(api_root, HTTPAdapter(max_retries=_RETRY))
        self._session_cache = (session, api_root)
        return self._session_cache

    def _get(self, path: str, params: dict[str, str | int] | None = None) -> Any:
        session, api_root = self._session()
        url: str = f"{api_root}{path}"
        try:
            response: requests.Response = session.get(
                url, params=params, timeout=_TIMEOUT_SECONDS, allow_redirects=False
            )
        except requests.exceptions.RetryError as e:
            raise YouTrackRequestError(None, f"retries exhausted on {path}") from e
        if response.status_code == 401:
            raise CredentialInvalidError(
                "YouTrack rejected the token. Check that it is valid and not revoked."
            )
        if response.status_code == 403:
            raise InsufficientPermissionsError(
                f"The YouTrack token cannot read {path}: {_error_detail(response)}"
            )
        if response.is_redirect:
            # A redirect usually means the base URL lacks the Server context
            # path. Following it could send the token to another host.
            location: str = response.headers.get("Location", "")
            raise ConnectorValidationError(
                f"YouTrack redirected {path} to "
                f"{urlsplit(location).netloc or location}. Check the base URL."
            )
        if not response.ok:
            raise YouTrackRequestError(response.status_code, _error_detail(response))
        return response.json()

    def _pages(
        self, path: str, params: dict[str, str | int], page_size: int
    ) -> Iterator[list[dict[str, Any]]]:
        """Each page of a `$top`/`$skip` listing until a short page, without
        repeats. Pages overlap, so items deleted between two requests shift the
        listing back without pushing a live item past the next page's start: a
        missed item would read as deleted to pruning. A repeat can only come
        from the page before, so only its ids are kept."""
        overlap: int = page_size // _PAGE_OVERLAP_DIVISOR
        step: int = page_size - overlap
        previous: set[str] = set()
        for page in range(_MAX_PAGES):
            items: list[dict[str, Any]] = self._get(
                path, {**params, "$top": page_size, "$skip": page * step}
            )
            fresh: list[dict[str, Any]] = [
                item for item in items if item["id"] not in previous
            ]
            previous = {item["id"] for item in items}
            if fresh:
                yield fresh
            if len(items) < page_size:
                return
        raise RuntimeError(f"YouTrack kept paging {path} past {_MAX_PAGES} pages")

    def _list(self, path: str, fields: str, model: type[ModelT]) -> list[ModelT]:
        items: list[ModelT] = []
        for page in self._pages(path, {"fields": fields}, _LISTING_PAGE_SIZE):
            items.extend(model.model_validate(item) for item in page)
            if len(items) > _MAX_LISTED_ITEMS:
                raise RuntimeError(
                    f"YouTrack {path} listed more than {_MAX_LISTED_ITEMS} items"
                )
        return items

    @source_operation(
        capabilities=(
            CredentialCapability.INDEXING,
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.BOTH,
    )
    def get_me(self) -> YouTrackUser:
        """The token's own user."""
        return YouTrackUser.model_validate(
            self._get("/users/me", {"fields": _USER_FIELDS})
        )

    @source_operation(
        capabilities=(
            CredentialCapability.INDEXING,
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.BOTH,
    )
    def list_projects(self) -> list[YouTrackProject]:
        """Every project the token can read, archived ones included."""
        return self._list("/admin/projects", _PROJECT_FIELDS, YouTrackProject)

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def iterate_issues(
        self, *, query: str, page_size: int = ISSUE_PAGE_SIZE
    ) -> Iterator[list[YouTrackIssue]]:
        """Pages of issues matching a YouTrack search query, with comments."""
        for page in self._pages(
            "/issues", {"query": query, "fields": _ISSUE_FIELDS}, page_size
        ):
            yield [YouTrackIssue.model_validate(item) for item in page]

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def list_issue_comments(self, *, issue_id: str) -> list[YouTrackComment]:
        """Every comment of one issue, for issues whose embedded list fell
        short of their comment count."""
        return self._list(
            f"/issues/{issue_id}/comments", _COMMENT_FIELDS, YouTrackComment
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def iterate_slim_issues(
        self, *, query: str, page_size: int = SLIM_PAGE_SIZE
    ) -> Iterator[list[YouTrackSlimIssue]]:
        """Pages of issue ids for pruning."""
        for page in self._pages(
            "/issues", {"query": query, "fields": _SLIM_ISSUE_FIELDS}, page_size
        ):
            yield [YouTrackSlimIssue.model_validate(item) for item in page]

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.BOTH,
    )
    def iterate_issue_access(
        self, *, query: str, page_size: int = SLIM_PAGE_SIZE
    ) -> Iterator[list[YouTrackIssueAccess]]:
        """Pages of each issue's project, reporter and visibility."""
        for page in self._pages(
            "/issues", {"query": query, "fields": _ISSUE_ACCESS_FIELDS}, page_size
        ):
            yield [YouTrackIssueAccess.model_validate(item) for item in page]

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.BOTH,
    )
    def list_users(self) -> list[YouTrackUser]:
        return self._list("/users", _USER_FIELDS, YouTrackUser)

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.BOTH,
    )
    def list_group_user_ids(self, *, group_id: str) -> set[str]:
        """Members of the group and of every group nested under it."""
        return {
            ref.id for ref in self._list(f"/groups/{group_id}/users", "id", YouTrackRef)
        }

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.BOTH,
    )
    def list_roles(self) -> list[YouTrackRole]:
        return self._list("/roles", "id,permissions(id,key)", YouTrackRole)

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.BOTH,
    )
    def list_assigned_roles(self) -> list[YouTrackAssignedRole]:
        """Every role grant in every scope. Needs YouTrack 2026.1 or later and
        a token that can read global and project roles."""
        try:
            return self._list(
                "/assignedRoles", _ASSIGNED_ROLE_FIELDS, YouTrackAssignedRole
            )
        except YouTrackRequestError as e:
            if e.status_code != 404:
                raise
            raise ConnectorValidationError(
                "This YouTrack has no role assignments API. Permission sync "
                "needs YouTrack 2026.1 or later."
            ) from e

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.BOTH,
    )
    def list_organizations(self) -> list[YouTrackOrganization]:
        return self._list(
            "/admin/organizations", "id,projects(id)", YouTrackOrganization
        )
