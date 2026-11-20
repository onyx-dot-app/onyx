"""DealCloud source-operations gateway: every DealCloud REST call lives here.

A DealCloud site serves its REST API under `<site>/api/rest`. An API user's
client id and API key buy a bearer token that lasts 15 minutes. The site URL is
admin-supplied and receives the key, so every request goes through the shared
SSRF-safe transport.
"""

import codecs
import json
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from typing import Any, TypeVar

import requests
from pydantic import JsonValue

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.connector_config import BaseUrlCredentialBinding
from onyx.connectors.cross_connector_utils.server_wait import bound_server_wait
from onyx.connectors.dealcloud.models import (
    DealCloudEntryType,
    DealCloudField,
    DealCloudRow,
    DealCloudUser,
    DealCloudUserGroup,
    DealCloudUserGroupRef,
)
from onyx.connectors.exceptions import (
    ConnectorValidationError,
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
from onyx.server.security.models import connector_ssrf_enforced
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from onyx.utils.retry_after import parse_retry_after_seconds
from onyx.utils.url import SSRFException, ssrf_safe_request

logger = setup_logger()

T = TypeVar("T")

DEALCLOUD_CLIENT_ID: str = "dealcloud_client_id"
DEALCLOUD_API_KEY: str = "dealcloud_api_key"

# Rows per query. DealCloud accepts up to 10,000. Rows carry every field, so
# this stays lower to keep one answer under MAX_RESPONSE_BYTES for wide
# objects. A batch that is still too large is read in halves.
ROW_BATCH_SIZE: int = 2000

_DATA_SCOPE: str = "data"
# A separate token, so a user without the user management capability still
# gets a data token and can index.
_USER_MANAGEMENT_SCOPE: str = "user_management"
_USER_GROUP_PATH: str = "/v1/management/user/group"
_USER_GROUP_PAGE_SIZE: int = 1000
# A listing still paging past this is a site that ignores pageNumber.
_MAX_USER_GROUP_PAGES: int = 1000
_TOKEN_PATH: str = "/v1/oauth/token"
_SCHEMA_PATH: str = "/v4/schema/entrytypes"
_DATA_PATH: str = "/v4/data/entrydata"
_REQUEST_TIMEOUT: tuple[int, int] = (10, 120)
# Data and schema each allow 5 calls per second. One shared pace stays under both.
_MIN_REQUEST_INTERVAL_SECONDS: float = 0.2
_MAX_ATTEMPTS: int = 6
# A 429 tells the gateway to wait, so it does not count as a failed attempt.
# One call gives up after this many, or after this long waiting in total, and
# the next run resumes from the checkpoint.
_MAX_RATE_LIMIT_WAITS: int = 30
_MAX_RATE_LIMIT_WAIT_SECONDS: float = 300.0
# The rate limit window is one second.
_DEFAULT_RATE_LIMIT_WAIT_SECONDS: float = 1.0
# DealCloud names the end of the current rate limit window in this header.
_RATE_LIMIT_RESET_HEADER: str = "X-Rate-Limit-Reset"
# A token is renewed this long before DealCloud expires it.
_TOKEN_REFRESH_MARGIN_SECONDS: float = 60.0
_TOKEN_REJECTED_STATUSES: frozenset[int] = frozenset({400, 401, 403})
_ROW_ENTRY_ID_KEY: str = "EntryId"
# An answer read whole, such as a batch of rows, is refused past this size
# instead of filling the worker's memory.
MAX_RESPONSE_BYTES: int = 64 * 1024 * 1024
# DealCloud lists every entry id of an object in one answer. It is parsed as a
# stream, and a listing with more entries than this fails.
MAX_LISTED_ENTRIES: int = 5_000_000
# One listed entry is a few hundred characters. An entry still open after this
# many is not a listing, and would otherwise grow the parser's buffer.
_MAX_LISTED_ENTRY_CHARS: int = 1024 * 1024
_READ_CHUNK_BYTES: int = 1024 * 1024
_ERROR_DETAIL_BYTES: int = 500
# Guards the pacing schedule and the lazy token lock. Waits happen outside it.
_LOCK = threading.Lock()


class DealCloudApiError(SourceApiError):
    """DealCloud answered an error status the gateway does not map itself,
    kept answering 5xx until the retries ran out, or sent an answer the
    gateway cannot read."""


class DealCloudAnswerTooLargeError(DealCloudApiError):
    """An answer read whole passed MAX_RESPONSE_BYTES."""


def _send(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None,
    params: dict[str, str] | None,
    body: dict[str, JsonValue] | None,
    form: dict[str, str] | None,
) -> requests.Response:
    """One request to the site. It connects to the address that passed the
    SSRF check, so a DNS change cannot move it to another host. The SSRF
    protection level decides how strict the check is: private hosts are
    reachable only when an admin relaxed it, and cloud metadata stays blocked
    either way."""
    enforced: bool = connector_ssrf_enforced(
        get_security_settings().ssrf_protection_level
    )
    headers: dict[str, str] = {"Accept": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    try:
        return ssrf_safe_request(
            f"{base_url.rstrip('/')}/api/rest{path}",
            headers=headers,
            timeout=_REQUEST_TIMEOUT,
            allow_private_network=not enforced,
            block_loopback_and_link_local=False,
            block_link_local_only=not enforced,
            https_only=True,
            method=method,
            params=params,
            json=body,
            data=form,
            stream=True,
        )
    except SSRFException as e:
        raise ConnectorValidationError(
            f"Invalid DealCloud URL '{base_url}': {e}"
        ) from e


def _succeeded(response: requests.Response) -> bool:
    """Redirects are not followed, so a 3xx is a failure. Following one could
    send the key or token to another host."""
    return 200 <= response.status_code < 300


def _read_json(response: requests.Response) -> Any:
    """The parsed body, read up to MAX_RESPONSE_BYTES."""
    chunks: list[bytes] = []
    size = 0
    with response:
        for chunk in response.iter_content(chunk_size=_READ_CHUNK_BYTES):
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise DealCloudAnswerTooLargeError(
                    "DealCloud's answer is larger than "
                    f"{MAX_RESPONSE_BYTES // (1024 * 1024)} MB",
                    status_code=response.status_code,
                )
            chunks.append(chunk)
    return json.loads(b"".join(chunks))


def _iter_json_objects(response: requests.Response) -> Iterator[dict[str, Any]]:
    """The objects of a JSON array answer, parsed as they arrive, so an answer
    of any size holds little more than one chunk in memory."""
    decoder = json.JSONDecoder()
    to_text = codecs.getincrementaldecoder("utf-8")()
    buffer = ""
    in_array = False
    with response:
        for chunk in response.iter_content(chunk_size=_READ_CHUNK_BYTES):
            buffer += to_text.decode(chunk)
            position = 0
            while True:
                while position < len(buffer) and buffer[position] in " \t\r\n,":
                    position += 1
                if position == len(buffer):
                    break
                if not in_array:
                    if buffer[position] != "[":
                        raise ValueError("the answer is not a JSON array")
                    in_array = True
                    position += 1
                    continue
                if buffer[position] == "]":
                    return
                try:
                    item, position = decoder.raw_decode(buffer, position)
                except json.JSONDecodeError:
                    if len(buffer) - position > _MAX_LISTED_ENTRY_CHARS:
                        raise ValueError(
                            "an entry of the answer is longer than "
                            f"{_MAX_LISTED_ENTRY_CHARS} characters"
                        )
                    # The object continues in the next chunk.
                    break
                if not isinstance(item, dict):
                    raise ValueError("the answer is not an array of objects")
                yield item
            buffer = buffer[position:]
    raise ValueError("the answer ended before its JSON array closed")


def _error_detail(response: requests.Response) -> str:
    """The start of an error body. The rest is not read, and the streamed
    response is closed so its connection is released."""
    with response:
        start: bytes = next(response.iter_content(chunk_size=_ERROR_DETAIL_BYTES), b"")
    return start[:_ERROR_DETAIL_BYTES].decode(errors="replace")


def _rate_limit_wait_seconds(response: requests.Response) -> float:
    wait = parse_retry_after_seconds(response.headers.get("Retry-After"))
    if wait is not None:
        return wait
    try:
        reset = datetime.fromisoformat(response.headers[_RATE_LIMIT_RESET_HEADER])
    except (KeyError, ValueError):
        return _DEFAULT_RATE_LIMIT_WAIT_SECONDS
    if reset.tzinfo is None:
        reset = reset.replace(tzinfo=timezone.utc)
    return max((reset - datetime.now(timezone.utc)).total_seconds(), 0.0)


def _to_modified_since(moment: datetime) -> str:
    """DealCloud accepts only this shape, e.g. 2020-04-26T01:16:40.030Z."""
    utc = moment.astimezone(timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def _listed_entry_ids(response: requests.Response) -> list[int]:
    """Ascending ids of the entries an answer lists, without those it marks
    as deleted."""
    entry_ids: list[int] = []
    for entry in _iter_json_objects(response):
        if entry.get("isDeleted"):
            continue
        entry_ids.append(entry["id"])
        if len(entry_ids) > MAX_LISTED_ENTRIES:
            raise ValueError(f"the answer lists more than {MAX_LISTED_ENTRIES} entries")
    return sorted(entry_ids)


class DealCloudSourceOperations(SourceOperations):
    source = DocumentSource.DEALCLOUD
    sdk_modules = ("requests",)
    config_keys = frozenset(BaseUrlCredentialBinding.model_fields)

    _next_request_at: float = 0.0
    # No call starts before this monotonic time, set by a 429.
    _paused_until: float = 0.0
    # Per scope, the bearer token and the monotonic time it stops being used at.
    _token_cache: dict[str, tuple[str, float]] | None = None
    _token_lock_cache: threading.Lock | None = None

    def _base_url(self) -> str:
        return BaseUrlCredentialBinding.model_validate(
            self.connector_specific_config or {}
        ).base_url

    def _token_lock(self) -> threading.Lock:
        """One per gateway, so a slow site delays only its own token."""
        if self._token_lock_cache is None:
            with _LOCK:
                if self._token_lock_cache is None:
                    self._token_lock_cache = threading.Lock()
        return self._token_lock_cache

    def _wait_for_turn(self) -> None:
        while True:
            with _LOCK:
                now = time.monotonic()
                start = max(now, self._next_request_at, self._paused_until)
                self._next_request_at = start + _MIN_REQUEST_INTERVAL_SECONDS
            if start > now:
                time.sleep(start - now)
            with _LOCK:
                # A pause that began while this call waited takes its slot.
                if time.monotonic() >= self._paused_until:
                    return

    def _pause(self, seconds: float) -> None:
        """Holds back every call of this gateway, waiting ones included, so
        that its threads do not each meet the same refusal."""
        with _LOCK:
            self._paused_until = max(self._paused_until, time.monotonic() + seconds)

    def _call(
        self,
        method: str,
        path: str,
        read: Callable[[requests.Response], T],
        *,
        scope: str = _DATA_SCOPE,
        authorized: bool = True,
        params: dict[str, str] | None = None,
        body: dict[str, JsonValue] | None = None,
        form: dict[str, str] | None = None,
    ) -> T:
        """One request with its answer read by `read`. A timeout, a lost
        connection or a 5xx is tried again, also when it happens while the
        answer is read. A 429 waits for the time DealCloud names. `authorized`
        is False only for the token request, which buys a token for `scope`."""
        base_url = self._base_url()
        renewed_token = False
        failures = 0
        refusals = 0
        waited = 0.0
        while True:
            is_last_attempt = failures == _MAX_ATTEMPTS - 1
            token: str | None = self._token(scope) if authorized else None
            self._wait_for_turn()
            try:
                response = _send(
                    base_url,
                    method,
                    path,
                    token=token,
                    params=params,
                    body=body,
                    form=form,
                )
                if _succeeded(response):
                    return read(response)
                detail: str = _error_detail(response)
            except requests.Timeout as e:
                if is_last_attempt:
                    raise TimedOutValidationError(
                        f"DealCloud did not answer {method} {path} in time."
                    ) from e
                failures += 1
                continue
            except requests.RequestException as e:
                if is_last_attempt:
                    raise UnreachableValidationError(
                        f"Onyx cannot connect to DealCloud for {method} {path}: {e}"
                    ) from e
                failures += 1
                continue
            except ValueError as e:
                raise DealCloudApiError(
                    f"Onyx cannot read DealCloud's answer to {method} {path}: {e}",
                    status_code=None,
                    method=method,
                    url=path,
                ) from e

            status: int = response.status_code
            if status == 429:
                refusals += 1
                wait: float = bound_server_wait(
                    _rate_limit_wait_seconds(response), "dealcloud"
                )
                waited += wait
                if (
                    refusals > _MAX_RATE_LIMIT_WAITS
                    or waited > _MAX_RATE_LIMIT_WAIT_SECONDS
                ):
                    # Every later call would wait out the same limit, so the
                    # run stops.
                    raise RateLimitedValidationError(
                        f"DealCloud kept rate limiting {method} {path}",
                        summary="DealCloud rate limited Onyx",
                    )
                self._pause(wait)
                continue
            if status >= 500 and not is_last_attempt:
                time.sleep(2.0**failures)
                failures += 1
                continue
            if not authorized and status in _TOKEN_REJECTED_STATUSES:
                if scope == _USER_MANAGEMENT_SCOPE:
                    raise InsufficientPermissionsError(
                        "DealCloud gave the API user no user management token. "
                        "Give the user's group the User Management capability."
                    )
                raise CredentialInvalidError(
                    "DealCloud rejected the client ID or API key. Check both, and "
                    "that the user's group has the API capability."
                )
            if status == 401:
                # DealCloud can drop a token before expires_in, so one renewal
                # is tried.
                if token is not None and not renewed_token:
                    renewed_token = True
                    self._drop_token(scope, token)
                    continue
                raise CredentialInvalidError(
                    "DealCloud rejected the API user's token. Check the client "
                    "ID and API key."
                )
            if status == 403:
                raise InsufficientPermissionsError(
                    f"The DealCloud API user cannot call {method} {path}: {detail}"
                )
            raise DealCloudApiError(
                f"DealCloud answered {status} to {method} {path}",
                status_code=status,
                method=method,
                url=path,
                body=detail,
            )

    def _buy_token(self, scope: str) -> tuple[str, float]:
        credentials: dict[str, Any] = self.credentials_provider.get_credentials()
        client_id: str | None = credentials.get(DEALCLOUD_CLIENT_ID)
        api_key: str | None = credentials.get(DEALCLOUD_API_KEY)
        if not client_id or not api_key:
            raise ConnectorMissingCredentialError("DealCloud")
        body: dict[str, Any] = self._call(
            "POST",
            _TOKEN_PATH,
            _read_json,
            scope=scope,
            authorized=False,
            form={
                "grant_type": "client_credentials",
                "scope": scope,
                "client_id": client_id,
                "client_secret": api_key,
            },
        )
        return (
            body["access_token"],
            time.monotonic()
            + float(body["expires_in"])
            - _TOKEN_REFRESH_MARGIN_SECONDS,
        )

    def _token(self, scope: str) -> str:
        cached = (self._token_cache or {}).get(scope)
        if cached is not None and time.monotonic() < cached[1]:
            return cached[0]
        with self._token_lock():
            if self._token_cache is None:
                self._token_cache = {}
            cached = self._token_cache.get(scope)
            if cached is None or time.monotonic() >= cached[1]:
                cached = self._token_cache[scope] = self._buy_token(scope)
            return cached[0]

    def _drop_token(self, scope: str, token: str) -> None:
        with self._token_lock():
            cached = (self._token_cache or {}).get(scope)
            if self._token_cache is not None and cached and cached[0] == token:
                del self._token_cache[scope]

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def list_entry_types(self) -> list[DealCloudEntryType]:
        return [
            DealCloudEntryType.model_validate(entry_type)
            for entry_type in self._call("GET", _SCHEMA_PATH, _read_json)
        ]

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def list_fields(self, *, entry_type_id: int) -> list[DealCloudField]:
        return [
            DealCloudField.model_validate(field)
            for field in self._call(
                "GET", f"{_SCHEMA_PATH}/{entry_type_id}/fields", _read_json
            )
        ]

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def list_entry_ids(self, *, entry_type_id: int) -> list[int]:
        """The id of every entry of an object, ascending. DealCloud returns the
        whole list in one answer, so the walk has no pages to drift between."""
        return self._call(
            "GET", f"{_DATA_PATH}/{entry_type_id}/entries", _listed_entry_ids
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def list_changed_entry_ids(
        self, *, entry_type_id: int, modified_since: datetime
    ) -> list[int]:
        """Ascending ids of the entries changed since a time and still
        present, calculated changes included. DealCloud keeps this history
        for 6 months."""
        return self._call(
            "GET",
            f"{_DATA_PATH}/{entry_type_id}/entries/allHistory",
            _listed_entry_ids,
            params={"modifiedSince": _to_modified_since(modified_since)},
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.BOTH,
    )
    def get_rows(
        self, *, entry_type_id: int, entry_ids: list[int]
    ) -> list[DealCloudRow]:
        """The rows of the given entries, with every field. An entry deleted
        since it was listed is left out, and one too large to read comes back
        marked. Reference values carry the URL of the entry they name."""
        try:
            answer: dict[str, Any] = self._call(
                "POST",
                f"{_DATA_PATH}/rows/query/{entry_type_id}",
                _read_json,
                body={
                    # The form DealCloud documents for reading entries by id.
                    "query": f"{_ROW_ENTRY_ID_KEY} in ({','.join(map(str, entry_ids))})",
                    "limit": len(entry_ids),
                    "skip": 0,
                    "wrapIntoArrays": True,
                    "resolveReferenceUrls": True,
                },
            )
        except DealCloudAnswerTooLargeError:
            if len(entry_ids) == 1:
                # Raising would stop the run at this entry on every retry.
                return [
                    DealCloudRow(entry_id=entry_ids[0], values={}, is_too_large=True)
                ]
            return self._rows_in_halves(entry_type_id, entry_ids)
        rows: list[dict[str, Any]] = answer.get("rows", [])
        matched = int(answer.get("totalRecords", 0))
        if len(rows) < matched <= len(entry_ids):
            # DealCloud matched more rows than it returned, so its page is
            # smaller than the batch.
            if len(entry_ids) == 1:
                raise DealCloudApiError(
                    f"DealCloud matched entry {entry_ids[0]} but returned no row for it",
                    status_code=None,
                )
            return self._rows_in_halves(entry_type_id, entry_ids)
        return [
            DealCloudRow(
                entry_id=row[_ROW_ENTRY_ID_KEY],
                values={
                    key: value for key, value in row.items() if key != _ROW_ENTRY_ID_KEY
                },
            )
            for row in rows
        ]

    def _rows_in_halves(
        self, entry_type_id: int, entry_ids: list[int]
    ) -> list[DealCloudRow]:
        """Reads a batch that DealCloud did not answer in full as two smaller
        ones, which needs no offset paging."""
        middle = len(entry_ids) // 2
        return self.get_rows(
            entry_type_id=entry_type_id, entry_ids=entry_ids[:middle]
        ) + self.get_rows(entry_type_id=entry_type_id, entry_ids=entry_ids[middle:])

    @source_operation(
        capabilities=(CredentialCapability.EXTERNAL_GROUP_SYNC,),
        consumes=OperationConsumes.BOTH,
    )
    def list_active_users(self) -> list[DealCloudUser]:
        return [
            DealCloudUser.model_validate(user)
            for user in self._call(
                "GET", "/v4/schema/users", _read_json, params={"activeOnly": "true"}
            )
        ]

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.BOTH,
    )
    def list_user_groups(self) -> list[DealCloudUserGroupRef]:
        """Every user group of the site, keyed by id so that a group seen on
        two pages counts once. Needs the User Management capability."""
        groups: dict[int, DealCloudUserGroupRef] = {}
        for page_number in range(1, _MAX_USER_GROUP_PAGES + 1):
            page: list[dict[str, Any]] = self._call(
                "GET",
                _USER_GROUP_PATH,
                _read_json,
                scope=_USER_MANAGEMENT_SCOPE,
                params={
                    "pageNumber": str(page_number),
                    "pageSize": str(_USER_GROUP_PAGE_SIZE),
                },
            )
            for group in page:
                ref = DealCloudUserGroupRef.model_validate(group)
                groups[ref.id] = ref
            if len(page) < _USER_GROUP_PAGE_SIZE:
                return list(groups.values())
        raise RuntimeError(
            f"DealCloud kept paging user groups past {_MAX_USER_GROUP_PAGES} pages"
        )

    @source_operation(
        capabilities=(
            CredentialCapability.DOC_PERMISSION_SYNC,
            CredentialCapability.EXTERNAL_GROUP_SYNC,
        ),
        consumes=OperationConsumes.BOTH,
    )
    def get_user_group(self, *, group_id: int) -> DealCloudUserGroup:
        return DealCloudUserGroup.model_validate(
            self._call(
                "GET",
                f"{_USER_GROUP_PATH}/{group_id}",
                _read_json,
                scope=_USER_MANAGEMENT_SCOPE,
            )
        )
