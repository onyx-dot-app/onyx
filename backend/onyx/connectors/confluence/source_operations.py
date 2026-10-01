"""Confluence source-operations gateway: every Confluence API call lives here.

This is the single file in ``onyx/connectors/confluence/`` and
``ee/onyx/external_permissions/confluence/`` allowed to import ``atlassian``
(the import-fence test enforces it). The gateway builds its clients lazily from
the credential plus the bound config fields (``wiki_base``, ``is_cloud``,
``scoped_token``), and exposes each remote call as a stamped operation that
returns plain data.

``_OnyxConfluence`` is the transport: rate-limit retries, OAuth refresh, and the
pagination engine. The EE perm-sync modules still call it directly through the
temporary ``onyx_confluence`` re-export; #15454 moves those calls to operations.

Pagination notes: the Cloud ``search/user`` and ``user/memberof`` endpoints use
offset pagination, while page retrieval uses cursors. The default for Cloud is
cursor pagination; pass ``force_offset_pagination`` for an API that does not
return ``_links.next``.
"""

import json
import threading
import time
from collections.abc import Callable, Generator, Iterator
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, TypeVar, cast
from urllib.parse import quote

import requests
from atlassian import Confluence
from atlassian.errors import ApiError
from requests import HTTPError

from onyx.configs.app_configs import (
    CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE,
    OAUTH_CONFLUENCE_CLOUD_CLIENT_ID,
    OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET,
)
from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.connectors.confluence.config import ConfluenceCredentialBinding
from onyx.connectors.confluence.models import ConfluenceUser
from onyx.connectors.confluence.user_profile_override import (
    process_confluence_user_profiles_override,
)
from onyx.connectors.confluence.utils import (
    _handle_http_error,
    build_cql_url,
    confluence_refresh_tokens,
    get_start_param_from_url,
    update_param_in_path,
)
from onyx.connectors.cross_connector_utils.miscellaneous_utils import scoped_url
from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
)
from onyx.connectors.interfaces import CredentialsProviderInterface
from onyx.connectors.source_operations import (
    OperationConsumes,
    SourceOperations,
    source_operation,
)
from onyx.redis.redis_pool import get_redis_client
from onyx.redis.tenant_redis_client import TenantRedisClient
from onyx.utils.logger import setup_logger

logger = setup_logger()

_T = TypeVar("_T")

_UNTESTED = "Capability checks land in #15455."

# Client settings for the connection probe and for all later calls.
_PROBE_KWARGS: dict[str, Any] = {"max_backoff_retries": 6, "max_backoff_seconds": 10}
_FINAL_KWARGS: dict[str, Any] = {"max_backoff_retries": 10, "max_backoff_seconds": 60}
# Timeout of the client behind ``fast=True`` operations (validation).
_FAST_TIMEOUT = 3

_FIND_PAGE_EXPAND = "body.storage.value"

# Set by the Confluence Cloud OAuth finalize step.
_OAUTH_SITE_KEYS = ("cloud_name", "wiki_base")

# https://jira.atlassian.com/browse/CONFCLOUD-76433
_PROBLEMATIC_EXPANSIONS = "body.storage.value"
_REPLACEMENT_EXPANSIONS = "body.view.value"

# CONFCLOUD-77618 / CONFCLOUD-76424: ancestor-restrictions expand on
# content/search 404s the whole batch when an ancestor is unreadable
# (draft / outdated / trashed). We detect the body signature and raise.
_ANCESTOR_RESTRICTIONS_EXPAND_PREFIX = "ancestors.restrictions.read.restrictions."
_CONFCLOUD_77618_404_BODY_SIGNATURES = (
    "No content with id",
    "Cannot find content. Outdated version/old_draft/trashed",
)

_USER_NOT_FOUND = "Unknown Confluence User"
# Keyed by (instance base url, user id): one worker process can serve several
# Confluence instances, and DC userkeys are unique only per instance.
_USER_ID_TO_DISPLAY_NAME_CACHE: dict[tuple[str, str], str | None] = {}
_DEFAULT_PAGINATION_LIMIT = 1000
_MINIMUM_PAGINATION_LIMIT = 5

_SERVER_ERROR_CODES = {500, 502, 503, 504}
_FORBIDDEN_STATUS = 403

_CONFLUENCE_SPACES_API_V1 = "rest/api/space"
_CONFLUENCE_SPACES_API_V2 = "wiki/api/v2/spaces"

# Atlassian KB documenting how Secure Administrator Sessions (WebSudo) breaks
# admin JSON-RPC calls. Surfaced in the validation error so admins can act on
# it without our help.
_WEBSUDO_KB_URL = (
    "https://support.atlassian.com/confluence/kb/"
    "json-rpc-api-request-returns-websudorequiredexception-on-confluence/"
)
# Cap how much of an unparseable JSON-RPC response body we put in the error
# message. WebSudo / login HTML pages are well under this; the cap is a
# defense against a runaway response (e.g. a multi-MB error page) ending up
# in our logs and validation surface.
_JSONRPC_ERROR_BODY_SNIPPET_CHARS = 1000

# DC 9.1.0 is the first DC release with the REST API for space permissions
# (CONFSERVER-78176). Older DC versions still need the legacy JSON-RPC
# fallback. Server / Data Center only -- Cloud has its own permissions API
# and is branched on `is_cloud` upstream of any version check.
_MIN_DC_VERSION_FOR_REST_SPACE_PERMISSIONS: tuple[int, int] = (9, 1)

# Atlassian's documented Confluence DC endpoint for build information,
# under the "Server Information" REST API group. Returns a JSON object
# whose top-level `version` field is the upstream Confluence version
# (e.g. "10.2.10"). Confirmed present in the v8.4, v9.3, and v10.x
# DC REST API references; we previously probed the Jira-style
# `/rest/api/serverInfo` slug, which 404s on Confluence DC 10.x.
_DC_SERVER_INFORMATION_PATH = "rest/api/server-information"


class Confcloud77618Error(Exception):
    """Signal to the perm-sync caller that the ancestor-restrictions
    expand 404'd on a draft / outdated / trashed ancestor and the run
    must restart with per-page restriction lookups."""

    def __init__(self, url: str, body: str) -> None:
        super().__init__(
            f"CONFCLOUD-77618: ancestor-restrictions expand 404 from "
            f"{url}: {body[:500]}"
        )
        self.url = url
        self.body = body


class ConfluenceRetriesExhaustedError(RuntimeError):
    """Every attempt of a Confluence call failed with a retryable error."""

    def __init__(self, message: str, *, last_status_code: int | None) -> None:
        super().__init__(message)
        self.last_status_code = last_status_code


class ConfluenceRestSpacePermissionsNotAvailableError(Exception):
    """Raised by REST-API space-permissions calls when the endpoint is missing
    on the upstream Confluence DC instance (e.g. DC < 9.1.0 returning 404).

    Callers use this as a signal to fall back to the legacy JSON-RPC path.
    """


def _is_confcloud_77618_response(response: requests.Response) -> bool:
    """Body-signature match for the CONFCLOUD-77618 / CONFCLOUD-76424 404
    so unrelated 404s still propagate."""
    if response.status_code != 404:
        return False
    body = response.text
    return any(sig in body for sig in _CONFCLOUD_77618_404_BODY_SIGNATURES)


class _OnyxConfluence:
    """Wraps the SDK ``Confluence`` client.

    Adds CQL pagination with expansions, which the SDK does not support well.
    Every public SDK method reached through ``__getattr__`` runs inside
    ``_call_with_retries`` (rate-limit retries and OAuth refresh).
    """

    CREDENTIAL_PREFIX = "connector:confluence:credential"
    CREDENTIAL_TTL = 300  # 5 min
    PROBE_TIMEOUT = 5  # 5 seconds

    def __init__(
        self,
        is_cloud: bool,
        url: str,
        credentials_provider: CredentialsProviderInterface,
        timeout: int | None = None,
        scoped_token: bool = False,
        # should generally not be passed in, but making it overridable for
        # easier testing
        confluence_user_profiles_override: list[dict[str, str]] | None = (
            CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE
        ),
        # The resolved scoped-token API URL, so clients of one gateway share
        # one tenant_info lookup.
        scoped_api_url: str | None = None,
    ) -> None:
        self.base_url = url
        if scoped_token:
            url = scoped_api_url or scoped_url(url, "confluence")

        self._is_cloud = is_cloud
        self._url = url.rstrip("/")
        self._credentials_provider = credentials_provider
        self.scoped_token = scoped_token
        self.redis_client: TenantRedisClient | None = None
        self.static_credentials: dict[str, Any] | None = None
        if self._credentials_provider.is_dynamic():
            self.redis_client = get_redis_client(
                tenant_id=credentials_provider.get_tenant_id()
            )
        else:
            self.static_credentials = self._credentials_provider.get_credentials()

        self._confluence = Confluence(url)
        self.credential_key: str = (
            self.CREDENTIAL_PREFIX
            + f":credential_{self._credentials_provider.get_provider_key()}"
        )

        self._kwargs: Any = None

        self.shared_base_kwargs: dict[str, str | int | bool] = {
            "api_version": "cloud" if is_cloud else "latest",
            "backoff_and_retry": False,
            "cloud": is_cloud,
        }
        if timeout:
            self.shared_base_kwargs["timeout"] = timeout

        self._confluence_user_profiles_override = (
            process_confluence_user_profiles_override(confluence_user_profiles_override)
            if confluence_user_profiles_override
            else None
        )

        # Cached result of the server-information probe, populated on
        # first `get_server_version()` call. _server_version_probed=True
        # with _server_version=None means "we tried and the probe
        # failed", so we don't keep retrying every space-permissions sync.
        self._server_version: tuple[int, int] | None = None
        self._server_version_probed: bool = False

    def _renew_credentials(self) -> tuple[dict[str, Any], bool]:
        """credential_json - the current json credentials
        Returns a tuple
        1. The up to date credentials
        2. True if the credentials were updated

        This method is intended to be used within a distributed lock.
        Lock, call this, update credentials if the tokens were refreshed, then release
        """
        # static credentials are preloaded, so no locking/redis required
        if self.static_credentials:
            return self.static_credentials, False

        if not self.redis_client:
            raise RuntimeError("self.redis_client is None")

        # dynamic credentials need locking
        # check redis first, then fallback to the DB
        credential_bytes = self.redis_client.get(self.credential_key)
        if credential_bytes is not None:
            credential_str = credential_bytes.decode("utf-8")
            credential_json: dict[str, Any] = json.loads(credential_str)
        else:
            credential_json = self._credentials_provider.get_credentials()

        if "confluence_refresh_token" not in credential_json:
            # static credentials ... cache them permanently and return
            self.static_credentials = credential_json
            return credential_json, False

        if not OAUTH_CONFLUENCE_CLOUD_CLIENT_ID:
            raise RuntimeError("OAUTH_CONFLUENCE_CLOUD_CLIENT_ID must be set!")

        if not OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET:
            raise RuntimeError("OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET must be set!")

        # check if we should refresh tokens. we're deciding to refresh halfway
        # to expiration
        now = datetime.now(timezone.utc)
        created_at = datetime.fromisoformat(credential_json["created_at"])
        expires_in: int = credential_json["expires_in"]
        renew_at = created_at + timedelta(seconds=expires_in // 2)
        if now <= renew_at:
            # cached/current credentials are reasonably up to date
            return credential_json, False

        # we need to refresh
        logger.info("Renewing Confluence Cloud credentials...")
        new_credentials = {
            # The refresh response has no site info; keep what the OAuth
            # finalize step stored.
            **{
                key: credential_json[key]
                for key in _OAUTH_SITE_KEYS
                if key in credential_json
            },
            **confluence_refresh_tokens(
                OAUTH_CONFLUENCE_CLOUD_CLIENT_ID,
                OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET,
                credential_json["cloud_id"],
                credential_json["confluence_refresh_token"],
            ),
        }

        # store the new credentials to redis and to the db thru the provider
        # redis: we use a 5 min TTL because we are given a 10 minute grace period
        # when keys are rotated. it's easier to expire the cached credentials
        # reasonably frequently rather than trying to handle strong synchronization
        # between the db and redis everywhere the credentials might be updated
        new_credential_str = json.dumps(new_credentials)
        self.redis_client.set(
            self.credential_key, new_credential_str, nx=True, ex=self.CREDENTIAL_TTL
        )
        self._credentials_provider.set_credentials(new_credentials)

        return new_credentials, True

    @staticmethod
    def _make_oauth2_dict(credentials: dict[str, Any]) -> dict[str, Any]:
        oauth2_dict: dict[str, Any] = {}
        if "confluence_refresh_token" in credentials:
            oauth2_dict["client_id"] = OAUTH_CONFLUENCE_CLOUD_CLIENT_ID
            oauth2_dict["token"] = {}
            oauth2_dict["token"]["access_token"] = credentials[
                "confluence_access_token"
            ]
        return oauth2_dict

    def _build_spaces_url(
        self,
        is_v2: bool,
        base_url: str,
        limit: int,
        space_keys: list[str] | None,
        start: int | None = None,
    ) -> str:
        """Build URL for Confluence spaces API with query parameters."""
        key_param = "keys" if is_v2 else "spaceKey"

        params = [f"limit={limit}"]
        if space_keys:
            params.append(f"{key_param}={','.join(space_keys)}")
        if start is not None and not is_v2:
            params.append(f"start={start}")

        return f"{base_url}?{'&'.join(params)}"

    def _paginate_spaces_for_endpoint(
        self,
        is_v2: bool,
        base_url: str,
        limit: int,
        space_keys: list[str] | None,
    ) -> Iterator[dict[str, Any]]:
        """Paginate spaces. Server stops on missing ``_links.next``
        (and empty ``results``, defensively). Don't stop on
        ``len(results) < limit``: ``/rest/api/space`` on DC caps at
        ``DefaultRestSpaceManager.MAX_SIZE`` (#4129). ``start`` is
        re-derived locally; Confluence under-counts it on capped pages
        and CONFSERVER-95272/-95312 returns records past the true end.
        """
        start = 0
        url = self._build_spaces_url(
            is_v2, base_url, limit, space_keys, start if not is_v2 else None
        )

        while url:
            response = self.get(url, advanced_mode=True)
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return

            yield from results

            next_link = data.get("_links", {}).get("next", "")
            if not next_link:
                return

            if is_v2:
                url = next_link
            else:
                start += len(results)
                url = self._build_spaces_url(is_v2, base_url, limit, space_keys, start)

    def retrieve_confluence_spaces(
        self,
        space_keys: list[str] | None = None,
        limit: int = 50,
    ) -> Iterator[dict[str, str]]:
        """
        Retrieve spaces from Confluence using v2 API (Cloud) or v1 API (Server/fallback).

        Args:
            space_keys: Optional list of space keys to filter by
            limit: Results per page (default 50)

        Yields:
            Space dictionaries with keys: id, key, name, type, status, etc.

        Note:
            For Cloud instances, attempts v2 API first. If v2 returns 404,
            automatically falls back to v1 API for compatibility with older instances.
        """
        # Determine API version once
        use_v2 = self._is_cloud and not self.scoped_token
        base_url = _CONFLUENCE_SPACES_API_V2 if use_v2 else _CONFLUENCE_SPACES_API_V1

        try:
            yield from self._paginate_spaces_for_endpoint(
                use_v2, base_url, limit, space_keys
            )
        except HTTPError as e:
            if e.response.status_code == 404 and use_v2:
                logger.warning(
                    "v2 spaces API returned 404, falling back to v1 API. This may indicate an older Confluence Cloud instance."
                )
                # Fallback to v1
                yield from self._paginate_spaces_for_endpoint(
                    False, _CONFLUENCE_SPACES_API_V1, limit, space_keys
                )
            else:
                raise

    def _probe_connection(
        self,
        **kwargs: Any,
    ) -> None:
        merged_kwargs = {**self.shared_base_kwargs, **kwargs}
        # add special timeout to make sure that we don't hang indefinitely
        merged_kwargs["timeout"] = self.PROBE_TIMEOUT

        with self._credentials_provider:
            credentials, _ = self._renew_credentials()
            if self.scoped_token:
                # v2 endpoint doesn't always work with scoped tokens, use v1
                token = credentials["confluence_access_token"]
                probe_url = f"{self.base_url}/{_CONFLUENCE_SPACES_API_V1}?limit=1"
                try:
                    r = requests.get(
                        probe_url,
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=10,
                    )
                    r.raise_for_status()
                except HTTPError as e:
                    if e.response.status_code == 403:
                        logger.warning(
                            "scoped token authenticated but not valid for probe endpoint (spaces)"
                        )
                    else:
                        if "WWW-Authenticate" in e.response.headers:
                            logger.warning(
                                "WWW-Authenticate: %s",
                                e.response.headers["WWW-Authenticate"],
                            )
                            logger.warning("Full error: %s", e.response.text)
                        raise e
                return

        # Initialize connection with probe timeout settings
        self._confluence = self._initialize_connection_helper(
            credentials, **merged_kwargs
        )

        # Retrieve first space to validate connection
        spaces_iter = self.retrieve_confluence_spaces(limit=1)
        first_space = next(spaces_iter, None)

        if not first_space:
            raise RuntimeError(
                f"No spaces found at {self._url}! Check your credentials and wiki_base and make sure is_cloud is set correctly."
            )

        logger.info("Confluence probe succeeded.")

    def _initialize_connection(
        self,
        **kwargs: Any,
    ) -> None:
        """Called externally to init the connection in a thread safe manner."""
        merged_kwargs = {**self.shared_base_kwargs, **kwargs}
        with self._credentials_provider:
            credentials, _ = self._renew_credentials()
            self._confluence = self._initialize_connection_helper(
                credentials, **merged_kwargs
            )
            self._kwargs = merged_kwargs

    def _initialize_connection_helper(
        self,
        credentials: dict[str, Any],
        **kwargs: Any,
    ) -> Confluence:
        """Called internally to init the connection. Distributed locking
        to prevent multiple threads from modifying the credentials
        must be handled around this function."""

        confluence = None

        # probe connection with direct client, no retries
        if "confluence_refresh_token" in credentials:
            logger.info("Connecting to Confluence Cloud with OAuth Access Token.")

            oauth2_dict: dict[str, Any] = _OnyxConfluence._make_oauth2_dict(credentials)
            url = f"https://api.atlassian.com/ex/confluence/{credentials['cloud_id']}"
            confluence = Confluence(url=url, oauth2=oauth2_dict, **kwargs)
        else:
            logger.info(
                "Connecting to Confluence with Personal Access Token as user: %s",
                credentials["confluence_username"],
            )
            if self._is_cloud:
                confluence = Confluence(
                    url=self._url,
                    username=credentials["confluence_username"],
                    password=credentials["confluence_access_token"],
                    **kwargs,
                )
            else:
                confluence = Confluence(
                    url=self._url,
                    token=credentials["confluence_access_token"],
                    **kwargs,
                )

        return confluence

    def _sdk_url(self) -> str:
        """The SDK client's API root URL."""
        return self._confluence.url

    # https://developer.atlassian.com/cloud/confluence/rate-limiting/
    # This uses the native rate limiting option provided by the
    # confluence client and otherwise applies a simpler set of error handling.
    def _call_with_retries(
        self, call: Callable[[Confluence], _T], *, retry_forbidden: bool = True
    ) -> _T:
        """Runs ``call`` on the SDK client with OAuth refresh and retries.

        Retries a 403 (Confluence Server rate limit), 429 and 5xx as
        ``_handle_http_error`` allows. ``retry_forbidden=False`` raises a 403 at
        once. Raises ``ConfluenceRetriesExhaustedError`` when every attempt
        failed with a retryable error.
        """
        MAX_RETRIES = 5

        TIMEOUT = 600
        timeout_at = time.monotonic() + TIMEOUT
        last_status_code: int | None = None

        for attempt in range(MAX_RETRIES):
            if time.monotonic() > timeout_at:
                raise TimeoutError(
                    f"Confluence call attempts took longer than {TIMEOUT} seconds."
                )

            # we're relying more on the client to rate limit itself
            # and applying our own retries in a more specific set of circumstances
            try:
                with self._credentials_provider:
                    credentials, renewed = self._renew_credentials()
                    if renewed:
                        self._confluence = self._initialize_connection_helper(
                            credentials, **self._kwargs
                        )
                    return call(self._confluence)

            except HTTPError as e:
                if e.response is not None:
                    last_status_code = e.response.status_code
                if not retry_forbidden and last_status_code == _FORBIDDEN_STATUS:
                    raise
                delay_until = _handle_http_error(e, attempt, MAX_RETRIES)
                logger.warning(
                    "HTTPError in confluence call. Retrying in %s seconds...",
                    max(delay_until - time.monotonic(), 0),
                )
                while time.monotonic() < delay_until:
                    # in the future, check a signal here to exit
                    time.sleep(1)
            except AttributeError as e:
                # Some error within the Confluence library, unclear why it fails.
                # Users reported it to be intermittent, so just retry
                if attempt == MAX_RETRIES - 1:
                    raise e

                logger.exception(
                    "Confluence Client raised an AttributeError. Retrying..."
                )
                time.sleep(5)
        raise ConfluenceRetriesExhaustedError(
            f"Confluence call failed after {MAX_RETRIES} attempts "
            f"(last status: {last_status_code}).",
            last_status_code=last_status_code,
        )

    def _make_rate_limited_confluence_method(self, name: str) -> Callable[..., Any]:
        def call_method(confluence: Confluence, *args: Any, **kwargs: Any) -> Any:
            attr = getattr(confluence, name, None)  # ods: ignore[getattr]
            if attr is None:
                # The underlying Confluence client doesn't have this attribute
                raise AttributeError(
                    f"'{type(self).__name__}' object has no attribute '{name}'"
                )
            return attr(*args, **kwargs)

        def wrapped_call(*args: Any, **kwargs: Any) -> Any:
            return self._call_with_retries(
                lambda confluence: call_method(confluence, *args, **kwargs)
            )

        return wrapped_call

    def __getattr__(self, name: str) -> Any:
        """Dynamically intercept attribute/method access."""
        attr = getattr(self._confluence, name, None)  # ods: ignore[getattr]
        if attr is None:
            # The underlying Confluence client doesn't have this attribute
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

        # If it's not a method, just return it after ensuring token validity
        if not callable(attr):
            return attr

        # skip methods that start with "_"
        if name.startswith("_"):
            return attr

        # wrap the method with our retry handler
        return self._make_rate_limited_confluence_method(name)

    def _try_one_by_one_for_paginated_url(
        self,
        url_suffix: str,
        initial_start: int,
        limit: int,
    ) -> Generator[dict[str, Any], None, str | None]:
        """
        Go through `limit` items, starting at `initial_start` one by one (e.g. using
        `limit=1` for each call).

        If we encounter an error, we skip the item and try the next one. We will return
        the items we were able to retrieve successfully.

        Returns the expected next url_suffix. Returns None if it thinks we've hit the end.

        TODO(chris): make this yield failures as well as successes.
        TODO(chris): make this work for confluence cloud somehow.
        """
        if self._is_cloud:
            raise RuntimeError("This method is not implemented for Confluence Cloud.")

        found_empty_page = False
        temp_url_suffix = url_suffix

        for ind in range(limit):
            try:
                temp_url_suffix = update_param_in_path(
                    url_suffix, "start", str(initial_start + ind)
                )
                temp_url_suffix = update_param_in_path(temp_url_suffix, "limit", "1")
                logger.info("Making recovery confluence call to %s", temp_url_suffix)
                raw_response = self.get(path=temp_url_suffix, advanced_mode=True)
                raw_response.raise_for_status()

                latest_results = raw_response.json().get("results", [])
                yield from latest_results

                if not latest_results:
                    # no more results, break out of the loop
                    logger.info(
                        "No results found for call '%s'Stopping pagination.",
                        temp_url_suffix,
                    )
                    found_empty_page = True
                    break
            except Exception:
                logger.exception(
                    "Error in confluence call to %s. Continuing.",
                    temp_url_suffix,
                )

        if found_empty_page:
            return None

        # if we got here, we successfully tried `limit` items
        return update_param_in_path(url_suffix, "start", str(initial_start + limit))

    def _paginate_url(
        self,
        url_suffix: str,
        limit: int | None = None,
        # Called with the next url to use to get the next page
        next_page_callback: Callable[[str], None] | None = None,
        force_offset_pagination: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """
        This will paginate through the top level query.
        """
        if not limit:
            limit = _DEFAULT_PAGINATION_LIMIT

        current_limit = limit
        url_suffix = update_param_in_path(url_suffix, "limit", str(current_limit))

        while url_suffix:
            logger.debug("Making confluence call to %s", url_suffix)
            try:
                # Only pass params if they're not already in the URL to avoid duplicate
                # params accumulating. Confluence's _links.next already includes these.
                params = {}
                if "body-format=" not in url_suffix:
                    params["body-format"] = "atlas_doc_format"
                if "expand=" not in url_suffix:
                    params["expand"] = "body.atlas_doc_format"

                raw_response = self.get(
                    path=url_suffix,
                    advanced_mode=True,
                    params=params,
                )
            except Exception as e:
                logger.exception("Error in confluence call to %s", url_suffix)
                raise e

            try:
                raw_response.raise_for_status()
            except Exception as e:
                logger.warning("Error in confluence call to %s", url_suffix)

                # If the problematic expansion is in the url, replace it
                # with the replacement expansion and try again
                # If that fails, raise the error
                if _PROBLEMATIC_EXPANSIONS in url_suffix:
                    logger.warning(
                        "Replacing %s with %s and trying again.",
                        _PROBLEMATIC_EXPANSIONS,
                        _REPLACEMENT_EXPANSIONS,
                    )
                    url_suffix = url_suffix.replace(
                        _PROBLEMATIC_EXPANSIONS,
                        _REPLACEMENT_EXPANSIONS,
                    )
                    continue

                # CONFCLOUD-77618 / 76424: typed signal so the perm-sync
                # caller can restart in per-page restriction-fetch mode.
                if (
                    _ANCESTOR_RESTRICTIONS_EXPAND_PREFIX in url_suffix
                    and _is_confcloud_77618_response(raw_response)
                ):
                    raise Confcloud77618Error(
                        url=url_suffix, body=raw_response.text
                    ) from e

                if raw_response.status_code in _SERVER_ERROR_CODES:
                    # Try reducing the page size -- Confluence often times out
                    # on large result sets (especially Cloud 504s).
                    if current_limit > _MINIMUM_PAGINATION_LIMIT:
                        old_limit = current_limit
                        current_limit = max(
                            current_limit // 2, _MINIMUM_PAGINATION_LIMIT
                        )
                        logger.warning(
                            "Confluence returned %s. "
                            "Reducing limit from %s to %s "
                            "and retrying.",
                            raw_response.status_code,
                            old_limit,
                            current_limit,
                        )
                        url_suffix = update_param_in_path(
                            url_suffix, "limit", str(current_limit)
                        )
                        continue

                    # Limit reduction exhausted -- for Server, fall back to
                    # one-by-one offset pagination as a last resort.
                    if not self._is_cloud:
                        initial_start = get_start_param_from_url(url_suffix)
                        # this will just yield the successful items from the batch
                        new_url_suffix = yield from self._try_one_by_one_for_paginated_url(
                            url_suffix,
                            initial_start=initial_start,
                            limit=current_limit,
                        )
                        # this means we ran into an empty page
                        if new_url_suffix is None:
                            if next_page_callback:
                                next_page_callback("")
                            break

                        url_suffix = new_url_suffix
                        continue

                    logger.exception(
                        "Error in confluence call to %s "
                        "after reducing limit to %s.\n"
                        "Raw Response Text: %s\n"
                        "Error: %s\n",
                        url_suffix,
                        current_limit,
                        raw_response.text,
                        e,
                    )
                    raise

                logger.exception(
                    "Error in confluence call to %s \n"
                    "Raw Response Text: %s \n"
                    "Full Response: %s \n"
                    "Error: %s \n",
                    url_suffix,
                    raw_response.text,
                    raw_response.__dict__,
                    e,
                )
                raise

            try:
                next_response = raw_response.json()
            except Exception as e:
                logger.exception(
                    "Failed to parse response as JSON. Response: %s",
                    raw_response.__dict__,
                )
                raise e

            # Yield the results individually.
            results = cast(list[dict[str, Any]], next_response.get("results", []))

            # #4129: DC silently caps page size and under-counts the
            # ``start`` it embeds in ``_links.next``; re-derive it
            # ourselves. Manual yielding (not ``yield from``) so we can
            # fire ``next_page_callback`` before the last yield --
            # otherwise the iterator may never resume.
            old_url_suffix = url_suffix
            next_start = get_start_param_from_url(old_url_suffix) + len(results)
            url_suffix = cast(str, next_response.get("_links", {}).get("next", ""))
            if url_suffix and current_limit != limit:
                url_suffix = update_param_in_path(
                    url_suffix, "limit", str(current_limit)
                )
            if url_suffix and not self._is_cloud and results:
                url_suffix = update_param_in_path(url_suffix, "start", str(next_start))

            for i, result in enumerate(results):
                if i == len(results) - 1:
                    if url_suffix and next_page_callback:
                        next_page_callback(url_suffix)
                    elif force_offset_pagination:
                        url_suffix = update_param_in_path(
                            old_url_suffix, "start", str(next_start)
                        )

                yield result

            # we've observed that Confluence sometimes returns a next link despite giving
            # 0 results. This is a bug with Confluence, so we need to check for it and
            # stop paginating.
            if url_suffix and not results:
                logger.info(
                    "No results found for call '%s' despite next link being present. Stopping pagination.",
                    old_url_suffix,
                )
                break

    def fetch_content_read_restrictions(
        self,
        content_id: str,
    ) -> dict[str, Any] | None:
        """Fetch a single page's restrictions via the dedicated
        ``content/{id}/restriction/byOperation`` endpoint. Returns
        ``None`` on 403/404 so unreadable ancestors (drafts owned by
        another user) resolve as "no inheritable restriction here".
        ``advanced_mode=True`` bypasses the rate-limit wrapper's 7x
        403-retry loop which would otherwise burn ~70s per draft."""
        path = f"rest/api/content/{quote(content_id, safe='')}/restriction/byOperation"
        response: requests.Response = self.get(path, advanced_mode=True)
        if response.status_code in (403, 404):
            return None
        response.raise_for_status()
        body = response.json()
        return cast(dict[str, Any], body or {})

    def paginated_cql_retrieval(
        self,
        cql: str,
        expand: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        The content/search endpoint can be used to fetch pages, attachments, and comments.
        """
        cql_url = build_cql_url(cql, expand)
        yield from self._paginate_url(cql_url, limit)

    def paginated_page_retrieval(
        self,
        cql_url: str,
        limit: int,
        # Called with the next url to use to get the next page
        next_page_callback: Callable[[str], None] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        Error handling (and testing) wrapper for _paginate_url,
        because the current approach to page retrieval involves handling the
        next page links manually.
        """
        try:
            yield from self._paginate_url(
                cql_url, limit=limit, next_page_callback=next_page_callback
            )
        except Exception as e:
            logger.exception("Error in paginated_page_retrieval: %s", e)
            raise e

    def cql_paginate_all_expansions(
        self,
        cql: str,
        expand: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Paginate the top-level query, then each `_links.next` discovered
        in the expansions."""

        def _traverse_and_update(data: dict | list) -> None:
            if isinstance(data, dict):
                next_url = data.get("_links", {}).get("next")
                if next_url and "results" in data:
                    data["results"].extend(self._paginate_url(next_url, limit=limit))

                for value in data.values():
                    _traverse_and_update(value)
            elif isinstance(data, list):
                for item in data:
                    _traverse_and_update(item)

        for confluence_object in self.paginated_cql_retrieval(cql, expand, limit):
            _traverse_and_update(confluence_object)
            yield confluence_object

    def paginated_cql_user_retrieval(
        self,
        expand: str | None = None,
        limit: int | None = None,
    ) -> Iterator[ConfluenceUser]:
        """
        The search/user endpoint can be used to fetch users.
        It's a separate endpoint from the content/search endpoint used only for users.
        Otherwise it's very similar to the content/search endpoint.
        """

        # this is needed since there is a live bug with Confluence Server/Data Center
        # where not all users are returned by the APIs. This is a workaround needed until
        # that is patched.
        if self._confluence_user_profiles_override:
            yield from self._confluence_user_profiles_override

        elif self._is_cloud:
            cql = "type=user"
            url = "rest/api/search/user"
            expand_string = f"&expand={expand}" if expand else ""
            url += f"?cql={cql}{expand_string}"
            for user_result in self._paginate_url(
                url, limit, force_offset_pagination=True
            ):
                # Example response:
                # {
                #     'user': {
                #         'type': 'known',
                #         'accountId': '712020:35e60fbb-d0f3-4c91-b8c1-f2dd1d69462d',
                #         'accountType': 'atlassian',
                #         'email': 'chris@danswer.ai',
                #         'publicName': 'Chris Weaver',
                #         'profilePicture': {
                #             'path': '/wiki/aa-avatar/712020:35e60fbb-d0f3-4c91-b8c1-f2dd1d69462d',
                #             'width': 48,
                #             'height': 48,
                #             'isDefault': False
                #         },
                #         'displayName': 'Chris Weaver',
                #         'isExternalCollaborator': False,
                #         '_expandable': {
                #             'operations': '',
                #             'personalSpace': ''
                #         },
                #         '_links': {
                #             'self': 'https://danswerai.atlassian.net/wiki/rest/api/user?accountId=712020:35e60fbb-d0f3-4c91-b8c1-f2dd1d69462d'
                #         }
                #     },
                #     'title': 'Chris Weaver',
                #     'excerpt': '',
                #     'url': '/people/712020:35e60fbb-d0f3-4c91-b8c1-f2dd1d69462d',
                #     'breadcrumbs': [],
                #     'entityType': 'user',
                #     'iconCssClass': 'aui-icon content-type-profile',
                #     'lastModified': '2025-02-18T04:08:03.579Z',
                #     'score': 0.0
                # }
                user = user_result["user"]
                yield ConfluenceUser(
                    user_id=user["accountId"],
                    username=None,
                    display_name=user["displayName"],
                    email=user.get("email"),
                    type=user["accountType"],
                )
        else:
            for user in self._paginate_url("rest/api/user/list", limit):
                yield ConfluenceUser(
                    user_id=user["userKey"],
                    username=user["username"],
                    display_name=user["displayName"],
                    email=None,
                    type=user.get("type", "user"),
                )

    def paginated_groups_by_user_retrieval(
        self,
        user_id: str,  # accountId in Cloud, userKey in Server
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        This is not an SQL like query.
        It's a confluence specific endpoint that can be used to fetch groups.
        """
        user_field = "accountId" if self._is_cloud else "key"
        user_value = user_id
        # Server uses userKey (but calls it key during the API call), Cloud uses accountId
        user_query = f"{user_field}={quote(user_value)}"

        url = f"rest/api/user/memberof?{user_query}"
        yield from self._paginate_url(url, limit, force_offset_pagination=True)

    def get_all_space_permissions_server(
        self,
        space_key: str,
    ) -> list[dict[str, Any]]:
        """
        Fetches a space's permissions via the legacy JSON-RPC API.

        This is the only space-permissions API available on Confluence Data
        Center < 9.1.0. DC 9.1.0+ ships a proper REST API at
        /rest/api/space/{spaceKey}/permissions (CONFSERVER-78176) which is
        preferred wherever available; this method is the fallback for older
        Server / Data Center deployments.

        Failure modes handled here:

        - HTTP 401: the JSON-RPC plugin is disabled. Confluence Admin ->
          General Configuration -> Further Configuration -> Enable
          "Remote API (XML-RPC & SOAP)".
        - HTTP 200 with a non-JSON body (Confluence 7.7+): "Secure
          Administrator Sessions" / WebSudo is intercepting admin JSON-RPC
          calls and serving the login HTML or a WebSudoRequiredException
          page instead of a JSON-RPC envelope. We surface the actual HTTP
          status, Content-Type, and a body snippet so the admin can confirm
          which of the documented failure modes they're hitting (rather
          than guessing) and act on it.

        We use atlassian-python-api's `advanced_mode=True` to get the raw
        requests.Response back. Without it, the library's _response_handler
        catches the JSON parse error and silently coerces the body to None,
        which throws away every signal we'd need to debug the failure.
        Trade-off: the library no longer raises HTTPError on 4xx/5xx in
        advanced mode, so this call no longer benefits from the
        __getattr__ wrapper's retry-on-5xx; we call raise_for_status
        ourselves to preserve the "blow up on server error" behavior.
        """
        url = "rpc/json-rpc/confluenceservice-v2"
        data = {
            "jsonrpc": "2.0",
            "method": "getSpacePermissionSets",
            "id": 7,
            "params": [space_key],
        }
        response: requests.Response = self.post(url, data=data, advanced_mode=True)

        if response.status_code == 401:
            raise HTTPError(
                "Unauthorized (401) when calling JSON-RPC API for space permissions. "
                "This is likely because the Remote API is disabled. "
                "To fix: Confluence Admin -> General Configuration -> Further Configuration "
                "-> Enable 'Remote API (XML-RPC & SOAP)'",
                response=response,
            )
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError:
            content_type = response.headers.get("Content-Type", "<unset>")
            body_snippet = response.text[:_JSONRPC_ERROR_BODY_SNIPPET_CHARS]
            raise ConnectorValidationError(
                f"Confluence JSON-RPC returned a non-JSON response for space "
                f"'{space_key}' (HTTP {response.status_code}, "
                f"Content-Type={content_type}). This typically happens on "
                "Confluence Server / Data Center 7.7+ when 'Secure "
                "Administrator Sessions' (WebSudo) intercepts admin JSON-RPC "
                "calls. To fix, either (1) disable Secure Administrator "
                "Sessions in General Configuration -> Security Configuration, "
                "or (2) upgrade to Confluence Data Center 9.1+ where the REST "
                f"space-permissions API replaces JSON-RPC. See "
                f"{_WEBSUDO_KB_URL}\n"
                f"Response body (first {_JSONRPC_ERROR_BODY_SNIPPET_CHARS} "
                f"chars): {body_snippet!r}"
            )

        logger.debug("jsonrpc response: %s", payload)
        if not payload.get("result"):
            logger.warning(
                "No jsonrpc response for space permissions for space %s\nResponse: %s",
                space_key,
                payload,
            )

        return payload.get("result", [])

    def get_server_version(self) -> tuple[int, int] | None:
        """Returns the (major, minor) version of the upstream Confluence
        Data Center instance, or None for Cloud or when the probe fails.

        Probed once per client instance via Atlassian's
        documented "Server Information" endpoint
        (/rest/api/server-information). The result is cached on the
        instance, including the negative result, so a one-off network
        blip doesn't cause us to re-probe on every space-permissions
        sync.

        Used to gate features that only exist on newer DC versions, such
        as the REST space-permissions API introduced in DC 9.1.0
        (CONFSERVER-78176). When the probe fails (returns None), callers
        intentionally fall back to the legacy JSON-RPC path, on the
        assumption that probe failure most often correlates with older
        DC builds where the REST permissions API isn't available
        anyway. Most callers should prefer the higher-level feature
        predicates (e.g. supports_rest_space_permissions) over
        comparing the version tuple directly.
        """
        if self._is_cloud:
            return None
        if self._server_version_probed:
            return self._server_version

        self._server_version = self._probe_server_version()
        self._server_version_probed = True
        if self._server_version is not None:
            logger.info(
                "Detected Confluence Data Center version %s.%s",
                self._server_version[0],
                self._server_version[1],
            )
        return self._server_version

    def _probe_server_version(self) -> tuple[int, int] | None:
        try:
            info = self.get(_DC_SERVER_INFORMATION_PATH)
        except Exception as e:
            logger.warning("Failed to probe Confluence server version: %s", e)
            return None
        if not isinstance(info, dict):
            return None
        version_str = info.get("version") or ""
        return _parse_dc_version(version_str)

    def supports_rest_space_permissions(self) -> bool:
        """Whether the upstream instance has the DC 9.1+ space-permissions
        REST API (CONFSERVER-78176). Always False for Cloud (different API
        surface, branched on `is_cloud` upstream of any version check) and
        for DC instances older than 9.1.0 or where the version probe fails.
        """
        version = self.get_server_version()
        return (
            version is not None
            and version >= _MIN_DC_VERSION_FOR_REST_SPACE_PERMISSIONS
        )

    def get_all_space_permissions_server_rest(
        self,
        space_key: str,
    ) -> list[dict[str, Any]]:
        """Confluence DC 9.1+ REST API for space permissions.

        GET /rest/api/space/{spaceKey}/permissions returns a flat list of
        {operation, subject, spaceKey, spaceId} entries (CONFSERVER-78176).

        Failure modes:

        - 401: handled identically to the JSON-RPC path (token missing /
          expired).
        - 404: the endpoint isn't available on this Confluence DC version
          (i.e. < 9.1.0). Surfaced as
          ConfluenceRestSpacePermissionsNotAvailableError so the caller
          can fall back to the legacy JSON-RPC path.
        - 500: per CONFSERVER-99908, callers without
          Confluence-admin/space-admin rights receive HTTP 500 (rather
          than the more correct 403). Surfaced as
          InsufficientPermissionsError with that ticket referenced so
          the operator knows the actual remediation is "grant the bot
          account admin", not "investigate a server-side bug".
        """
        path = f"rest/api/space/{quote(space_key, safe='')}/permissions"
        response: requests.Response = self.get(path, advanced_mode=True)

        if response.status_code == 404:
            raise ConfluenceRestSpacePermissionsNotAvailableError(
                f"REST space-permissions endpoint not available on this "
                f"Confluence instance (HTTP 404 for space '{space_key}'). "
                "The endpoint requires Confluence Data Center 9.1.0+."
            )
        if response.status_code == 401:
            raise HTTPError(
                "Unauthorized (401) when calling REST space-permissions API. "
                "The credential is missing or expired.",
                response=response,
            )
        if response.status_code == 500:
            raise InsufficientPermissionsError(
                f"Confluence returned HTTP 500 for "
                f"GET /rest/api/space/{space_key}/permissions. Per "
                "CONFSERVER-99908 this endpoint returns 500 (rather than "
                "403) when the calling account lacks Confluence-admin or "
                "space-admin rights. Grant the bot account admin "
                "permissions on this space (or globally) and retry."
            )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, list):
            logger.warning(
                "Unexpected REST space-permissions payload shape for space "
                "%s: expected list, got %s",
                space_key,
                type(payload).__name__,
            )
            return []
        return payload

    def get_anonymous_space_permissions_server_rest(
        self,
        space_key: str,
    ) -> list[dict[str, Any]]:
        """Confluence DC 9.1+ anonymous space-permissions endpoint.

        GET /rest/api/space/{spaceKey}/permissions/anonymous returns the
        operations the anonymous role has on the space. Distinct from the
        bulk endpoint, which on the JSON-RPC path used to return an
        anonymous "row" inline.

        404 is treated as "no anonymous access" rather than fatal; some
        9.x patch versions had this endpoint missing or moved before it
        stabilized, and "missing endpoint" should not be louder than
        "no anonymous access" for our use case.
        """
        path = f"rest/api/space/{quote(space_key, safe='')}/permissions/anonymous"
        response: requests.Response = self.get(path, advanced_mode=True)

        if response.status_code == 404:
            return []
        if response.status_code == 500:
            # CONFSERVER-99908 again -- same remediation, different endpoint.
            raise InsufficientPermissionsError(
                f"Confluence returned HTTP 500 for "
                f"GET /rest/api/space/{space_key}/permissions/anonymous. "
                "Per CONFSERVER-99908 this endpoint returns 500 (rather "
                "than 403) when the calling account lacks "
                "Confluence-admin or space-admin rights."
            )
        response.raise_for_status()

        payload = response.json()
        if not isinstance(payload, list):
            return []
        return payload


def _parse_dc_version(version_str: str) -> tuple[int, int] | None:
    """Parse 'X.Y.Z[...]' into (X, Y); returns None on malformed input."""
    if not version_str:
        return None
    parts = version_str.split(".")
    if len(parts) < 2:
        return None
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return None


def _get_user(confluence_client: _OnyxConfluence, user_id: str) -> str:
    """Returns the display name for an account id (Cloud) or userkey (DC).

    Returns ``_USER_NOT_FOUND`` if the user is deactivated or not found.
    """
    cache_key = (confluence_client._url, user_id)
    if _USER_ID_TO_DISPLAY_NAME_CACHE.get(cache_key) is None:
        try:
            result = confluence_client.get_user_details_by_userkey(user_id)
            found_display_name = result.get("displayName")
        except Exception:
            found_display_name = None

        if not found_display_name:
            try:
                result = confluence_client.get_user_details_by_accountid(user_id)
                found_display_name = result.get("displayName")
            except Exception:
                found_display_name = None

        _USER_ID_TO_DISPLAY_NAME_CACHE[cache_key] = found_display_name

    return _USER_ID_TO_DISPLAY_NAME_CACHE.get(cache_key) or _USER_NOT_FOUND


class ConfluenceSpaceNotFoundError(Exception):
    """The space key does not exist, or the credential cannot read the space."""


class ConfluenceProbeVariant(str, Enum):
    """Token type of the connection probe: scoped API tokens use another path."""

    SCOPED = "scoped"
    UNSCOPED = "unscoped"


class ConfluenceSearchVariant(str, Enum):
    """Permission class of a CQL content search.

    ``content`` reads bodies, ``slim`` reads metadata only, and
    ``with_restrictions`` also expands read restrictions, which needs the
    permission-read scope.
    """

    CONTENT = "content"
    SLIM = "slim"
    WITH_RESTRICTIONS = "with_restrictions"


_SEARCH_VARIANTS = tuple(ConfluenceSearchVariant)


class ConfluenceSourceOperations(SourceOperations):
    source = DocumentSource.CONFLUENCE
    sdk_modules = ("atlassian",)
    # The gateway reads only the credential-bound fields (site URL, Cloud or
    # Data Center, scoped token).
    config_keys = frozenset(ConfluenceCredentialBinding.model_fields)

    _cached_client: _OnyxConfluence | None = None
    _cached_fast_client: _OnyxConfluence | None = None
    _cached_scoped_api_url: str | None = None

    def _client_build_lock(self) -> threading.Lock:
        """This gateway's lock against duplicate builds; a build makes remote
        calls for scoped tokens (tenant_info), so concurrent first calls would
        repeat them. Per gateway, so a slow site does not block other gateways.
        ``dict.setdefault`` is atomic under the GIL, so no guard lock is needed."""
        return vars(self).setdefault("_build_lock", threading.Lock())

    def _binding(self) -> ConfluenceCredentialBinding:
        return ConfluenceCredentialBinding.model_validate(
            self.connector_specific_config or {}
        )

    def _scoped_api_url(self, wiki_base: str) -> str:
        if self._cached_scoped_api_url is None:
            self._cached_scoped_api_url = scoped_url(wiki_base, "confluence")
        return self._cached_scoped_api_url

    def _build_client(self, *, fast: bool) -> _OnyxConfluence:
        binding = self._binding()
        wiki_base = binding.wiki_base.rstrip("/")
        return _OnyxConfluence(
            is_cloud=binding.is_cloud,
            url=wiki_base,
            credentials_provider=self.credentials_provider,
            timeout=_FAST_TIMEOUT if fast else None,
            scoped_token=binding.scoped_token,
            scoped_api_url=(
                self._scoped_api_url(wiki_base) if binding.scoped_token else None
            ),
        )

    def _client(self, *, fast: bool = False) -> _OnyxConfluence:
        cached = self._cached_fast_client if fast else self._cached_client
        if cached is not None:
            return cached
        with self._client_build_lock():
            cached = self._cached_fast_client if fast else self._cached_client
            if cached is None:
                cached = self._build_client(fast=fast)
                cached._initialize_connection(**_FINAL_KWARGS)
                if fast:
                    self._cached_fast_client = cached
                else:
                    self._cached_client = cached
        return cached

    def _legacy_client(self, *, fast: bool = False) -> _OnyxConfluence:
        """Temporary: the perm-sync paths still pass the client to the EE
        modules. #15454 moves those calls to operations and deletes this."""
        return self._client(fast=fast)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        variants=tuple(ConfluenceProbeVariant),
        untested=_UNTESTED,
    )
    def probe_site(self, *, variant: ConfluenceProbeVariant) -> None:
        """Proves the credential works for the site. Scoped tokens resolve the
        cloud id (tenant_info) and read one space over v1; other tokens read
        one space. Raises on failure."""
        scoped = self._binding().scoped_token
        if (variant == ConfluenceProbeVariant.SCOPED) != scoped:
            raise ValueError(
                f"probe_site variant {variant.value!r} does not match "
                f"scoped_token={scoped}."
            )
        with self._client_build_lock():
            client = self._cached_client or self._build_client(fast=False)
            client._probe_connection(**_PROBE_KWARGS)
            client._initialize_connection(**_FINAL_KWARGS)
            self._cached_client = client

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.DOC_PERMISSION_SYNC,
        },
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def list_spaces(
        self,
        *,
        space_keys: list[str] | None = None,
        limit: int = 50,
        fast: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Yields the visible spaces (v2 API for OAuth Cloud, else v1)."""
        return self._client(fast=fast).retrieve_confluence_spaces(
            space_keys=space_keys, limit=limit
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=_UNTESTED,
    )
    def get_space(self, *, space_key: str, fast: bool = False) -> dict[str, Any]:
        """Raises ``ConfluenceSpaceNotFoundError`` if the space does not exist
        or the credential cannot read it, and ``ConfluenceRetriesExhaustedError``
        when every retry failed or Confluence returned no body."""
        try:
            space: dict[str, Any] | None = self._client(fast=fast).get_space(space_key)
        except ApiError as e:
            raise ConfluenceSpaceNotFoundError(str(e)) from e
        if space is None:
            raise ConfluenceRetriesExhaustedError(
                f"Confluence returned no body for space {space_key}.",
                last_status_code=None,
            )
        return space

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.DOC_PERMISSION_SYNC,
        },
        consumes=OperationConsumes.BOTH,
        variants=_SEARCH_VARIANTS,
        untested=_UNTESTED,
    )
    def search_pages(
        self,
        *,
        variant: ConfluenceSearchVariant,  # noqa: ARG002
        cql: str,
        expand: str,
        limit: int | None = None,
        follow_expansion_links: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Yields the pages a CQL query matches. ``follow_expansion_links`` also
        pages through the ``_links.next`` of expanded fields."""
        return _search(
            self._client(),
            cql=cql,
            expand=expand,
            limit=limit,
            follow_expansion_links=follow_expansion_links,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=_UNTESTED,
    )
    def search_pages_from_url(
        self,
        *,
        url: str,
        limit: int,
        next_page_callback: Callable[[str], None],
    ) -> Iterator[dict[str, Any]]:
        """Yields pages from a content-search URL (a start URL or a checkpoint's
        ``_links.next``). Calls ``next_page_callback`` with each next URL."""
        return self._client().paginated_page_retrieval(
            cql_url=url, limit=limit, next_page_callback=next_page_callback
        )

    @source_operation(
        capabilities={
            CredentialCapability.INDEXING,
            CredentialCapability.DOC_PERMISSION_SYNC,
        },
        consumes=OperationConsumes.BOTH,
        variants=_SEARCH_VARIANTS,
        untested=_UNTESTED,
    )
    def search_attachments(
        self,
        *,
        variant: ConfluenceSearchVariant,  # noqa: ARG002
        cql: str,
        expand: str,
        limit: int | None = None,
        follow_expansion_links: bool = False,
    ) -> Iterator[dict[str, Any]]:
        """Yields the attachments a CQL query matches."""
        return _search(
            self._client(),
            cql=cql,
            expand=expand,
            limit=limit,
            follow_expansion_links=follow_expansion_links,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.BOTH,
        untested=_UNTESTED,
    )
    def search_comments(self, *, cql: str, expand: str) -> Iterator[dict[str, Any]]:
        """Yields the comments a CQL query matches."""
        return self._client().paginated_cql_retrieval(cql=cql, expand=expand)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def find_page_by_title(self, *, title: str) -> dict[str, Any] | None:
        """Returns the page with this title and its storage body, if any.
        Confluence enforces unique titles, so one result is enough."""
        return next(
            self._client().paginated_cql_retrieval(
                cql=f"type=page and title='{quote(title)}'",
                expand=_FIND_PAGE_EXPAND,
                limit=1,
            ),
            None,
        )

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def download_attachment(
        self, *, attachment: dict[str, Any], parent_content_id: str | None
    ) -> bytes:
        """Returns the attachment file. Uses the retry and OAuth refresh wrapper,
        but does not retry a 403: on a download it is a permission refusal.

        Raises ``ValueError`` if no download link can be built (Cloud needs the
        parent content id), ``HTTPError`` on a non-retryable error status, and
        ``ConfluenceRetriesExhaustedError`` when every retry failed.
        """
        client = self._client()
        link = _attachment_download_link(
            client._sdk_url(), attachment, parent_content_id, client._is_cloud
        )
        logger.info(
            "Downloading attachment: title=%s link=%s", attachment["title"], link
        )

        def download(confluence: Confluence) -> bytes:
            response = confluence.session.get(link)
            response.raise_for_status()
            return response.content

        return client._call_with_retries(download, retry_forbidden=False)

    @source_operation(
        capabilities={CredentialCapability.INDEXING},
        consumes=OperationConsumes.CREDENTIAL,
        untested=_UNTESTED,
    )
    def get_user_display_name(self, *, user_id: str) -> str:
        """Returns the display name of a userkey (DC) or account id (Cloud), or
        "Unknown Confluence User". No variants: the lookup tries the userkey
        endpoint and then the account-id endpoint for every id."""
        return _get_user(self._client(), user_id)


def _search(
    client: _OnyxConfluence,
    *,
    cql: str,
    expand: str,
    limit: int | None,
    follow_expansion_links: bool,
) -> Iterator[dict[str, Any]]:
    if follow_expansion_links:
        return client.cql_paginate_all_expansions(cql=cql, expand=expand, limit=limit)
    return client.paginated_cql_retrieval(cql=cql, expand=expand, limit=limit)


def _attachment_download_link(
    api_url: str,
    attachment: dict[str, Any],
    parent_content_id: str | None,
    is_cloud: bool,
) -> str:
    if not is_cloud:
        return api_url + attachment["_links"]["download"]
    # https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-content---attachments/#api-wiki-rest-api-content-id-child-attachment-attachmentid-download-get
    if not parent_content_id:
        raise ValueError(
            "parent_content_id is required to download attachments from "
            "Confluence Cloud."
        )
    return (
        api_url
        + f"/rest/api/content/{parent_content_id}/child/attachment/{attachment['id']}/download"
    )
