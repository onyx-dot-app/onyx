"""Source operations for the Google Drive connector.

This is the only module in ``google_drive/`` and in the EE Drive permission
sync that imports the Google SDK. Drive operations take the email of the user
to act as: a service account impersonates that user through domain-wide
delegation, and an OAuth credential ignores it and acts as its own user.
Directory operations act as the primary admin. Operations return plain data,
and SDK errors leave the gateway as ``GoogleDriveHttpError`` and
``GoogleDriveRefreshError``.
"""

import functools
import inspect
import io
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import Enum
from typing import Any, ParamSpec, TypeVar, cast

import requests
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from googleapiclient.errors import HttpError
from googleapiclient.http import BatchHttpRequest, MediaIoBaseDownload
from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.google_drive.constants import (
    DRIVE_FOLDER_TYPE,
    DRIVE_RESOURCE_KEY_FIELD,
    DRIVE_RESOURCE_KEY_HEADER,
)
from onyx.connectors.google_drive.models import (
    DriveBatchResult,
    GoogleDriveFileType,
)
from onyx.connectors.google_utils.google_auth import get_google_creds
from onyx.connectors.google_utils.google_utils import (
    GoogleFields,
    execute_access_probe,
    execute_paginated_retrieval,
    execute_paginated_retrieval_with_max_pages,
    is_access_denied,
)
from onyx.connectors.google_utils.resources import (
    get_admin_service,
    get_drive_service,
    get_google_authorized_session,
)
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_PRIMARY_ADMIN_KEY,
    USER_FIELDS,
    GoogleCredentialKind,
)
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

# Google caps a batch request at 100 calls.
_MAX_BATCH_SIZE = 100
_DOWNLOAD_NUM_RETRIES = 3
# Extra bytes a download chunk reads past the size threshold, so an oversized
# file is detected without reading all of it.
_CHUNK_SIZE_BUFFER = 64
_DOCS_API_DOCUMENT_URL = "https://docs.googleapis.com/v1/documents/{doc_id}"
_DOCS_FETCH_TIMEOUT_SECONDS = 60
_DOCS_FETCH_CHUNK_SIZE = 1024 * 1024

# What a requested target probe needs to decide who should crawl it.
_TARGET_PROBE_FIELDS = "id, mimeType, driveId, owners(emailAddress)"
_DRIVE_MEMBER_FIELDS = "permissions(emailAddress, type, role), nextPageToken"
_GROUP_MEMBER_FIELDS = "members(email, type), nextPageToken"
_GROUP_FIELDS = "groups(email), nextPageToken"
# Only the folder id and its permissions. permissionIds is needed because the
# API sometimes leaves out permissions that it lists by id.
_FOLDER_PERMISSION_FIELDS = (
    "nextPageToken, files(id, name, permissionIds, "
    "permissions(id, emailAddress, type, domain, permissionDetails))"
)


class GoogleDriveHttpError(Exception):
    """A Google API request failed with an HTTP error status."""

    def __init__(
        self,
        *,
        status_code: int,
        reasons: tuple[str, ...],
        access_denied: bool,
        message: str,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        # The machine-readable reasons Google gave, e.g. "accessNotConfigured"
        # or "teamDriveMembershipRequired".
        self.reasons = reasons
        # A 403 or 404 that is not a rate limit in disguise.
        self.access_denied = access_denied


class GoogleDriveRefreshError(Exception):
    """Google refused to issue a token: the service account cannot impersonate
    the user, or the OAuth grant is revoked or expired."""


class ExportSizeThresholdExceeded(Exception):
    """A Drive download or export was aborted because it passed the size
    threshold."""


class DriveCorpus(str, Enum):
    """The ``corpora`` of a files.list call. It sets what the caller must be
    allowed to see."""

    # Files the user owns or that are shared with the user.
    USER = "user"
    # One shared drive; the user must be a member.
    DRIVE = "drive"
    # Every drive the user can see.
    ALL_DRIVES = "allDrives"


class GoogleDriveAuth(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: GoogleCredentialKind
    primary_admin_email: str
    # The credential to store when loading it refreshed the OAuth token, else
    # None.
    refreshed_credential_json: dict[str, str] | None = None


class GoogleDirectoryUser(BaseModel):
    is_admin: bool
    is_delegated_admin: bool


class GoogleGroupMember(BaseModel):
    email: str | None
    # USER, GROUP or CUSTOMER.
    type: str | None


def _error_reasons(error_details: object) -> tuple[str, ...]:
    if not isinstance(error_details, list):
        return ()
    reasons: list[str] = []
    for detail in error_details:
        reason = detail.get("reason") if isinstance(detail, dict) else None
        if reason:
            reasons.append(str(reason))
    return tuple(reasons)


def _from_http_error(error: HttpError) -> GoogleDriveHttpError:
    return GoogleDriveHttpError(
        status_code=error.status_code,
        reasons=_error_reasons(error.error_details),
        access_denied=is_access_denied(error),
        message=str(error),
    )


def _from_requests_error(error: requests.HTTPError) -> GoogleDriveHttpError:
    response = error.response
    status = response.status_code if response is not None else 0
    reasons: tuple[str, ...] = ()
    if response is not None:
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            error_body = body["error"]
            reasons = _error_reasons(error_body.get("errors")) + _error_reasons(
                error_body.get("details")
            )
    rate_limited = status == 429 or any(
        reason in ("userRateLimitExceeded", "rateLimitExceeded") for reason in reasons
    )
    return GoogleDriveHttpError(
        status_code=status,
        reasons=reasons,
        access_denied=status in (403, 404) and not rate_limited,
        message=str(error),
    )


def _translate(error: Exception) -> Exception:
    if isinstance(error, HttpError):
        return _from_http_error(error)
    if isinstance(error, RefreshError):
        return GoogleDriveRefreshError(str(error))
    if isinstance(error, requests.HTTPError):
        return _from_requests_error(error)
    return error


@contextmanager
def _google_errors() -> Iterator[None]:
    try:
        yield
    except (HttpError, RefreshError, requests.HTTPError) as error:
        raise _translate(error) from error


def _translated(func: Callable[_P, _R]) -> Callable[_P, _R]:
    """Raises the gateway's errors in place of the SDK's. A generator operation
    is wrapped for the whole iteration, since its calls run lazily."""
    if inspect.isgeneratorfunction(func):

        @functools.wraps(func)
        def generator(*args: Any, **kwargs: Any) -> Iterator[Any]:
            with _google_errors():
                yield from func(*args, **kwargs)

        return cast(Callable[_P, _R], generator)

    @functools.wraps(func)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with _google_errors():
            return func(*args, **kwargs)

    return wrapper


def _add_resource_key_header(
    request: Any, file_id: str, resource_key: str | None
) -> None:
    if resource_key:
        request.headers[DRIVE_RESOURCE_KEY_HEADER] = f"{file_id}/{resource_key}"


def _download(request: Any, file_id: str, size_threshold: int) -> bytes:
    response_bytes = io.BytesIO()
    downloader = MediaIoBaseDownload(
        response_bytes, request, chunksize=size_threshold + _CHUNK_SIZE_BUFFER
    )
    done = False
    while not done:
        # num_retries retries transient errors with exponential backoff.
        download_progress, done = downloader.next_chunk(
            num_retries=_DOWNLOAD_NUM_RETRIES
        )
        if download_progress.resumable_progress > size_threshold:
            raise ExportSizeThresholdExceeded(
                f"File {file_id} exceeds size threshold of {size_threshold}"
            )

    response = response_bytes.getvalue()
    if not response:
        logger.warning("Failed to download %s", file_id)
        return bytes()
    return response


_ALL_CAPABILITIES = frozenset(CredentialCapability)
_PERM_SYNC_CAPABILITIES = frozenset(
    {
        CredentialCapability.DOC_PERMISSION_SYNC,
        CredentialCapability.EXTERNAL_GROUP_SYNC,
    }
)
_NOT_YET_TESTED = "Not yet tested: capability checks land later in the stack."


class GoogleDriveSourceOperations(SourceOperations):
    source = DocumentSource.GOOGLE_DRIVE
    sdk_modules = ("google", "googleapiclient")
    # The gateway reads only the credential.
    config_keys = frozenset()

    _cached_auth: GoogleDriveAuth | None = None
    _cached_creds: ServiceAccountCredentials | OAuthCredentials | None = None

    def _auth_lock(self) -> threading.Lock:
        """Guards the first credential load, which refreshes the token.
        ``dict.setdefault`` is atomic under the GIL, so no guard lock is
        needed."""
        return vars(self).setdefault("_auth_lock_instance", threading.Lock())

    def _load_auth(self) -> None:
        with self._auth_lock():
            if self._cached_auth is not None:
                return
            with self.credentials_provider:
                credentials = self.credentials_provider.get_credentials()
                primary_admin_email = credentials.get(DB_CREDENTIALS_PRIMARY_ADMIN_KEY)
                if not primary_admin_email:
                    raise ConnectorMissingCredentialError(
                        "Google Drive (no primary admin email in the credential)"
                    )
                creds, refreshed = get_google_creds(
                    credentials=credentials, source=DocumentSource.GOOGLE_DRIVE
                )
                if refreshed is not None:
                    self.credentials_provider.set_credentials(refreshed)
            self._cached_creds = creds
            self._cached_auth = GoogleDriveAuth(
                kind=(
                    GoogleCredentialKind.SERVICE_ACCOUNT
                    if isinstance(creds, ServiceAccountCredentials)
                    else GoogleCredentialKind.OAUTH
                ),
                primary_admin_email=primary_admin_email,
                refreshed_credential_json=refreshed,
            )

    def _auth(self) -> GoogleDriveAuth:
        if self._cached_auth is None:
            self._load_auth()
        if self._cached_auth is None:
            raise RuntimeError("Bug: the credential load set no auth.")
        return self._cached_auth

    def _creds(self) -> ServiceAccountCredentials | OAuthCredentials:
        if self._cached_creds is None:
            self._load_auth()
        if self._cached_creds is None:
            raise RuntimeError("Bug: the credential load set no credentials.")
        return self._cached_creds

    def _drive(self, user_email: str) -> Any:
        return get_drive_service(self._creds(), user_email)

    def _directory(self) -> Any:
        """The Admin SDK directory service, acting as the primary admin."""
        return get_admin_service(self._creds(), self._auth().primary_admin_email)

    def _domain(self) -> str:
        return self._auth().primary_admin_email.split("@")[-1]

    @source_operation(
        capabilities=_ALL_CAPABILITIES,
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def authenticate(self) -> GoogleDriveAuth:
        """Loads the credential, refreshing its token. Runs once per gateway; a
        refreshed OAuth token is written back through the credentials
        provider."""
        return self._auth()

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def get_root_folder_id(self, *, user_email: str) -> str:
        """The id of the user's My Drive root. Fails when the user cannot be
        impersonated or has no Drive access."""
        return (
            self._drive(user_email)
            .files()
            .get(fileId="root", fields=GoogleFields.ID.value)
            .execute()[GoogleFields.ID.value]
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        variants=tuple(DriveCorpus),
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def list_files(
        self,
        *,
        variant: DriveCorpus,
        user_email: str,
        fields: str,
        query: str | None = None,
        drive_id: str | None = None,
        order_by: str | None = None,
        page_token: str | None = None,
        page_size: int | None = None,
        max_num_pages: int | None = None,
        continue_on_404_or_403: bool = False,
    ) -> Iterator[GoogleDriveFileType | str]:
        """files.list over a corpus. ``fields`` must request nextPageToken.
        With ``max_num_pages``, yields the next page token (a str) after that
        many pages and stops; without it, yields files only."""
        if (variant == DriveCorpus.DRIVE) != (drive_id is not None):
            raise ValueError("A drive listing needs drive_id, and only it.")
        kwargs: dict[str, Any] = {"corpora": variant.value, "fields": fields}
        if query is not None:
            kwargs["q"] = query
        if variant != DriveCorpus.USER:
            kwargs["supportsAllDrives"] = True
            kwargs["includeItemsFromAllDrives"] = True
        if drive_id is not None:
            kwargs["driveId"] = drive_id
        if order_by is not None:
            kwargs["orderBy"] = order_by
        if page_token:
            kwargs["pageToken"] = page_token
        if page_size is not None:
            kwargs["pageSize"] = page_size
        retrieval_function = self._drive(user_email).files().list
        if max_num_pages is None:
            yield from execute_paginated_retrieval(
                retrieval_function=retrieval_function,
                list_key="files",
                continue_on_404_or_403=continue_on_404_or_403,
                **kwargs,
            )
            return
        yield from execute_paginated_retrieval_with_max_pages(
            retrieval_function=retrieval_function,
            max_num_pages=max_num_pages,
            list_key="files",
            continue_on_404_or_403=continue_on_404_or_403,
            **kwargs,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def get_file(
        self,
        *,
        user_email: str,
        file_id: str,
        fields: str,
        resource_key: str | None = None,
    ) -> GoogleDriveFileType | None:
        """files.get, or None when the user cannot see the file (403, 404, or a
        failed impersonation)."""
        try:
            request = (
                self._drive(user_email)
                .files()
                .get(fileId=file_id, fields=fields, supportsAllDrives=True)
            )
            _add_resource_key_header(request, file_id, resource_key)
            file = request.execute()
        except HttpError as e:
            if e.resp.status in (403, 404):
                logger.debug("Cannot access Drive file %s: %s", file_id, e)
                return None
            raise
        except RefreshError:
            logger.debug("Cannot access Drive file %s: impersonation failed", file_id)
            return None
        if resource_key:
            file[DRIVE_RESOURCE_KEY_FIELD] = resource_key
        return file

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def probe_target(
        self, *, user_email: str, target_id: str
    ) -> GoogleDriveFileType | None:
        """Metadata of a requested drive or folder, or None if this user cannot
        see it. Rate limits and server errors are retried, then raise: reading
        them as "cannot see it" would pick a weaker principal."""
        try:
            request = (
                self._drive(user_email)
                .files()
                .get(
                    fileId=target_id,
                    supportsAllDrives=True,
                    fields=_TARGET_PROBE_FIELDS,
                )
            )
            return execute_access_probe(request)
        except RefreshError:
            return None

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def batch_get_files(
        self, *, user_email: str, file_ids_by_key: dict[str, str], fields: str
    ) -> DriveBatchResult:
        """files.get for many files in batch requests, keyed by the caller's
        key. Per-file errors go to ``errors``."""
        result = DriveBatchResult()
        keys = list(file_ids_by_key)
        service = self._drive(user_email)
        for start in range(0, len(keys), _MAX_BATCH_SIZE):

            def callback(
                request_id: str,
                response: GoogleDriveFileType,
                exception: Exception | None,
            ) -> None:
                if exception is not None:
                    logger.warning(
                        "Error retrieving file %s: %s", request_id, exception
                    )
                    result.errors[request_id] = _translate(exception)
                else:
                    result.files[request_id] = response

            batch = cast(
                BatchHttpRequest, service.new_batch_http_request(callback=callback)
            )
            for key in keys[start : start + _MAX_BATCH_SIZE]:
                batch.add(
                    service.files().get(
                        fileId=file_ids_by_key[key],
                        supportsAllDrives=True,
                        fields=fields,
                    ),
                    request_id=key,
                )
            batch.execute()
        return result

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def list_drives(
        self, *, user_email: str, use_domain_admin_access: bool
    ) -> Iterator[str]:
        """Ids of the shared drives the user can see. With domain admin access,
        every shared drive of the domain."""
        for drive in execute_paginated_retrieval(
            retrieval_function=self._drive(user_email).drives().list,
            list_key="drives",
            useDomainAdminAccess=use_domain_admin_access,
            fields="drives(id),nextPageToken",
        ):
            yield drive["id"]

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def get_shared_drive_name(self, *, user_email: str, drive_id: str) -> str | None:
        """The name of a shared drive (files.get calls every drive root
        'Drive'), or None when the user cannot see the drive."""
        try:
            drive = (
                self._drive(user_email)
                .drives()
                .get(driveId=drive_id, fields="name")
                .execute()
            )
        except HttpError as e:
            if e.resp.status in (403, 404):
                logger.debug("Cannot access drive %s: %s", drive_id, e)
                return None
            raise
        except RefreshError:
            logger.debug("Cannot access drive %s: impersonation failed", drive_id)
            return None
        return drive.get("name")

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def can_list_drive(self, *, user_email: str, drive_id: str) -> bool:
        """Whether the user is a member who can list the shared drive.

        drives.get comes first: for a non-member, files.list can succeed with
        zero items, which would make the drive look empty rather than out of
        reach. Only access denial or a failed impersonation returns False; any
        other error raises, so the run fails instead of picking a weaker
        principal.
        """
        service = self._drive(user_email)
        try:
            drive = execute_access_probe(
                service.drives().get(driveId=drive_id, fields="id")
            )
            if drive is None:
                return False
            listing = execute_access_probe(
                service.files().list(
                    corpora="drive",
                    driveId=drive_id,
                    includeItemsFromAllDrives=True,
                    supportsAllDrives=True,
                    pageSize=1,
                    fields="files(id)",
                )
            )
        except RefreshError as error:
            logger.info(
                "Cannot impersonate a candidate for drive %s: %s", drive_id, error
            )
            return False
        return listing is not None

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def list_drive_members(
        self, *, drive_id: str, use_domain_admin_access: bool
    ) -> Iterator[dict[str, Any]]:
        """The permissions of a shared drive (its members), read as the
        primary admin. With domain admin access this works for drives the admin
        is not a member of; it answers 404 for a drive of another domain."""
        yield from execute_paginated_retrieval(
            retrieval_function=self._drive(self._auth().primary_admin_email)
            .permissions()
            .list,
            list_key="permissions",
            fileId=drive_id,
            useDomainAdminAccess=use_domain_admin_access,
            supportsAllDrives=True,
            fields=_DRIVE_MEMBER_FIELDS,
        )

    @source_operation(
        capabilities=_ALL_CAPABILITIES,
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def list_file_permissions(
        self, *, user_email: str, file_id: str, fields: str
    ) -> Iterator[dict[str, Any]]:
        """The permissions of a file or folder, read as a user who can see it.
        ``fields`` must request nextPageToken."""
        yield from execute_paginated_retrieval(
            retrieval_function=self._drive(user_email).permissions().list,
            list_key="permissions",
            fileId=file_id,
            supportsAllDrives=True,
            fields=fields,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def download_file(
        self,
        *,
        user_email: str,
        file_id: str,
        size_threshold: int,
        resource_key: str | None = None,
    ) -> bytes:
        """The content of an uploaded file. Raises
        ``ExportSizeThresholdExceeded`` past ``size_threshold`` bytes."""
        request = self._drive(user_email).files().get_media(fileId=file_id)
        _add_resource_key_header(request, file_id, resource_key)
        return _download(request, file_id, size_threshold)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def export_file(
        self,
        *,
        user_email: str,
        file_id: str,
        mime_type: str,
        size_threshold: int,
        resource_key: str | None = None,
    ) -> bytes:
        """A Google Doc, Sheet or Slides file exported as ``mime_type``. Raises
        ``ExportSizeThresholdExceeded`` past ``size_threshold`` bytes."""
        request = (
            self._drive(user_email)
            .files()
            .export_media(fileId=file_id, mimeType=mime_type)
        )
        _add_resource_key_header(request, file_id, resource_key)
        return _download(request, file_id, size_threshold)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def fetch_google_doc(
        self, *, user_email: str, doc_id: str, max_response_bytes: int
    ) -> dict[str, Any] | None:
        """A Google Doc from the Docs API, with the content of every tab. None
        when the response exceeds ``max_response_bytes``; it is streamed, so an
        oversized one is never held whole."""
        with get_google_authorized_session(self._creds(), user_email) as session:
            with session.get(
                _DOCS_API_DOCUMENT_URL.format(doc_id=doc_id),
                params={"includeTabsContent": "true"},
                stream=True,
                timeout=_DOCS_FETCH_TIMEOUT_SECONDS,
            ) as response:
                response.raise_for_status()
                buffer = bytearray()
                for chunk in response.iter_content(chunk_size=_DOCS_FETCH_CHUNK_SIZE):
                    if not chunk:
                        continue
                    if len(buffer) + len(chunk) > max_response_bytes:
                        return None
                    buffer.extend(chunk)
        return json.loads(buffer)

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def list_user_emails(self, *, query: str | None = None) -> Iterator[str]:
        """The primary emails of the Workspace domain's users. ``query`` is a
        directory search, e.g. "isAdmin=true"."""
        kwargs: dict[str, Any] = {"domain": self._domain(), "fields": USER_FIELDS}
        if query is not None:
            kwargs["query"] = query
        for user in execute_paginated_retrieval(
            retrieval_function=self._directory().users().list,
            list_key="users",
            **kwargs,
        ):
            if email := user.get("primaryEmail"):
                yield email

    @source_operation(
        capabilities=_PERM_SYNC_CAPABILITIES,
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def get_admin_user(self) -> GoogleDirectoryUser:
        """The primary admin's directory entry. Fails when the primary admin
        cannot use the Workspace directory API."""
        user = (
            self._directory()
            .users()
            .get(userKey=self._auth().primary_admin_email)
            .execute()
        )
        return GoogleDirectoryUser(
            is_admin=bool(user.get("isAdmin", False)),
            is_delegated_admin=bool(user.get("isDelegatedAdmin", False)),
        )

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def list_groups(self) -> Iterator[str]:
        """The emails of the Workspace domain's groups."""
        for group in execute_paginated_retrieval(
            retrieval_function=self._directory().groups().list,
            list_key="groups",
            domain=self._domain(),
            fields=_GROUP_FIELDS,
        ):
            yield group["email"]

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def list_group_members(self, *, group_email: str) -> Iterator[GoogleGroupMember]:
        """The direct members of a group. Nested groups are not expanded."""
        for member in execute_paginated_retrieval(
            retrieval_function=self._directory().members().list,
            list_key="members",
            groupKey=group_email,
            fields=_GROUP_MEMBER_FIELDS,
        ):
            yield GoogleGroupMember(email=member.get("email"), type=member.get("type"))

    @source_operation(
        capabilities={CredentialCapability.EXTERNAL_GROUP_SYNC},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_NOT_YET_TESTED,
    )
    @_translated
    def list_folders_with_permissions(
        self, *, user_email: str
    ) -> Iterator[GoogleDriveFileType]:
        """Every folder the user can see, with its published permissions."""
        yield from execute_paginated_retrieval(
            retrieval_function=self._drive(user_email).files().list,
            list_key="files",
            continue_on_404_or_403=True,
            corpora=DriveCorpus.ALL_DRIVES.value,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            includePermissionsForView="published",
            fields=_FOLDER_PERMISSION_FIELDS,
            q=f"mimeType = '{DRIVE_FOLDER_TYPE}' and trashed = false",
        )
