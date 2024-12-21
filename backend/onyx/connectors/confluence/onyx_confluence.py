import io
import json
import math
import time
from abc import ABC
from abc import abstractmethod
from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast
from typing import TypeVar
from urllib.parse import quote

import bs4
from atlassian import Confluence  # type:ignore
from redis import Redis
from redis.exceptions import LockError
from redis.lock import Lock as RedisLock
from requests import HTTPError

from ee.onyx.configs.app_configs import OAUTH_CONFLUENCE_CLOUD_CLIENT_ID
from ee.onyx.configs.app_configs import OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET
from onyx.configs.app_configs import (
    CONFLUENCE_CONNECTOR_ATTACHMENT_CHAR_COUNT_THRESHOLD,
)
from onyx.configs.app_configs import CONFLUENCE_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD
from onyx.connectors.confluence.utils import confluence_refresh_tokens
from onyx.connectors.confluence.utils import validate_attachment_filetype
from onyx.connectors.interfaces import CredentialsProviderInterface
from onyx.file_processing.extract_file_text import extract_file_text
from onyx.file_processing.html_utils import format_document_soup
from onyx.redis.redis_pool import get_redis_client
from onyx.utils.logger import setup_logger

logger = setup_logger()


F = TypeVar("F", bound=Callable[..., Any])


RATE_LIMIT_MESSAGE_LOWERCASE = "Rate limit exceeded".lower()

# https://jira.atlassian.com/browse/CONFCLOUD-76433
_PROBLEMATIC_EXPANSIONS = "body.storage.value"
_REPLACEMENT_EXPANSIONS = "body.view.value"

_USER_NOT_FOUND = "Unknown Confluence User"
_USER_ID_TO_DISPLAY_NAME_CACHE: dict[str, str | None] = {}


class OAuthRefreshInterface(ABC):
    """Defines a callback interface to be passed to the rate limiting function.

    The interface is used to globally lock operations that use shared credentials. It
    would be bad for one operation to renew a credential while another operation is using it.

    """

    @abstractmethod
    def lock_and_refresh(self) -> bool:
        """Lock and refresh the OAuth Token"""

    @abstractmethod
    def release(self) -> None:
        """Release the lock."""


class ConfluenceRateLimitError(Exception):
    pass


def _handle_http_error(e: HTTPError, attempt: int) -> int:
    MIN_DELAY = 2
    MAX_DELAY = 60
    STARTING_DELAY = 5
    BACKOFF = 2

    # Check if the response or headers are None to avoid potential AttributeError
    if e.response is None or e.response.headers is None:
        logger.warning("HTTPError with `None` as response or as headers")
        raise e

    if (
        e.response.status_code != 429
        and RATE_LIMIT_MESSAGE_LOWERCASE not in e.response.text.lower()
    ):
        raise e

    retry_after = None

    retry_after_header = e.response.headers.get("Retry-After")
    if retry_after_header is not None:
        try:
            retry_after = int(retry_after_header)
            if retry_after > MAX_DELAY:
                logger.warning(
                    f"Clamping retry_after from {retry_after} to {MAX_DELAY} seconds..."
                )
                retry_after = MAX_DELAY
            if retry_after < MIN_DELAY:
                retry_after = MIN_DELAY
        except ValueError:
            pass

    if retry_after is not None:
        logger.warning(
            f"Rate limiting with retry header. Retrying after {retry_after} seconds..."
        )
        delay = retry_after
    else:
        logger.warning(
            "Rate limiting without retry header. Retrying with exponential backoff..."
        )
        delay = min(STARTING_DELAY * (BACKOFF**attempt), MAX_DELAY)

    delay_until = math.ceil(time.monotonic() + delay)
    return delay_until


# https://developer.atlassian.com/cloud/confluence/rate-limiting/
# this uses the native rate limiting option provided by the
# confluence client and otherwise applies a simpler set of error handling
def make_rate_limited_confluence_method(
    confluence_call: F, oauth_refresh_callback: OAuthRefreshInterface | None = None
) -> F:
    def wrapped_call(*args: list[Any], **kwargs: Any) -> Any:
        MAX_RETRIES = 5

        TIMEOUT = 600
        timeout_at = time.monotonic() + TIMEOUT

        try:
            for attempt in range(MAX_RETRIES):
                if time.monotonic() > timeout_at:
                    raise TimeoutError(
                        f"Confluence call attempts took longer than {TIMEOUT} seconds."
                    )

                if oauth_refresh_callback:
                    oauth_refresh_callback.lock_and_refresh()

                try:
                    # we're relying more on the client to rate limit itself
                    # and applying our own retries in a more specific set of circumstances
                    return confluence_call(*args, **kwargs)
                except HTTPError as e:
                    delay_until = _handle_http_error(e, attempt)
                    logger.warning(
                        f"HTTPError in confluence call. "
                        f"Retrying in {delay_until} seconds..."
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
        finally:
            if oauth_refresh_callback:
                oauth_refresh_callback.release()

    return cast(F, wrapped_call)


_DEFAULT_PAGINATION_LIMIT = 1000


class OAuthRefresh(OAuthRefreshInterface):
    """Callback class for the rate limiting wrapper to use in between retries"""

    LOCK_PREFIX: str = "da_lock:connector:confluence:token_refresh"
    LOCK_TTL = 900  # TTL of the lock

    CREDENTIAL_PREFIX = "connector:confluence:credential"
    CREDENTIAL_TTL = 300

    def __init__(self, credential_provider: CredentialsProviderInterface):
        self._credential_provider = credential_provider

        self.lock_key: str = (
            self.LOCK_PREFIX + f":credential_{credential_provider.get_credential_id()}"
        )
        self.credential_key: str = (
            self.CREDENTIAL_PREFIX
            + f":credential_{credential_provider.get_credential_id()}"
        )

        self.redis_client: Redis = get_redis_client()
        self.redis_lock: RedisLock = self.redis_client.lock(
            self.lock_key, timeout=self.LOCK_TTL
        )

    def acquire_and_refresh(self) -> bool:
        """Lock and refresh the OAuth Token"""
        acquired = self.redis_lock.acquire(blocking_timeout=self.LOCK_TTL)
        if not acquired:
            raise LockError(
                f"Could not acquire the lock refresh tokens within the specified timeout. "
                f"blocking_timeout={self.LOCK_TTL}s"
            )

        # check redis first, then fallback to the DB
        credential_bytes: bytes | None = self.redis_client.get(self.credential_key)
        if credential_bytes is not None:
            credential_str = credential_bytes.decode("utf-8")
            credential_json: dict[str, Any] = json.loads(credential_str)
        else:
            credential_json = self._credential_provider.get_credentials()

        now = datetime.now(timezone.utc)
        created_at = datetime.fromisoformat(credential_json["created_at"])
        expires_in = credential_json["expires_in"]
        renew_at = created_at + timedelta(seconds=expires_in // 2)
        if now > renew_at:
            new_credentials = confluence_refresh_tokens(
                OAUTH_CONFLUENCE_CLOUD_CLIENT_ID,
                OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET,
                credential_json["cloud_id"],
                credential_json["confluence_refresh_token"],
            )
            new_credential_str = json.dumps(new_credentials)
            self.redis_client.set(
                self.credential_key, new_credential_str, ex=self.CREDENTIAL_TTL
            )
            self._credential_provider.set_credentials(new_credentials)

    def release(self) -> None:
        """Release the lock."""
        try:
            if not self.redis_lock.owned():
                logger.error("redis_lock is no longer owned by this class!")
                return

            self.redis_lock.release()
        except Exception:
            logger.exception("Failed to check if primary worker lock is owned")


# class OnyxOAuthProvider():
#     """This class needs to provide the ability to:
#     1. read / write credentials
#     2. refresh credentials
#     3. distributed lock/release (to prevent multiple processes using the credential
#     from causing a race condition)
#     """

#     REFRESH_KEY: str = "da_lock:connector:confluence_token_refresh"
#     LOCK_TIMEOUT = 900

#     def __init__(self):
#         self.redis_client: Redis = get_redis_client()
#         self.redis_lock: RedisLock = self.redis_client.lock(
#             self.REFRESH_KEY, timeout=self.LOCK_TIMEOUT
#         )

#     def read_credentials():
#         pass

#     def write_credentials(credentials: dict[str, Any]):
#         pass


class OnyxConfluence:
    """
    This is a custom Confluence class that overrides the default Confluence class to add a custom CQL method.
    This is necessary because the default Confluence class does not properly support cql expansions.
    All methods are automatically wrapped with handle_confluence_rate_limit.
    """

    def __init__(self, url: str, *args: Any, **kwargs: Any) -> None:
        self._url = url
        self._args = args
        self._kwargs = kwargs

        self._confluence = Confluence(url)
        self._oauth_refresh_callback = OAuthRefresh()

        # super(OnyxConfluence, self).__init__(url, *args, **kwargs)
        # self._wrap_methods()

    def _test_connection(
        credential_provider: CredentialsProviderInterface,
        is_cloud: bool,
        wiki_base: str,
    ) -> bool:
        credentials = credential_provider.get_credentials()

        oauth2_dict: dict[str, Any] = {}
        url = wiki_base.rstrip("/")
        if "confluence_refresh_token" in credentials:
            oauth2_dict["client_id"] = OAUTH_CONFLUENCE_CLOUD_CLIENT_ID
            oauth2_dict["token"] = {}
            oauth2_dict["token"]["access_token"] = credentials[
                "confluence_access_token"
            ]
            url = f"https://api.atlassian.com/ex/confluence/{credentials['cloud_id']}"

        shared_base_kwargs = {
            "api_version": "cloud" if is_cloud else "latest",
            "backoff_and_retry": True,
            "cloud": is_cloud,
        }

        shared_probe_kwargs = {
            **shared_base_kwargs,
            "url": url,
            "max_backoff_retries": 6,
            "max_backoff_seconds": 10,
        }

        # probe connection with direct client, no retries
        if "confluence_refresh_token" in credentials:
            logger.info("Probing Confluence with OAuth Access Token.")

            confluence_client_with_minimal_retries = Confluence(
                oauth2=oauth2_dict, **shared_probe_kwargs
            )
        else:
            logger.info("Probing Confluence with Personal Access Token.")
            confluence_client_with_minimal_retries = Confluence(
                username=credentials["confluence_username"] if is_cloud else None,
                password=credentials["confluence_access_token"] if is_cloud else None,
                token=credentials["confluence_access_token"] if not is_cloud else None,
                **shared_probe_kwargs,
            )

        spaces = confluence_client_with_minimal_retries.get_all_spaces(limit=1)

        # uncomment the following for testing
        # the following is an attempt to retrieve the user's timezone
        # Unfornately, all data is returned in UTC regardless of the user's time zone
        # even tho CQL parses incoming times based on the user's time zone
        # space_key = spaces["results"][0]["key"]
        # space_details = confluence_client_with_minimal_retries.cql(f"space.key={space_key}+AND+type=space")

        if not spaces:
            raise RuntimeError(
                f"No spaces found at {wiki_base}! "
                "Check your credentials and wiki_base and make sure "
                "is_cloud is set correctly."
            )

        shared_final_kwargs = {
            **shared_base_kwargs,
            "max_backoff_retries": 10,
            "max_backoff_seconds": 60,
        }

        if "confluence_refresh_token" in credentials:
            return OnyxConfluence(url=url, oauth2=oauth2_dict, **shared_final_kwargs)

        return OnyxConfluence(
            url=url,
            # passing in username causes issues for Confluence data center
            username=credentials["confluence_username"] if is_cloud else None,
            password=credentials["confluence_access_token"] if is_cloud else None,
            token=credentials["confluence_access_token"] if not is_cloud else None,
            **shared_final_kwargs,
        )

    def get_current_user(self, expand: str | None = None) -> Any:
        """
        Implements a method that isn't in the third party client.

        Get information about the current user
        :param expand: OPTIONAL expand for get status of user.
                Possible param is "status". Results are "Active, Deactivated"
        :return: Returns the user details
        """

        from atlassian.errors import ApiPermissionError  # type:ignore

        url = "rest/api/user/current"
        params = {}
        if expand:
            params["expand"] = expand
        try:
            response = self._confluence.get(url, params=params)
        except HTTPError as e:
            if e.response.status_code == 403:
                raise ApiPermissionError(
                    "The calling user does not have permission", reason=e
                )
            raise
        return response

    # def _wrap_methods(self) -> None:
    #     """
    #     For each attribute that is callable (i.e., a method) and doesn't start with an underscore,
    #     wrap it with handle_confluence_rate_limit.
    #     """
    #     for attr_name in dir(self):
    #         if callable(getattr(self, attr_name)) and not attr_name.startswith("_"):
    #             setattr(
    #                 self,
    #                 attr_name,
    #                 handle_confluence_rate_limit(getattr(self, attr_name)),
    #             )

    # def _ensure_token_valid(self) -> None:
    #     if self._token_is_expired():
    #         self._refresh_token()
    #         # Re-init the Confluence client with the originally stored args
    #         self._confluence = Confluence(self._url, *self._args, **self._kwargs)

    def __getattr__(self, name: str):
        """Dynamically intercept attribute/method access."""
        attr = getattr(self._confluence, name, None)
        if attr is None:
            # The underlying Confluence client doesn't have this attribute
            raise AttributeError(
                f"'{type(self).__name__}' object has no attribute '{name}'"
            )

        # skip methods that start with "_"
        if callable(attr) and not name.startswith("_"):
            rate_limited_method = make_rate_limited_confluence_method(
                attr, self._oauth_refresh_callback
            )

            def wrapped_method(*args, **kwargs):
                return rate_limited_method(*args, **kwargs)

            return wrapped_method

        # If it's not a method, just return it after ensuring token validity
        return attr

    def _paginate_url(
        self, url_suffix: str, limit: int | None = None
    ) -> Iterator[dict[str, Any]]:
        """
        This will paginate through the top level query.
        """
        if not limit:
            limit = _DEFAULT_PAGINATION_LIMIT

        connection_char = "&" if "?" in url_suffix else "?"
        url_suffix += f"{connection_char}limit={limit}"

        while url_suffix:
            try:
                logger.debug(f"Making confluence call to {url_suffix}")
                next_response = self._confluence.get(url_suffix)
            except Exception as e:
                logger.warning(f"Error in confluence call to {url_suffix}")

                # If the problematic expansion is in the url, replace it
                # with the replacement expansion and try again
                # If that fails, raise the error
                if _PROBLEMATIC_EXPANSIONS not in url_suffix:
                    logger.exception(f"Error in confluence call to {url_suffix}")
                    raise e
                logger.warning(
                    f"Replacing {_PROBLEMATIC_EXPANSIONS} with {_REPLACEMENT_EXPANSIONS}"
                    " and trying again."
                )
                url_suffix = url_suffix.replace(
                    _PROBLEMATIC_EXPANSIONS,
                    _REPLACEMENT_EXPANSIONS,
                )
                continue

            # yield the results individually
            yield from next_response.get("results", [])

            url_suffix = next_response.get("_links", {}).get("next")

    def paginated_cql_retrieval(
        self,
        cql: str,
        expand: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        The content/search endpoint can be used to fetch pages, attachments, and comments.
        """
        expand_string = f"&expand={expand}" if expand else ""
        yield from self._paginate_url(
            f"rest/api/content/search?cql={cql}{expand_string}", limit
        )

    def cql_paginate_all_expansions(
        self,
        cql: str,
        expand: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        This function will paginate through the top level query first, then
        paginate through all of the expansions.
        The limit only applies to the top level query.
        All expansion paginations use default pagination limit (defined by Atlassian).
        """

        def _traverse_and_update(data: dict | list) -> None:
            if isinstance(data, dict):
                next_url = data.get("_links", {}).get("next")
                if next_url and "results" in data:
                    data["results"].extend(self._paginate_url(next_url))

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
    ) -> Iterator[dict[str, Any]]:
        """
        The search/user endpoint can be used to fetch users.
        It's a seperate endpoint from the content/search endpoint used only for users.
        Otherwise it's very similar to the content/search endpoint.
        """
        cql = "type=user"
        url = "rest/api/search/user" if self._confluence.cloud else "rest/api/search"
        expand_string = f"&expand={expand}" if expand else ""
        url += f"?cql={cql}{expand_string}"
        yield from self._paginate_url(url, limit)

    def paginated_groups_by_user_retrieval(
        self,
        user: dict[str, Any],
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        This is not an SQL like query.
        It's a confluence specific endpoint that can be used to fetch groups.
        """
        user_field = "accountId" if self._confluence.cloud else "key"
        user_value = user["accountId"] if self._confluence.cloud else user["userKey"]
        # Server uses userKey (but calls it key during the API call), Cloud uses accountId
        user_query = f"{user_field}={quote(user_value)}"

        url = f"rest/api/user/memberof?{user_query}"
        yield from self._paginate_url(url, limit)

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


def build_confluence_client(
    credentials: dict[str, Any],
    is_cloud: bool,
    wiki_base: str,
) -> OnyxConfluence:
    oauth2_dict: dict[str, Any] = {}
    url = wiki_base.rstrip("/")
    if "confluence_refresh_token" in credentials:
        oauth2_dict["client_id"] = OAUTH_CONFLUENCE_CLOUD_CLIENT_ID
        oauth2_dict["token"] = {}
        oauth2_dict["token"]["access_token"] = credentials["confluence_access_token"]
        url = f"https://api.atlassian.com/ex/confluence/{credentials['cloud_id']}"

    shared_base_kwargs = {
        "api_version": "cloud" if is_cloud else "latest",
        "backoff_and_retry": True,
        "cloud": is_cloud,
    }

    shared_probe_kwargs = {
        **shared_base_kwargs,
        "url": url,
        "max_backoff_retries": 6,
        "max_backoff_seconds": 10,
    }

    # probe connection with direct client, no retries
    if "confluence_refresh_token" in credentials:
        logger.info("Probing Confluence with OAuth Access Token.")

        confluence_client_with_minimal_retries = Confluence(
            oauth2=oauth2_dict, **shared_probe_kwargs
        )
    else:
        logger.info("Probing Confluence with Personal Access Token.")
        confluence_client_with_minimal_retries = Confluence(
            username=credentials["confluence_username"] if is_cloud else None,
            password=credentials["confluence_access_token"] if is_cloud else None,
            token=credentials["confluence_access_token"] if not is_cloud else None,
            **shared_probe_kwargs,
        )

    spaces = confluence_client_with_minimal_retries.get_all_spaces(limit=1)

    # uncomment the following for testing
    # the following is an attempt to retrieve the user's timezone
    # Unfornately, all data is returned in UTC regardless of the user's time zone
    # even tho CQL parses incoming times based on the user's time zone
    # space_key = spaces["results"][0]["key"]
    # space_details = confluence_client_with_minimal_retries.cql(f"space.key={space_key}+AND+type=space")

    if not spaces:
        raise RuntimeError(
            f"No spaces found at {wiki_base}! "
            "Check your credentials and wiki_base and make sure "
            "is_cloud is set correctly."
        )

    shared_final_kwargs = {
        **shared_base_kwargs,
        "max_backoff_retries": 10,
        "max_backoff_seconds": 60,
    }

    if "confluence_refresh_token" in credentials:
        return OnyxConfluence(url=url, oauth2=oauth2_dict, **shared_final_kwargs)

    return OnyxConfluence(
        url=url,
        # passing in username causes issues for Confluence data center
        username=credentials["confluence_username"] if is_cloud else None,
        password=credentials["confluence_access_token"] if is_cloud else None,
        token=credentials["confluence_access_token"] if not is_cloud else None,
        **shared_final_kwargs,
    )


def build_confluence_client_2(
    credential_provider: CredentialsProviderInterface,
    is_cloud: bool,
    wiki_base: str,
) -> OnyxConfluence:
    credentials = credential_provider.get_credentials()

    oauth2_dict: dict[str, Any] = {}
    url = wiki_base.rstrip("/")
    if "confluence_refresh_token" in credentials:
        oauth2_dict["client_id"] = OAUTH_CONFLUENCE_CLOUD_CLIENT_ID
        oauth2_dict["token"] = {}
        oauth2_dict["token"]["access_token"] = credentials["confluence_access_token"]
        url = f"https://api.atlassian.com/ex/confluence/{credentials['cloud_id']}"

    shared_base_kwargs = {
        "api_version": "cloud" if is_cloud else "latest",
        "backoff_and_retry": True,
        "cloud": is_cloud,
    }

    shared_probe_kwargs = {
        **shared_base_kwargs,
        "url": url,
        "max_backoff_retries": 6,
        "max_backoff_seconds": 10,
    }

    # probe connection with direct client, no retries
    if "confluence_refresh_token" in credentials:
        logger.info("Probing Confluence with OAuth Access Token.")

        confluence_client_with_minimal_retries = Confluence(
            oauth2=oauth2_dict, **shared_probe_kwargs
        )
    else:
        logger.info("Probing Confluence with Personal Access Token.")
        confluence_client_with_minimal_retries = Confluence(
            username=credentials["confluence_username"] if is_cloud else None,
            password=credentials["confluence_access_token"] if is_cloud else None,
            token=credentials["confluence_access_token"] if not is_cloud else None,
            **shared_probe_kwargs,
        )

    spaces = confluence_client_with_minimal_retries.get_all_spaces(limit=1)

    # uncomment the following for testing
    # the following is an attempt to retrieve the user's timezone
    # Unfornately, all data is returned in UTC regardless of the user's time zone
    # even tho CQL parses incoming times based on the user's time zone
    # space_key = spaces["results"][0]["key"]
    # space_details = confluence_client_with_minimal_retries.cql(f"space.key={space_key}+AND+type=space")

    if not spaces:
        raise RuntimeError(
            f"No spaces found at {wiki_base}! "
            "Check your credentials and wiki_base and make sure "
            "is_cloud is set correctly."
        )

    shared_final_kwargs = {
        **shared_base_kwargs,
        "max_backoff_retries": 10,
        "max_backoff_seconds": 60,
    }

    if "confluence_refresh_token" in credentials:
        return OnyxConfluence(url=url, oauth2=oauth2_dict, **shared_final_kwargs)

    return OnyxConfluence(
        url=url,
        # passing in username causes issues for Confluence data center
        username=credentials["confluence_username"] if is_cloud else None,
        password=credentials["confluence_access_token"] if is_cloud else None,
        token=credentials["confluence_access_token"] if not is_cloud else None,
        **shared_final_kwargs,
    )


_USER_EMAIL_CACHE: dict[str, str | None] = {}


def get_user_email_from_username__server(
    confluence_client: OnyxConfluence, user_name: str
) -> str | None:
    global _USER_EMAIL_CACHE
    if _USER_EMAIL_CACHE.get(user_name) is None:
        try:
            response = confluence_client.get_mobile_parameters(user_name)
            email = response.get("email")
        except Exception:
            # For now, we'll just return a string that indicates failure
            # We may want to revert to returning None in the future
            # email = None
            email = f"FAILED TO GET CONFLUENCE EMAIL FOR {user_name}"
            logger.warning(f"failed to get confluence email for {user_name}")
        _USER_EMAIL_CACHE[user_name] = email
    return _USER_EMAIL_CACHE[user_name]


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


def attachment_to_content(
    confluence_client: OnyxConfluence,
    attachment: dict[str, Any],
    parent_content_id: str | None = None,
) -> str | None:
    """If it returns None, assume that we should skip this attachment."""
    if not validate_attachment_filetype(attachment):
        return None

    if "api.atlassian.com" in confluence_client.url:
        # https://developer.atlassian.com/cloud/confluence/rest/v1/api-group-content---attachments/#api-wiki-rest-api-content-id-child-attachment-attachmentid-download-get
        if not parent_content_id:
            logger.warning(
                "parent_content_id is required to download attachments from Confluence Cloud!"
            )
            return None

        download_link = (
            confluence_client.url
            + f"/rest/api/content/{parent_content_id}/child/attachment/{attachment['id']}/download"
        )
    else:
        download_link = confluence_client.url + attachment["_links"]["download"]

    attachment_size = attachment["extensions"]["fileSize"]
    if attachment_size > CONFLUENCE_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD:
        logger.warning(
            f"Skipping {download_link} due to size. "
            f"size={attachment_size} "
            f"threshold={CONFLUENCE_CONNECTOR_ATTACHMENT_SIZE_THRESHOLD}"
        )
        return None

    logger.info(f"_attachment_to_content - _session.get: link={download_link}")

    response = confluence_client._session.get(download_link)
    if response.status_code != 200:
        logger.warning(
            f"Failed to fetch {download_link} with invalid status code {response.status_code}"
        )
        return None

    extracted_text = extract_file_text(
        io.BytesIO(response.content),
        file_name=attachment["title"],
        break_on_unprocessable=False,
    )
    if len(extracted_text) > CONFLUENCE_CONNECTOR_ATTACHMENT_CHAR_COUNT_THRESHOLD:
        logger.warning(
            f"Skipping {download_link} due to char count. "
            f"char count={len(extracted_text)} "
            f"threshold={CONFLUENCE_CONNECTOR_ATTACHMENT_CHAR_COUNT_THRESHOLD}"
        )
        return None

    return extracted_text


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
    for user in soup.findAll("ri:user"):
        user_id = (
            user.attrs["ri:account-id"]
            if "ri:account-id" in user.attrs
            else user.get("ri:userkey")
        )
        if not user_id:
            logger.warning(
                "ri:userkey not found in ri:user element. " f"Found attrs: {user.attrs}"
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
                f"Skipping retrieval of {html_page_reference} because because page data is missing"
            )
            continue

        page_title = page_data.attrs.get("ri:content-title")
        if not page_title:
            # only fetch pages that have a title
            logger.warning(
                f"Skipping retrieval of {html_page_reference} because it has no title"
            )
            continue

        if page_title in fetched_titles:
            # prevent recursive fetching of pages
            logger.debug(f"Skipping {page_title} because it has already been fetched")
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
                f"Error getting page contents for object {confluence_object}: {e}"
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
            logger.warning(f"Error processing ac:link-body: {e}")

    return format_document_soup(soup)
