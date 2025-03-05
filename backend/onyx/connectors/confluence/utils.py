import math
import time
from collections.abc import Callable
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from typing import cast
from typing import TYPE_CHECKING
from typing import TypeVar
from urllib.parse import parse_qs
from urllib.parse import quote
from urllib.parse import urlparse

import bs4
import requests
from pydantic import BaseModel

from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    pass

logger = setup_logger()

CONFLUENCE_OAUTH_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
RATE_LIMIT_MESSAGE_LOWERCASE = "Rate limit exceeded".lower()


class TokenResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str
    refresh_token: str
    scope: str


def validate_attachment_filetype(attachment: dict[str, Any]) -> bool:
    return attachment["metadata"]["mediaType"] not in [
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/svg+xml",
        "video/mp4",
        "video/quicktime",
    ]


def build_confluence_document_id(
    base_url: str, content_url: str, is_cloud: bool
) -> str:
    """For confluence, the document id is the page url for a page based document
        or the attachment download url for an attachment based document

    Args:
        base_url (str): The base url of the Confluence instance
        content_url (str): The url of the page or attachment download url

    Returns:
        str: The document id
    """
    if is_cloud and not base_url.endswith("/wiki"):
        base_url += "/wiki"
    return f"{base_url}{content_url}"


def _extract_referenced_attachment_names(page_text: str) -> list[str]:
    """Parse a Confluence html page to generate a list of current
        attachments in use

    Args:
        text (str): The page content

    Returns:
        list[str]: List of filenames currently in use by the page text
    """
    referenced_attachment_filenames = []
    soup = bs4.BeautifulSoup(page_text, "html.parser")
    for attachment in soup.findAll("ri:attachment"):
        referenced_attachment_filenames.append(attachment.attrs["ri:filename"])
    return referenced_attachment_filenames


def datetime_from_string(datetime_string: str) -> datetime:
    datetime_object = datetime.fromisoformat(datetime_string)

    if datetime_object.tzinfo is None:
        # If no timezone info, assume it is UTC
        datetime_object = datetime_object.replace(tzinfo=timezone.utc)
    else:
        # If not in UTC, translate it
        datetime_object = datetime_object.astimezone(timezone.utc)

    return datetime_object


def confluence_refresh_tokens(
    client_id: str, client_secret: str, cloud_id: str, refresh_token: str
) -> dict[str, Any]:
    # rotate the refresh and access token
    # Note that access tokens are only good for an hour in confluence cloud,
    # so we're going to have problems if the connector runs for longer
    # https://developer.atlassian.com/cloud/confluence/oauth-2-3lo-apps/#use-a-refresh-token-to-get-another-access-token-and-refresh-token-pair
    response = requests.post(
        CONFLUENCE_OAUTH_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
    )

    try:
        token_response = TokenResponse.model_validate_json(response.text)
    except Exception:
        raise RuntimeError("Confluence Cloud token refresh failed.")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=token_response.expires_in)

    new_credentials: dict[str, Any] = {}
    new_credentials["confluence_access_token"] = token_response.access_token
    new_credentials["confluence_refresh_token"] = token_response.refresh_token
    new_credentials["created_at"] = now.isoformat()
    new_credentials["expires_at"] = expires_at.isoformat()
    new_credentials["expires_in"] = token_response.expires_in
    new_credentials["scope"] = token_response.scope
    new_credentials["cloud_id"] = cloud_id
    return new_credentials


F = TypeVar("F", bound=Callable[..., Any])


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
            except requests.HTTPError as e:
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


def _handle_http_error(e: requests.HTTPError, attempt: int) -> int:
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


def get_single_param_from_url(url: str, param: str) -> str | None:
    """Get a parameter from a url"""
    parsed_url = urlparse(url)
    return parse_qs(parsed_url.query).get(param, [None])[0]


def get_start_param_from_url(url: str) -> int:
    """Get the start parameter from a url"""
    start_str = get_single_param_from_url(url, "start")
    if start_str is None:
        return 0
    return int(start_str)


def update_param_in_path(path: str, param: str, value: str) -> str:
    """Update a parameter in a path. Path should look something like:

    /api/rest/users?start=0&limit=10
    """
    parsed_url = urlparse(path)
    query_params = parse_qs(parsed_url.query)
    query_params[param] = [value]
    return (
        path.split("?")[0]
        + "?"
        + "&".join(f"{k}={quote(v[0])}" for k, v in query_params.items())
    )
