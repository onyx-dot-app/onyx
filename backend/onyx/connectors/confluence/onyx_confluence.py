import json
import time
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
from pydantic import BaseModel
from redis import Redis
from requests import HTTPError

from ee.onyx.configs.app_configs import OAUTH_CONFLUENCE_CLOUD_CLIENT_ID
from ee.onyx.configs.app_configs import OAUTH_CONFLUENCE_CLOUD_CLIENT_SECRET
from onyx.connectors.confluence.utils import _handle_http_error
from onyx.connectors.confluence.utils import confluence_refresh_tokens
from onyx.connectors.confluence.utils import get_start_param_from_url
from onyx.connectors.confluence.utils import update_param_in_path
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


class ConfluenceRateLimitError(Exception):
    pass


class ConfluenceUser(BaseModel):
    user_id: str  # accountId in Cloud, userKey in Server
    username: str | None  # Confluence Cloud doesn't give usernames
    display_name: str
    # Confluence Data Center doesn't give email back by default,
    # have to fetch it with a different endpoint
    email: str | None
    type: str


_DEFAULT_PAGINATION_LIMIT = 1000
_MINIMUM_PAGINATION_LIMIT = 50


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

    def __init__(
        self,
        is_cloud: bool,
        url: str,
        credentials_provider: CredentialsProviderInterface,
    ) -> None:
        self._is_cloud = is_cloud
        self._url = url.rstrip("/")
        self._credentials_provider = credentials_provider

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

        self.shared_base_kwargs = {
            "api_version": "cloud" if is_cloud else "latest",
            "backoff_and_retry": True,
            "cloud": is_cloud,
        }

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

    def _probe_connection(
        self,
        **kwargs: Any,
    ) -> None:
        merged_kwargs = {**self.shared_base_kwargs, **kwargs}

        with self._credentials_provider:
            credentials, _ = self._renew_credentials()

            # probe connection with direct client, no retries
            if "confluence_refresh_token" in credentials:
                logger.info("Probing Confluence with OAuth Access Token.")

                oauth2_dict: dict[str, Any] = OnyxConfluence._make_oauth2_dict(
                    credentials
                )
                url = (
                    f"https://api.atlassian.com/ex/confluence/{credentials['cloud_id']}"
                )
                confluence_client_with_minimal_retries = Confluence(
                    url=url, oauth2=oauth2_dict, **merged_kwargs
                )
            else:
                logger.info("Probing Confluence with Personal Access Token.")
                url = self._url
                if self._is_cloud:
                    confluence_client_with_minimal_retries = Confluence(
                        url=url,
                        username=credentials["confluence_username"],
                        password=credentials["confluence_access_token"],
                        **merged_kwargs,
                    )
                else:
                    confluence_client_with_minimal_retries = Confluence(
                        url=url,
                        token=credentials["confluence_access_token"],
                        **merged_kwargs,
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
                    f"No spaces found at {url}! "
                    "Check your credentials and wiki_base and make sure "
                    "is_cloud is set correctly."
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
            logger.info("Connecting to Confluence with Personal Access Token.")
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
    # this uses the native rate limiting option provided by the
    # confluence client and otherwise applies a simpler set of error handling
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

        return wrapped_call

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

        def wrapped_method(*args: Any, **kwargs: Any) -> Any:
            return rate_limited_method(*args, **kwargs)

        return wrapped_method

    def _paginate_url(
        self, url_suffix: str, limit: int | None = None, auto_paginate: bool = False
    ) -> Iterator[dict[str, Any]]:
        """
        This will paginate through the top level query.
        """
        if not limit:
            limit = _DEFAULT_PAGINATION_LIMIT

        connection_char = "&" if "?" in url_suffix else "?"
        url_suffix += f"{connection_char}limit={limit}"

        while url_suffix:
            logger.debug(f"Making confluence call to {url_suffix}")
            try:
                raw_response = self.get(
                    path=url_suffix,
                    advanced_mode=True,
                )
            except Exception as e:
                logger.exception(f"Error in confluence call to {url_suffix}")
                raise e

            try:
                raw_response.raise_for_status()
            except Exception as e:
                logger.warning(f"Error in confluence call to {url_suffix}")

                # If the problematic expansion is in the url, replace it
                # with the replacement expansion and try again
                # If that fails, raise the error
                if _PROBLEMATIC_EXPANSIONS in url_suffix:
                    logger.warning(
                        f"Replacing {_PROBLEMATIC_EXPANSIONS} with {_REPLACEMENT_EXPANSIONS}"
                        " and trying again."
                    )
                    url_suffix = url_suffix.replace(
                        _PROBLEMATIC_EXPANSIONS,
                        _REPLACEMENT_EXPANSIONS,
                    )
                    continue
                if (
                    raw_response.status_code == 500
                    and limit > _MINIMUM_PAGINATION_LIMIT
                ):
                    new_limit = limit // 2
                    logger.warning(
                        f"Error in confluence call to {url_suffix} \n"
                        f"Raw Response Text: {raw_response.text} \n"
                        f"Full Response: {raw_response.__dict__} \n"
                        f"Error: {e} \n"
                        f"Reducing limit from {limit} to {new_limit} and trying again."
                    )
                    url_suffix = url_suffix.replace(
                        f"limit={limit}", f"limit={new_limit}"
                    )
                    limit = new_limit
                    continue

                logger.exception(
                    f"Error in confluence call to {url_suffix} \n"
                    f"Raw Response Text: {raw_response.text} \n"
                    f"Full Response: {raw_response.__dict__} \n"
                    f"Error: {e} \n"
                )
                raise e

            try:
                next_response = raw_response.json()
            except Exception as e:
                logger.exception(
                    f"Failed to parse response as JSON. Response: {raw_response.__dict__}"
                )
                raise e

            # yield the results individually
            results = cast(list[dict[str, Any]], next_response.get("results", []))
            yield from results

            old_url_suffix = url_suffix
            url_suffix = cast(str, next_response.get("_links", {}).get("next", ""))

            # make sure we don't update the start by more than the amount
            # of results we were able to retrieve. The Confluence API has a
            # weird behavior where if you pass in a limit that is too large for
            # the configured server, it will artificially limit the amount of
            # results returned BUT will not apply this to the start parameter.
            # This will cause us to miss results.
            if url_suffix and "start" in url_suffix:
                new_start = get_start_param_from_url(url_suffix)
                previous_start = get_start_param_from_url(old_url_suffix)
                if new_start - previous_start > len(results):
                    logger.debug(
                        f"Start was updated by more than the amount of results "
                        f"retrieved for `{url_suffix}`. This is a bug with Confluence, "
                        "but we have logic to work around it - don't worry this isn't"
                        f" causing an issue. Start: {new_start}, Previous Start: "
                        f"{previous_start}, Len Results: {len(results)}."
                    )

                    # Update the url_suffix to use the adjusted start
                    adjusted_start = previous_start + len(results)
                    url_suffix = update_param_in_path(
                        url_suffix, "start", str(adjusted_start)
                    )

            # some APIs don't properly paginate, so we need to manually update the `start` param
            if auto_paginate and len(results) > 0:
                previous_start = get_start_param_from_url(old_url_suffix)
                updated_start = previous_start + len(results)
                url_suffix = update_param_in_path(
                    old_url_suffix, "start", str(updated_start)
                )

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
    ) -> Iterator[ConfluenceUser]:
        """
        The search/user endpoint can be used to fetch users.
        It's a seperate endpoint from the content/search endpoint used only for users.
        Otherwise it's very similar to the content/search endpoint.
        """
        if self.cloud:
            cql = "type=user"
            url = "rest/api/search/user"
            expand_string = f"&expand={expand}" if expand else ""
            url += f"?cql={cql}{expand_string}"
            # endpoint doesn't properly paginate, so we need to manually update the `start` param
            # thus the auto_paginate flag
            for user_result in self._paginate_url(url, limit, auto_paginate=True):
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
            # https://developer.atlassian.com/server/confluence/rest/v900/api-group-user/#api-rest-api-user-list-get
            # ^ is only available on data center deployments
            # Example response:
            # [
            #     {
            #         'type': 'known',
            #         'username': 'admin',
            #         'userKey': '40281082950c5fe901950c61c55d0000',
            #         'profilePicture': {
            #             'path': '/images/icons/profilepics/default.svg',
            #             'width': 48,
            #             'height': 48,
            #             'isDefault': True
            #         },
            #         'displayName': 'Admin Test',
            #         '_links': {
            #             'self': 'http://localhost:8090/rest/api/user?key=40281082950c5fe901950c61c55d0000'
            #         },
            #         '_expandable': {
            #             'status': ''
            #         }
            #     }
            # ]
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
        user_field = "accountId" if self.cloud else "key"
        user_value = user_id
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

    def get_all_space_permissions_server(
        self,
        space_key: str,
    ) -> list[dict[str, Any]]:
        """
        This is a confluence server specific method that can be used to
        fetch the permissions of a space.
        This is better logging than calling the get_space_permissions method
        because it returns a jsonrpc response.
        TODO: Make this call these endpoints for newer confluence versions:
        - /rest/api/space/{spaceKey}/permissions
        - /rest/api/space/{spaceKey}/permissions/anonymous
        """
        url = "rpc/json-rpc/confluenceservice-v2"
        data = {
            "jsonrpc": "2.0",
            "method": "getSpacePermissionSets",
            "id": 7,
            "params": [space_key],
        }
        response = self.post(url, data=data)
        logger.debug(f"jsonrpc response: {response}")
        if not response.get("result"):
            logger.warning(
                f"No jsonrpc response for space permissions for space {space_key}"
                f"\nResponse: {response}"
            )

        return response.get("result", [])

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
        except Exception:
            logger.warning(f"failed to get confluence email for {user_name}")
            # For now, we'll just return None and log a warning. This means
            # we will keep retrying to get the email every group sync.
            email = None
            # We may want to just return a string that indicates failure so we dont
            # keep retrying
            # email = f"FAILED TO GET CONFLUENCE EMAIL FOR {user_name}"
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
