"""
# README (notes on Confluence pagination):

We've noticed that the `search/users` and `users/memberof` endpoints for Confluence Cloud use offset-based pagination as
opposed to cursor-based. We also know that page-retrieval uses cursor-based pagination.

Our default pagination strategy right now for cloud is to assume cursor-based.
However, if you notice that a cloud API is not being properly paginated (i.e., if the `_links.next` is not appearing in the
returned payload), then you can force offset-based pagination.

# TODO (@raunakab)
We haven't explored all of the cloud APIs' pagination strategies. @raunakab take time to go through this and figure them out.
"""

import json
import time
from collections.abc import Callable
from collections.abc import Generator
from collections.abc import Iterator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast
from typing import TypeVar
from urllib.parse import quote

import bs4
import requests
from atlassian import Confluence
from redis import Redis
from requests import HTTPError

from onyx.configs.app_configs import CONFLUENCE_CONNECTOR_USER_PROFILES_OVERRIDE
from onyx.configs.app_configs import OAUTH_CONFLUENCE_CLOUD_CLIENT_ID
from onyx.configs.app_configs import OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET
from onyx.connectors.confluence.models import ConfluenceUser
from onyx.connectors.confluence.user_profile_override import (
    process_confluence_user_profiles_override,
)
from onyx.connectors.confluence.utils import _handle_http_error
from onyx.connectors.confluence.utils import confluence_refresh_tokens
from onyx.connectors.confluence.utils import get_start_param_from_url
from onyx.connectors.confluence.utils import update_param_in_path
from onyx.connectors.cross_connector_utils.miscellaneous_utils import scoped_url
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.interfaces import CredentialsProviderInterface
from onyx.file_processing.html_utils import format_document_soup
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()


F = TypeVar("F", bound=Callable[..., Any])


# https://jira.atlassian.com/browse/CONFCLOUD-76433
_PROBLEMATIC_EXPANSIONS = "body.storage.value"
_REPLACEMENT_EXPANSIONS = "body.view.value"

_USER_NOT_FOUND = "Unknown Confluence User"
_USER_ID_TO_DISPLAY_NAME_CACHE: dict[str, str | None] = {}
_USER_EMAIL_CACHE: dict[str, str | None] = {}
# Separate cache from _USER_EMAIL_CACHE: the DC 9.1+ REST space-permissions
# response only includes a user's userKey (CONFSERVER-100505), not their
# username, so we have to resolve email by a different identifier.
_USER_KEY_TO_EMAIL_CACHE: dict[str, str | None] = {}
_DEFAULT_PAGINATION_LIMIT = 1000
_MINIMUM_PAGINATION_LIMIT = 5

_SERVER_ERROR_CODES = {500, 502, 503, 504}

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


class ConfluenceRateLimitError(Exception):
    pass


class ConfluenceRestSpacePermissionsNotAvailableError(Exception):
    """Raised by REST-API space-permissions calls when the endpoint is missing
    on the upstream Confluence DC instance (e.g. DC < 9.1.0 returning 404).

    Callers use this as a signal to fall back to the legacy JSON-RPC path.
    """


class OnyxConfluence:
    """
    This is a custom Confluence class that:

    A. overrides the default Confluence class to add a custom CQL method.
    B.
    This is necessary because the default Confluence class does not properly support cql expansions.
    All methods are automatically wrapped with handle_confluence_rate_limit.
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
    ) -> None:
        self.base_url = url  #'/'.join(url.rstrip("/").split("/")[:-1])
        url = scoped_url(url, "confluence") if scoped_token else url

        self._is_cloud = is_cloud
        self._url = url.rstrip("/")
        self._credentials_provider = credentials_provider
        self.scoped_token = scoped_token
        self.redis_client: Redis | None = None
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

        # Cached result of /rest/api/serverInfo, populated on first
        # `get_server_version()` call. _server_version_probed=True with
        # _server_version=None means "we tried and the probe failed", so
        # we don't keep retrying every space-permissions sync.
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
        credential_raw = self.redis_client.get(self.credential_key)
        if credential_raw is not None:
            credential_bytes = cast(bytes, credential_raw)
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
        new_credentials = confluence_refresh_tokens(
            OAUTH_CONFLUENCE_CLOUD_CLIENT_ID,
            OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET,
            credential_json["cloud_id"],
            credential_json["confluence_refresh_token"],
        )

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
        """Internal helper to paginate through spaces for a specific API endpoint."""
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

            if is_v2:
                url = data.get("_links", {}).get("next", "")
            else:
                if len(results) < limit:
                    return
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
                import requests

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

            oauth2_dict: dict[str, Any] = OnyxConfluence._make_oauth2_dict(credentials)
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

    # https://developer.atlassian.com/cloud/confluence/rate-limiting/
    # This uses the native rate limiting option provided by the
    # confluence client and otherwise applies a simpler set of error handling.
    def _make_rate_limited_confluence_method(
        self, name: str, credential_provider: CredentialsProviderInterface | None
    ) -> Callable[..., Any]:
        def wrapped_call(*args: list[Any], **kwargs: Any) -> Any:
            MAX_RETRIES = 5

            TIMEOUT = 600
            timeout_at = time.monotonic() + TIMEOUT

            for attempt in range(MAX_RETRIES):
                if time.monotonic() > timeout_at:
                    raise TimeoutError(
                        f"Confluence call attempts took longer than {TIMEOUT} seconds."
                    )

                # we're relying more on the client to rate limit itself
                # and applying our own retries in a more specific set of circumstances
                try:
                    if credential_provider:
                        with credential_provider:
                            credentials, renewed = self._renew_credentials()
                            if renewed:
                                self._confluence = self._initialize_connection_helper(
                                    credentials, **self._kwargs
                                )
                            attr = getattr(self._confluence, name, None)
                            if attr is None:
                                # The underlying Confluence client doesn't have this attribute
                                raise AttributeError(
                                    f"'{type(self).__name__}' object has no attribute '{name}'"
                                )

                            return attr(*args, **kwargs)
                    else:
                        attr = getattr(self._confluence, name, None)
                        if attr is None:
                            # The underlying Confluence client doesn't have this attribute
                            raise AttributeError(
                                f"'{type(self).__name__}' object has no attribute '{name}'"
                            )

                        return attr(*args, **kwargs)

                except HTTPError as e:
                    delay_until = _handle_http_error(e, attempt, MAX_RETRIES)
                    logger.warning(
                        "HTTPError in confluence call. Retrying in %s seconds...",
                        delay_until,
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

        return wrapped_call

    def __getattr__(self, name: str) -> Any:
        """Dynamically intercept attribute/method access."""
        attr = getattr(self._confluence, name, None)
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
        rate_limited_method: Callable[..., Any] = (
            self._make_rate_limited_confluence_method(name, self._credentials_provider)
        )

        return rate_limited_method

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

        TODO (chris): make this yield failures as well as successes.
        TODO (chris): make this work for confluence cloud somehow.
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
                        new_url_suffix = (
                            yield from self._try_one_by_one_for_paginated_url(
                                url_suffix,
                                initial_start=initial_start,
                                limit=current_limit,
                            )
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

            # Note 1:
            # Make sure we don't update the start by more than the amount
            # of results we were able to retrieve. The Confluence API has a
            # weird behavior where if you pass in a limit that is too large for
            # the configured server, it will artificially limit the amount of
            # results returned BUT will not apply this to the start parameter.
            # This will cause us to miss results.
            #
            # Note 2:
            # We specifically perform manual yielding (i.e., `for x in xs: yield x`) as opposed to using a `yield from xs`
            # because we *have to call the `next_page_callback`* prior to yielding the last element!
            #
            # If we did:
            #
            # ```py
            # yield from results
            # if next_page_callback:
            #   next_page_callback(url_suffix)
            # ```
            #
            # then the logic would fail since the iterator would finish (and the calling scope would exit out of its driving
            # loop) prior to the callback being called.

            old_url_suffix = url_suffix
            updated_start = get_start_param_from_url(old_url_suffix)
            url_suffix = cast(str, next_response.get("_links", {}).get("next", ""))
            if url_suffix and current_limit != limit:
                url_suffix = update_param_in_path(
                    url_suffix, "limit", str(current_limit)
                )
            for i, result in enumerate(results):
                updated_start += 1
                if url_suffix and next_page_callback and i == len(results) - 1:
                    # update the url if we're on the last result in the page
                    if not self._is_cloud:
                        # If confluence claims there are more results, we update the start param
                        # based on how many results were returned and try again.
                        url_suffix = update_param_in_path(
                            url_suffix, "start", str(updated_start)
                        )
                    # notify the caller of the new url
                    next_page_callback(url_suffix)

                elif force_offset_pagination and i == len(results) - 1:
                    url_suffix = update_param_in_path(
                        old_url_suffix, "start", str(updated_start)
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

    def build_cql_url(self, cql: str, expand: str | None = None) -> str:
        expand_string = f"&expand={expand}" if expand else ""
        return f"rest/api/content/search?cql={cql}{expand_string}"

    def paginated_cql_retrieval(
        self,
        cql: str,
        expand: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        The content/search endpoint can be used to fetch pages, attachments, and comments.
        """
        cql_url = self.build_cql_url(cql, expand)
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
        """
        This function will paginate through the top level query first, then
        paginate through all of the expansions.
        """

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

    def paginated_groups_retrieval(
        self,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        This is not an SQL like query.
        It's a confluence specific endpoint that can be used to fetch groups.
        """
        yield from self._paginate_url("rest/api/group", limit)

    def paginated_group_members_retrieval(
        self,
        group_name: str,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        This is not an SQL like query.
        It's a confluence specific endpoint that can be used to fetch the members of a group.
        THIS DOESN'T WORK FOR SERVER because it breaks when there is a slash in the group name.
        E.g. neither "test/group" nor "test%2Fgroup" works for confluence.
        """
        group_name = quote(group_name)
        yield from self._paginate_url(f"rest/api/group/{group_name}/member", limit)

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

        Probed once per OnyxConfluence instance via /rest/api/serverInfo
        (the result is cached on the instance, including the negative
        result, so a one-off network blip doesn't cause us to re-probe on
        every space-permissions sync).

        Used to gate features that only exist on newer DC versions, such
        as the REST space-permissions API introduced in DC 9.1.0
        (CONFSERVER-78176). Most callers should prefer the higher-level
        feature predicates (e.g. supports_rest_space_permissions) over
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
            info = self.get("rest/api/serverInfo")
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

    def get_current_user(self, expand: str | None = None) -> Any:
        """
        Implements a method that isn't in the third party client.

        Get information about the current user
        :param expand: OPTIONAL expand for get status of user.
                Possible param is "status". Results are "Active, Deactivated"
        :return: Returns the user details
        """

        from atlassian.errors import ApiPermissionError

        url = "rest/api/user/current"
        params = {}
        if expand:
            params["expand"] = expand
        try:
            response = self.get(url, params=params)
        except HTTPError as e:
            if e.response.status_code == 403:
                raise ApiPermissionError(
                    "The calling user does not have permission", reason=e
                )
            raise
        return response


def get_user_email_from_username__server(
    confluence_client: OnyxConfluence, user_name: str
) -> str | None:
    global _USER_EMAIL_CACHE
    if _USER_EMAIL_CACHE.get(user_name) is None:
        try:
            response = confluence_client.get_mobile_parameters(user_name)
            email = response.get("email")
        except HTTPError as e:
            status_code = e.response.status_code if e.response is not None else "N/A"
            logger.warning(
                "Failed to get confluence email for %s: HTTP %s - %s",
                user_name,
                status_code,
                e,
            )
            # For now, we'll just return None and log a warning. This means
            # we will keep retrying to get the email every group sync.
            email = None
        except Exception as e:
            logger.warning(
                "Failed to get confluence email for %s: %s - %s",
                user_name,
                type(e).__name__,
                e,
            )
            email = None
        _USER_EMAIL_CACHE[user_name] = email
    return _USER_EMAIL_CACHE[user_name]


def get_user_email_from_userkey__server(
    confluence_client: OnyxConfluence, user_key: str
) -> str | None:
    """userKey -> email resolver for Confluence Data Center.

    Parallels get_user_email_from_username__server but keyed on userKey
    instead of username, because the DC 9.1+ space-permissions REST API
    only exposes userKey on user subjects (CONFSERVER-100505 -- still
    unresolved as of the 10.x line).

    Cached separately from _USER_EMAIL_CACHE because the keyspaces are
    different (userKey is opaque hex, username is human-readable).
    """
    global _USER_KEY_TO_EMAIL_CACHE
    if user_key not in _USER_KEY_TO_EMAIL_CACHE:
        try:
            response = confluence_client.get_user_details_by_userkey(user_key)
            email = response.get("email") if isinstance(response, dict) else None
        except HTTPError as e:
            status_code = e.response.status_code if e.response is not None else "N/A"
            logger.warning(
                "Failed to get confluence email for userKey %s: HTTP %s - %s",
                user_key,
                status_code,
                e,
            )
            email = None
        except Exception as e:
            logger.warning(
                "Failed to get confluence email for userKey %s: %s - %s",
                user_key,
                type(e).__name__,
                e,
            )
            email = None
        _USER_KEY_TO_EMAIL_CACHE[user_key] = email
    return _USER_KEY_TO_EMAIL_CACHE[user_key]


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


def _get_user(confluence_client: OnyxConfluence, user_id: str) -> str:
    """Get Confluence Display Name based on the account-id or userkey value

    Args:
        user_id (str): The user id (i.e: the account-id or userkey)
        confluence_client (Confluence): The Confluence Client

    Returns:
        str: The User Display Name. 'Unknown User' if the user is deactivated or not found
    """
    global _USER_ID_TO_DISPLAY_NAME_CACHE
    if _USER_ID_TO_DISPLAY_NAME_CACHE.get(user_id) is None:
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

        _USER_ID_TO_DISPLAY_NAME_CACHE[user_id] = found_display_name

    return _USER_ID_TO_DISPLAY_NAME_CACHE.get(user_id) or _USER_NOT_FOUND


def sanitize_attachment_title(title: str) -> str:
    """
    Sanitize the attachment title to be a valid HTML attribute.
    """
    return title.replace("<", "_").replace(">", "_").replace(" ", "_").replace(":", "_")


def extract_text_from_confluence_html(
    confluence_client: OnyxConfluence,
    confluence_object: dict[str, Any],
    fetched_titles: set[str],
) -> str:
    """Parse a Confluence html page and replace the 'user Id' by the real
        User Display Name

    Args:
        confluence_object (dict): The confluence object as a dict
        confluence_client (Confluence): Confluence client
        fetched_titles (set[str]): The titles of the pages that have already been fetched
    Returns:
        str: loaded and formated Confluence page
    """
    body = confluence_object["body"]
    object_html = body.get("storage", body.get("view", {})).get("value")

    soup = bs4.BeautifulSoup(object_html, "html.parser")

    _remove_macro_stylings(soup=soup)

    for date_span in soup.findAll("span", {"class": "date-lozenger-container"}):
        date_span.replaceWith(date_span.get_text())

    for user in soup.findAll("ri:user"):
        user_id = (
            user.attrs["ri:account-id"]
            if "ri:account-id" in user.attrs
            else user.get("ri:userkey")
        )
        if not user_id:
            logger.warning(
                "ri:userkey not found in ri:user element. Found attrs: %s",
                user.attrs,
            )
            continue
        # Include @ sign for tagging, more clear for LLM
        user.replaceWith("@" + _get_user(confluence_client, user_id))

    for html_page_reference in soup.findAll("ac:structured-macro"):
        # Here, we only want to process page within page macros
        if html_page_reference.attrs.get("ac:name") != "include":
            continue

        page_data = html_page_reference.find("ri:page")
        if not page_data:
            logger.warning(
                "Skipping retrieval of %s because because page data is missing",
                html_page_reference,
            )
            continue

        page_title = page_data.attrs.get("ri:content-title")
        if not page_title:
            # only fetch pages that have a title
            logger.warning(
                "Skipping retrieval of %s because it has no title",
                html_page_reference,
            )
            continue

        if page_title in fetched_titles:
            # prevent recursive fetching of pages
            logger.debug("Skipping %s because it has already been fetched", page_title)
            continue

        fetched_titles.add(page_title)

        # Wrap this in a try-except because there are some pages that might not exist
        try:
            page_query = f"type=page and title='{quote(page_title)}'"

            page_contents: dict[str, Any] | None = None
            # Confluence enforces title uniqueness, so we should only get one result here
            for page in confluence_client.paginated_cql_retrieval(
                cql=page_query,
                expand="body.storage.value",
                limit=1,
            ):
                page_contents = page
                break
        except Exception as e:
            logger.warning(
                "Error getting page contents for object %s: %s",
                confluence_object,
                e,
            )
            continue

        if not page_contents:
            continue

        text_from_page = extract_text_from_confluence_html(
            confluence_client=confluence_client,
            confluence_object=page_contents,
            fetched_titles=fetched_titles,
        )

        html_page_reference.replaceWith(text_from_page)

    for html_link_body in soup.findAll("ac:link-body"):
        # This extracts the text from inline links in the page so they can be
        # represented in the document text as plain text
        try:
            text_from_link = html_link_body.text
            html_link_body.replaceWith(f"(LINK TEXT: {text_from_link})")
        except Exception as e:
            logger.warning("Error processing ac:link-body: %s", e)

    for html_attachment in soup.findAll("ri:attachment"):
        # This extracts the text from inline attachments in the page so they can be
        # represented in the document text as plain text
        try:
            html_attachment.replaceWith(
                f"<attachment>{sanitize_attachment_title(html_attachment.attrs['ri:filename'])}</attachment>"
            )  # to be replaced later
        except Exception as e:
            logger.warning("Error processing ac:attachment: %s", e)

    return format_document_soup(soup)


def _remove_macro_stylings(soup: bs4.BeautifulSoup) -> None:
    for macro_root in soup.findAll("ac:structured-macro"):
        if not isinstance(macro_root, bs4.Tag):
            continue

        macro_styling = macro_root.find(name="ac:parameter", attrs={"ac:name": "page"})
        if not macro_styling or not isinstance(macro_styling, bs4.Tag):
            continue

        macro_styling.extract()
