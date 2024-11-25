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

from danswer.utils.logger import setup_logger

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


_DEFAULT_PAGINATION_LIMIT = 100


class OnyxConfluence(Confluence):
    """
    This is a custom Confluence class that overrides the default Confluence class to add a custom CQL method.
    This is necessary because the default Confluence class does not properly support cql expansions.
    All methods are automatically wrapped with handle_confluence_rate_limit.
    """

    def __init__(self, url: str, *args: Any, **kwargs: Any) -> None:
        super(OnyxConfluence, self).__init__(url, *args, **kwargs)
        self._wrap_methods()

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
            try:
                logger.debug(f"Making confluence call to {url_suffix}")
                next_response = self.get(url_suffix)
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
        cql: str,
        expand: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        """
        The search/user endpoint can be used to fetch users.
        It's a seperate endpoint from the content/search endpoint used only for users.
        Otherwise it's very similar to the content/search endpoint.
        """
        expand_string = f"&expand={expand}" if expand else ""
        yield from self._paginate_url(
            f"rest/api/search/user?cql={cql}{expand_string}", limit
        )

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
        """
        group_name = quote(group_name)
        yield from self._paginate_url(f"rest/api/group/{group_name}/member", limit)
