"""Egnyte source-operations gateway: every Egnyte Public API call lives here.

Egnyte limits each access token to 2 calls per second and a daily quota
(1,000 calls by default). The gateway paces its own calls, waits out a
per-second 429, and fails at once when the daily quota is used up, since that
429 asks to wait until the quota resets.
"""

import re
import threading
import time
from io import BytesIO
from typing import Any
from urllib.parse import quote

import requests

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.cross_connector_utils.server_wait import bound_server_wait
from onyx.connectors.egnyte.models import (
    EgnyteFile,
    EgnyteFolder,
    EgnyteFolderPage,
    EgnyteGroup,
    EgnyteGroupRef,
    EgnytePermissions,
    EgnyteUser,
    EgnyteUserInfo,
)
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
from onyx.utils.logger import setup_logger
from onyx.utils.retry_after import parse_retry_after_seconds

logger = setup_logger()

EGNYTE_DOMAIN: str = "domain"
EGNYTE_ACCESS_TOKEN: str = "access_token"

# The domain is the subdomain of egnyte.com, so it must be one DNS label.
_DOMAIN_PATTERN: re.Pattern[str] = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$"
)
# (connect, read) seconds for every request.
_REQUEST_TIMEOUT: tuple[int, int] = (10, 60)
# Egnyte allows 2 calls per second per token.
_MIN_REQUEST_INTERVAL_SECONDS: float = 0.5
_MAX_ATTEMPTS: int = 6
_MAX_BACKOFF_SECONDS: float = 30.0
_DEFAULT_RATE_LIMIT_WAIT_SECONDS: float = 1.0
_QUOTA_ALLOTTED_HEADER: str = "X-Accesstoken-Quota-Allotted"
_QUOTA_CURRENT_HEADER: str = "X-Accesstoken-Quota-Current"
_DOWNLOAD_CHUNK_BYTES: int = 1024 * 1024
_V2_USERS_PATH: str = "/v2/users"
_V2_GROUPS_PATH: str = "/v2/groups"
# Egnyte returns at most 100 users or groups per page.
_DIRECTORY_PAGE_SIZE: int = 100
# A listing still paging past this is a server that ignores startIndex.
_MAX_DIRECTORY_PAGES: int = 10_000
# Guards the lazy session build and the pacing schedule of every gateway
# instance. Waits happen outside it.
_LOCK = threading.Lock()


class EgnyteApiError(SourceApiError):
    """Egnyte answered an error status the gateway does not map itself, or
    kept failing until the retries ran out."""


class EgnyteQuotaExhaustedError(RateLimitedValidationError):
    """The token used up its daily Egnyte API quota."""


def validate_domain(domain: str) -> None:
    if not _DOMAIN_PATTERN.match(domain):
        raise CredentialInvalidError(
            f"'{domain}' is not an Egnyte domain. Use the name before "
            "'.egnyte.com', e.g. 'company' for company.egnyte.com."
        )


def _api_root(domain: str) -> str:
    return f"https://{domain}.egnyte.com/pubapi"


def _fs_path(path: str) -> str:
    return quote(path.strip("/"))


def _is_quota_exhausted(response: requests.Response) -> bool:
    try:
        allotted = int(response.headers[_QUOTA_ALLOTTED_HEADER])
        current = int(response.headers[_QUOTA_CURRENT_HEADER])
    except (KeyError, ValueError):
        return False
    return current >= allotted


class EgnyteSourceOperations(SourceOperations):
    source = DocumentSource.EGNYTE
    sdk_modules = ("requests",)
    config_keys = frozenset()

    _session_cache: tuple[requests.Session, str] | None = None
    _next_request_at: float = 0.0

    def _session(self) -> tuple[requests.Session, str]:
        """The authenticated session and the API root it may call."""
        if self._session_cache is not None:
            return self._session_cache
        credentials: dict[str, Any] = self.credentials_provider.get_credentials()
        domain: str | None = credentials.get(EGNYTE_DOMAIN)
        token: str | None = credentials.get(EGNYTE_ACCESS_TOKEN)
        if not domain or not token:
            raise ConnectorMissingCredentialError("Egnyte")
        validate_domain(domain)
        with _LOCK:
            if self._session_cache is None:
                session = requests.Session()
                session.headers.update({"Authorization": f"Bearer {token}"})
                self._session_cache = (session, _api_root(domain))
        return self._session_cache

    def _wait_for_turn(self) -> None:
        with _LOCK:
            now = time.monotonic()
            start = max(now, self._next_request_at)
            self._next_request_at = start + _MIN_REQUEST_INTERVAL_SECONDS
        if start > now:
            time.sleep(start - now)

    def _get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        session, api_root = self._session()
        url = f"{api_root}{path}"
        for attempt in range(_MAX_ATTEMPTS):
            is_last_attempt = attempt == _MAX_ATTEMPTS - 1
            self._wait_for_turn()
            try:
                response = session.get(
                    url,
                    params=params,
                    stream=stream,
                    timeout=_REQUEST_TIMEOUT,
                    allow_redirects=False,
                )
            except requests.Timeout as e:
                if is_last_attempt:
                    raise TimedOutValidationError(
                        f"Egnyte did not answer GET {path} in time."
                    ) from e
                continue
            except requests.ConnectionError as e:
                if is_last_attempt:
                    raise UnreachableValidationError(
                        f"Onyx cannot connect to Egnyte for GET {path}: {e}"
                    ) from e
                continue

            if response.status_code == 429:
                if _is_quota_exhausted(response):
                    raise EgnyteQuotaExhaustedError(
                        "The Egnyte token used up its daily API quota. Onyx "
                        "continues when the quota resets.",
                        summary="Egnyte daily API quota used up",
                    )
                wait = parse_retry_after_seconds(response.headers.get("Retry-After"))
                time.sleep(
                    bound_server_wait(
                        wait if wait is not None else _DEFAULT_RATE_LIMIT_WAIT_SECONDS,
                        "egnyte",
                    )
                )
                continue
            if response.status_code >= 500 and not is_last_attempt:
                time.sleep(min(2.0**attempt, _MAX_BACKOFF_SECONDS))
                continue
            if response.status_code == 401:
                raise CredentialInvalidError(
                    "Egnyte rejected the access token. Reconnect the Egnyte account."
                )
            if response.status_code == 403:
                raise InsufficientPermissionsError(
                    f"The Egnyte token cannot read {path}: {response.text[:500]}"
                )
            if not response.ok or response.is_redirect:
                raise EgnyteApiError(
                    f"Egnyte answered {response.status_code} to GET {path}",
                    status_code=response.status_code,
                    method="GET",
                    url=url,
                    body=response.text[:500],
                )
            return response
        raise EgnyteApiError(
            f"Egnyte kept rate limiting GET {path}",
            status_code=429,
            method="GET",
            url=url,
        )

    def _list_folder_page(
        self, folder_path: str, offset: int, page_size: int, with_permissions: bool
    ) -> EgnyteFolderPage:
        params: dict[str, str | int] = {
            "list_content": "true",
            "count": page_size,
            "offset": offset,
            # Names are unique in a folder, so the order is stable while the
            # folder changes.
            "sort_by": "name",
            "sort_direction": "ascending",
        }
        if with_permissions:
            params["perms"] = "true"
        body: dict[str, Any] = self._get(
            f"/v1/fs/{_fs_path(folder_path)}", params
        ).json()
        return EgnyteFolderPage(
            folder=EgnyteFolder.model_validate(body),
            folders=[EgnyteFolder.model_validate(f) for f in body.get("folders", [])],
            files=[EgnyteFile.model_validate(f) for f in body.get("files", [])],
            permissions=(
                EgnytePermissions.model_validate(body.get("permissions") or {})
                if with_permissions
                else None
            ),
        )

    def _list_directory(self, path: str, limit: int | None) -> list[dict[str, Any]]:
        """The resources of a SCIM listing, which pages by 1-based startIndex.
        Every one, or at most ``limit`` from one call."""
        resources: list[dict[str, Any]] = []
        for _ in range(_MAX_DIRECTORY_PAGES):
            body: dict[str, Any] = self._get(
                path,
                {
                    "startIndex": len(resources) + 1,
                    "count": min(limit or _DIRECTORY_PAGE_SIZE, _DIRECTORY_PAGE_SIZE),
                },
            ).json()
            page: list[dict[str, Any]] = body.get("resources", [])
            resources.extend(page)
            if limit is not None:
                return resources[:limit]
            if not page or len(resources) >= int(body.get("totalResults", 0)):
                return resources
        raise RuntimeError(
            f"Egnyte kept paging {path} past {_MAX_DIRECTORY_PAGES} pages"
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_folder_page(
        self, *, folder_path: str, offset: int, page_size: int
    ) -> EgnyteFolderPage:
        """One page of a folder's direct children, sorted by name."""
        return self._list_folder_page(folder_path, offset, page_size, False)

    @source_operation(
        capabilities=(CredentialCapability.DOC_PERMISSION_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_folder_page_with_permissions(
        self, *, folder_path: str, offset: int, page_size: int
    ) -> EgnyteFolderPage:
        """A folder page with the folder's effective grants. Needs the
        Egnyte.permission scope, and Egnyte refuses it for "/" and "/Private"."""
        return self._list_folder_page(folder_path, offset, page_size, True)

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_user_info(self) -> EgnyteUserInfo:
        return EgnyteUserInfo.model_validate(self._get("/v1/userinfo").json())

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_users(self, *, limit: int | None = None) -> list[EgnyteUser]:
        """Every user of the domain, or the first ``limit`` with one call.
        Needs an administrator's token."""
        return [
            EgnyteUser.model_validate(user)
            for user in self._list_directory(_V2_USERS_PATH, limit)
        ]

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_groups(self, *, limit: int | None = None) -> list[EgnyteGroupRef]:
        """Every custom group, or the first ``limit`` with one call. The
        default groups are not listed."""
        return [
            EgnyteGroupRef.model_validate(group)
            for group in self._list_directory(_V2_GROUPS_PATH, limit)
        ]

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_group(self, *, group_id: str) -> EgnyteGroup:
        """A custom group with its members."""
        return EgnyteGroup.model_validate(
            self._get(f"{_V2_GROUPS_PATH}/{quote(group_id)}").json()
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def download_file(self, *, file_path: str, max_bytes: int | None = None) -> BytesIO:
        """The latest version of a file, streamed into one buffer so a large
        file is held in memory once. With ``max_bytes``, only the start of
        the file is read."""
        buffer = BytesIO()
        chunk_size = min(max_bytes or _DOWNLOAD_CHUNK_BYTES, _DOWNLOAD_CHUNK_BYTES)
        response = self._get(f"/v1/fs-content/{_fs_path(file_path)}", stream=True)
        with response:
            for chunk in response.iter_content(chunk_size=chunk_size):
                buffer.write(chunk)
                if max_bytes is not None and buffer.tell() >= max_bytes:
                    break
        buffer.seek(0)
        return buffer
