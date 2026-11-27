"""Zendesk source-operations gateway: every Zendesk REST call lives here.

The credential carries the account's subdomain, an agent's email and an API
token. Requests authenticate as `<email>/token`.
"""

import threading
import time
from collections.abc import Callable
from typing import Any, ClassVar

import requests

from onyx.configs.app_configs import REQUEST_TIMEOUT_SECONDS
from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.cross_connector_utils.rate_limit_wrapper import rate_limit_builder
from onyx.connectors.exceptions import (
    CredentialExpiredError,
    InsufficientPermissionsError,
)
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.connectors.zendesk.models import ZendeskPageResponse, ZendeskUser
from onyx.utils.retry_after import parse_retry_after_seconds
from onyx.utils.retry_wrapper import retry_builder

MAX_PAGE_SIZE = 30  # Zendesk API maximum
# Zendesk's maximum for comment listings.
_COMMENT_PAGE_SIZE = 100
# Upper bound on how long we'll honor a server-provided Retry-After.
_MAX_RETRY_AFTER_SLEEP_SECONDS = 60

ZENDESK_SUBDOMAIN: str = "zendesk_subdomain"
ZENDESK_EMAIL: str = "zendesk_email"
ZENDESK_TOKEN: str = "zendesk_token"


class ZendeskSupportInactiveError(ValueError):
    """The account has no active Support product, so it has no tickets."""


class ZendeskRequestError(RuntimeError):
    """Zendesk answered with an error status other than 401 or 403, or could
    not be reached (no status then)."""

    def __init__(self, status_code: int | None, detail: str) -> None:
        super().__init__(f"Zendesk request failed ({status_code}): {detail}")
        self.status_code = status_code


def next_cursor(meta: dict[str, Any], current: str | None) -> str:
    """The cursor of the next page. A page that claims more items but repeats
    or omits its cursor would make the walk loop forever."""
    cursor: str | None = meta.get("after_cursor")
    if not cursor or cursor == current:
        raise ZendeskRequestError(None, "a page claimed more items but did not advance")
    return cursor


def subdomain_from_credential(value: str) -> str:
    """The credential field holds a subdomain or the account's whole URL."""
    host: str = value.strip().split("://")[-1].split("/")[0]
    return host.removeprefix("www.").split(".zendesk.com")[0]


def _is_transient(error: BaseException) -> bool:
    """Retry rate limits, server errors and network failures. Other client
    errors (bad token, missing resource) fail at once."""
    if isinstance(error, requests.exceptions.HTTPError):
        status_code: int | None = (
            error.response.status_code if error.response is not None else None
        )
        return status_code is None or status_code == 429 or status_code >= 500
    return isinstance(error, requests.exceptions.RequestException)


def _make_request_function(
    base_url: str, auth: tuple[str, str], max_calls_per_minute: int | None
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    @retry_builder(retry_if=_is_transient)
    @(
        rate_limit_builder(max_calls=max_calls_per_minute, period=60)
        if max_calls_per_minute
        else lambda x: x
    )
    def make_request(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        response = requests.get(
            f"{base_url}/{endpoint}",
            auth=auth,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        if response.status_code == 429:
            retry_after = parse_retry_after_seconds(response.headers.get("Retry-After"))
            if retry_after is not None:
                # Sleep for the duration indicated by the Retry-After header
                time.sleep(min(retry_after, _MAX_RETRY_AFTER_SLEEP_SECONDS))

        elif (
            response.status_code == 403
            and response.json().get("error") == "SupportProductInactive"
        ):
            return response.json()

        response.raise_for_status()
        return response.json()

    return make_request


class ZendeskSourceOperations(SourceOperations):
    source = DocumentSource.ZENDESK
    sdk_modules = ("requests",)
    config_keys = frozenset({"calls_per_minute"})

    _request_cache: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
    # Shared by every instance. It guards only the one-time build of an
    # instance's request function.
    _request_lock: ClassVar[threading.Lock] = threading.Lock()

    def _request_raw(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        """One request function per gateway, so its rate limit is shared by
        every caller of this gateway."""
        if self._request_cache is None:
            with self._request_lock:
                if self._request_cache is None:
                    self._request_cache = self._build_request_function()
        return self._request_cache(endpoint, params)

    def _request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._request_raw(endpoint, params)
        except requests.exceptions.HTTPError as e:
            status_code: int = e.response.status_code
            if status_code == 401:
                raise CredentialExpiredError(
                    "Your Zendesk credentials appear to be invalid or expired (HTTP 401)."
                ) from e
            if status_code == 403:
                raise InsufficientPermissionsError(
                    "Your Zendesk token does not have sufficient permissions (HTTP 403)."
                ) from e
            raise ZendeskRequestError(status_code, str(e)) from e
        except requests.exceptions.RequestException as e:
            raise ZendeskRequestError(None, str(e)) from e

    def _build_request_function(
        self,
    ) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
        credentials: dict[str, Any] = self.credentials_provider.get_credentials()
        subdomain: str | None = credentials.get(ZENDESK_SUBDOMAIN)
        email: str | None = credentials.get(ZENDESK_EMAIL)
        token: str | None = credentials.get(ZENDESK_TOKEN)
        if not subdomain or not email or not token:
            raise ConnectorMissingCredentialError("Zendesk")
        calls_per_minute: int | None = (self.connector_specific_config or {}).get(
            "calls_per_minute"
        )
        return _make_request_function(
            f"https://{subdomain_from_credential(subdomain)}.zendesk.com/api/v2",
            (f"{email}/token", token),
            calls_per_minute,
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_me(self) -> ZendeskUser:
        """The user the token authenticates as. Zendesk answers a request it
        could not authenticate with an anonymous user that has no id."""
        user: dict[str, Any] = self._request("users/me", {})["user"]
        if user.get("id") is None:
            raise CredentialExpiredError(
                "Zendesk did not accept the email and API token."
            )
        return ZendeskUser.model_validate(user)

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_content_tags(
        self, *, page_size: int = MAX_PAGE_SIZE, max_pages: int | None = None
    ) -> dict[str, str]:
        """Help Center content tag names by id."""
        content_tags: dict[str, str] = {}
        params: dict[str, Any] = {"page[size]": page_size}
        pages: int = 0
        while True:
            data = self._request("guide/content_tags", params)
            pages += 1
            for tag in data.get("records", []):
                content_tags[tag["id"]] = tag["name"]
            if not data.get("meta", {}).get("has_more", False) or (
                max_pages is not None and pages >= max_pages
            ):
                return content_tags
            params["page[after]"] = next_cursor(data["meta"], params.get("page[after]"))

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_article_page(
        self,
        *,
        start_time: int | None = None,
        after_cursor: str | None = None,
        page_size: int = MAX_PAGE_SIZE,
    ) -> ZendeskPageResponse:
        """One page of Help Center articles, oldest update first."""
        params: dict[str, Any] = {
            "page[size]": page_size,
            "sort_by": "updated_at",
            "sort_order": "asc",
        }
        if start_time is not None:
            params["start_time"] = start_time
        if after_cursor is not None:
            params["page[after]"] = after_cursor
        data = self._request("help_center/articles", params)
        return ZendeskPageResponse(
            data=data["articles"],
            meta=data["meta"],
            has_more=bool(data["meta"].get("has_more", False)),
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_ticket_page(
        self, *, start_time: int | None = None, per_page: int | None = None
    ) -> ZendeskPageResponse:
        """One page of the incremental ticket export (up to 1,000 tickets unless
        per_page is set)."""
        # NOTE: for some reason zendesk doesn't seem to be respecting the start_time
        # param in my local testing with very few tickets. We'll look into it if this
        # becomes an issue in larger deployments
        params: dict[str, Any] = {"start_time": start_time or 0}
        if per_page is not None:
            params["per_page"] = per_page
        data = self._request("incremental/tickets.json", params)
        if data.get("error") == "SupportProductInactive":
            raise ZendeskSupportInactiveError(
                "Zendesk Support Product is not active for this account, No tickets to index"
            )
        return ZendeskPageResponse(
            data=data["tickets"],
            meta={"end_time": data["end_time"]},
            has_more=not bool(data.get("end_of_stream", False)),
        )

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def get_user(self, *, user_id: str | int) -> ZendeskUser | None:
        """One user, or None when Zendesk cannot return them."""
        try:
            data = self._request_raw(f"users/{user_id}", {})
        except requests.exceptions.HTTPError:
            return None
        user: dict[str, Any] | None = data.get("user")
        return ZendeskUser.model_validate(user) if user else None

    @source_operation(
        capabilities=(CredentialCapability.INDEXING,),
        consumes=OperationConsumes.CREDENTIAL,
    )
    def list_ticket_comments(self, *, ticket_id: str | int) -> list[dict[str, Any]]:
        """Every comment of one ticket, internal notes included."""
        comments: list[dict[str, Any]] = []
        params: dict[str, Any] = {"page[size]": _COMMENT_PAGE_SIZE}
        while True:
            data = self._request(f"tickets/{ticket_id}/comments", params)
            comments.extend(data.get("comments", []))
            if not data.get("meta", {}).get("has_more", False):
                return comments
            params["page[after]"] = next_cursor(data["meta"], params.get("page[after]"))
