import math
import time
from collections.abc import Callable
from collections.abc import Iterator
from typing import Any
from typing import cast
from typing import TypeVar
from urllib.parse import quote

from atlassian import Confluence  # type:ignore
from requests import HTTPError

from onyx.utils.logger import setup_logger

logger = setup_logger()


F = TypeVar("F", bound=Callable[..., Any])


RATE_LIMIT_MESSAGE_LOWERCASE = "Rate limit exceeded".lower()

# https://jira.atlassian.com/browse/CONFCLOUD-76433
_PROBLEMATIC_EXPANSIONS = "body.storage.value"
_REPLACEMENT_EXPANSIONS = "body.view.value"


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
def handle_confluence_rate_limit(confluence_call: F) -> F:
    def wrapped_call(*args: list[Any], **kwargs: Any) -> Any:
        MAX_RETRIES = 5

        TIMEOUT = 600
        timeout_at = time.monotonic() + TIMEOUT

        for attempt in range(MAX_RETRIES):
            if time.monotonic() > timeout_at:
                raise TimeoutError(
                    f"Confluence call attempts took longer than {TIMEOUT} seconds."
                )

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

    return cast(F, wrapped_call)


_DEFAULT_PAGINATION_LIMIT = 1000


class OnyxConfluence(Confluence):
    """
    This is a custom Confluence class that overrides the default Confluence class to add a custom CQL method.
    This is necessary because the default Confluence class does not properly support cql expansions.
    All methods are automatically wrapped with handle_confluence_rate_limit.
    """

    def __init__(self, url: str, *args: Any, **kwargs: Any) -> None:
        super(OnyxConfluence, self).__init__(url, *args, **kwargs)
        self._wrap_methods()

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

    def _wrap_methods(self) -> None:
        """
        For each attribute that is callable (i.e., a method) and doesn't start with an underscore,
        wrap it with handle_confluence_rate_limit.
        """
        for attr_name in dir(self):
            if callable(getattr(self, attr_name)) and not attr_name.startswith("_"):
                setattr(
                    self,
                    attr_name,
                    handle_confluence_rate_limit(getattr(self, attr_name)),
                )

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
                if _PROBLEMATIC_EXPANSIONS not in url_suffix:
                    logger.exception(
                        f"Error in confluence call to {url_suffix} \n"
                        f"Raw Response Text: {raw_response.text} \n"
                        f"Full Response: {raw_response.__dict__} \n"
                        f"Error: {e} \n"
                    )
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

            try:
                next_response = raw_response.json()
            except Exception as e:
                logger.exception(
                    f"Failed to parse response as JSON. Response: {raw_response.__dict__}"
                )
                raise e

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
        url = "rest/api/search/user" if self.cloud else "rest/api/search"
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
        user_field = "accountId" if self.cloud else "key"
        user_value = user["accountId"] if self.cloud else user["userKey"]
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


def _validate_connector_configuration(
    credentials: dict[str, Any],
    is_cloud: bool,
    wiki_base: str,
) -> None:
    # test connection with direct client, no retries
    confluence_client_with_minimal_retries = Confluence(
        api_version="cloud" if is_cloud else "latest",
        url=wiki_base.rstrip("/"),
        username=credentials["confluence_username"] if is_cloud else None,
        password=credentials["confluence_access_token"] if is_cloud else None,
        token=credentials["confluence_access_token"] if not is_cloud else None,
        backoff_and_retry=True,
        max_backoff_retries=6,
        max_backoff_seconds=10,
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


def build_confluence_client(
    credentials: dict[str, Any],
    is_cloud: bool,
    wiki_base: str,
) -> OnyxConfluence:
    _validate_connector_configuration(
        credentials=credentials,
        is_cloud=is_cloud,
        wiki_base=wiki_base,
    )
    return OnyxConfluence(
        api_version="cloud" if is_cloud else "latest",
        # Remove trailing slash from wiki_base if present
        url=wiki_base.rstrip("/"),
        # passing in username causes issues for Confluence data center
        username=credentials["confluence_username"] if is_cloud else None,
        password=credentials["confluence_access_token"] if is_cloud else None,
        token=credentials["confluence_access_token"] if not is_cloud else None,
        backoff_and_retry=True,
        max_backoff_retries=10,
        max_backoff_seconds=60,
        cloud=is_cloud,
    )
