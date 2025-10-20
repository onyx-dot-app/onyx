import re
import time
from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from enum import Enum
from typing import Any

from googleapiclient.errors import HttpError  # type: ignore

from onyx.connectors.google_drive.models import GoogleDriveFileType
from onyx.utils.logger import setup_logger
from onyx.utils.retry_wrapper import retry_builder

logger = setup_logger()


# Google Drive APIs are quite flakey and may 500 for an
# extended period of time. This is now addressed by checkpointing.
#
# NOTE: We previously tried to combat this here by adding a very
# long retry period (~20 minutes of trying, one request a minute.)
# This is no longer necessary due to checkpointing.
add_retries = retry_builder(tries=5, max_delay=10)

NEXT_PAGE_TOKEN_KEY = "nextPageToken"
PAGE_TOKEN_KEY = "pageToken"
ORDER_BY_KEY = "orderBy"


# See https://developers.google.com/drive/api/reference/rest/v3/files/list for more
class GoogleFields(str, Enum):
    ID = "id"
    CREATED_TIME = "createdTime"
    MODIFIED_TIME = "modifiedTime"
    NAME = "name"
    SIZE = "size"
    PARENTS = "parents"


def _execute_with_retry(request: Any) -> Any:
    max_attempts = 6
    attempt = 1

    while attempt < max_attempts:
        # Note for reasons unknown, the Google API will sometimes return a 429
        # and even after waiting the retry period, it will return another 429.
        # It could be due to a few possibilities:
        # 1. Other things are also requesting from the Drive/Gmail API with the same key
        # 2. It's a rolling rate limit so the moment we get some amount of requests cleared, we hit it again very quickly
        # 3. The retry-after has a maximum and we've already hit the limit for the day
        # or it's something else...
        try:
            return request.execute()
        except HttpError as error:
            attempt += 1

            if error.resp.status == 429:
                # Attempt to get 'Retry-After' from headers
                retry_after = error.resp.get("Retry-After")
                if retry_after:
                    sleep_time = int(retry_after)
                else:
                    # Extract 'Retry after' timestamp from error message
                    match = re.search(
                        r"Retry after (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)",
                        str(error),
                    )
                    if match:
                        retry_after_timestamp = match.group(1)
                        retry_after_dt = datetime.strptime(
                            retry_after_timestamp, "%Y-%m-%dT%H:%M:%S.%fZ"
                        ).replace(tzinfo=timezone.utc)
                        current_time = datetime.now(timezone.utc)
                        sleep_time = max(
                            int((retry_after_dt - current_time).total_seconds()),
                            0,
                        )
                    else:
                        logger.error(
                            f"No Retry-After header or timestamp found in error message: {error}"
                        )
                        sleep_time = 60

                sleep_time += 3  # Add a buffer to be safe

                logger.info(
                    f"Rate limit exceeded. Attempt {attempt}/{max_attempts}. Sleeping for {sleep_time} seconds."
                )
                time.sleep(sleep_time)

            else:
                raise

    # If we've exhausted all attempts
    raise Exception(f"Failed to execute request after {max_attempts} attempts")


def get_file_owners(file: GoogleDriveFileType, primary_admin_email: str) -> list[str]:
    """
    Get the owners of a file if the attribute is present.
    """
    return [
        email
        for owner in file.get("owners", [])
        if (email := owner.get("emailAddress"))
        and email.split("@")[-1] == primary_admin_email.split("@")[-1]
    ]


def _execute_single_retrieval(
    retrieval_function: Callable,
    continue_on_404_or_403: bool = False,
    **request_kwargs: Any,
) -> GoogleDriveFileType:
    """Execute a single retrieval from Google Drive API"""
    try:
        results = retrieval_function(**request_kwargs).execute()
    except HttpError as e:
        if e.resp.status >= 500:
            results = add_retries(
                lambda: retrieval_function(**request_kwargs).execute()
            )()
        elif e.resp.status == 400:
            if (
                "pageToken" in request_kwargs
                and "Invalid Value" in str(e)
                and "pageToken" in str(e)
            ):
                logger.warning(
                    f"Invalid page token: {request_kwargs['pageToken']}, retrying from start of request"
                )
                request_kwargs.pop("pageToken")
                return _execute_single_retrieval(
                    retrieval_function,
                    continue_on_404_or_403,
                    **request_kwargs,
                )
            logger.error(f"Error executing request: {e}")
            raise e
        elif e.resp.status == 404 or e.resp.status == 403:
            if continue_on_404_or_403:
                logger.debug(f"Error executing request: {e}")
                results = {}
            else:
                raise e
        elif e.resp.status == 429:
            results = _execute_with_retry(
                lambda: retrieval_function(**request_kwargs).execute()
            )
        else:
            logger.exception("Error executing request:")
            raise e

    return results


def execute_single_retrieval(
    retrieval_function: Callable,
    list_key: str | None = None,
    continue_on_404_or_403: bool = False,
    **request_kwargs: Any,
) -> Iterator[GoogleDriveFileType]:
    results = _execute_single_retrieval(
        retrieval_function,
        continue_on_404_or_403,
        **request_kwargs,
    )
    if list_key:
        for item in results.get(list_key, []):
            yield item
    else:
        yield results


# included for type purposes; caller should not need to address
# Nones unless max_num_pages is specified. Use
# execute_paginated_retrieval_with_max_pages instead if you want
# the early stop + yield None after max_num_pages behavior.
def execute_paginated_retrieval(
    retrieval_function: Callable,
    list_key: str | None = None,
    continue_on_404_or_403: bool = False,
    **kwargs: Any,
) -> Iterator[GoogleDriveFileType]:
    for item in _execute_paginated_retrieval(
        retrieval_function,
        list_key,
        continue_on_404_or_403,
        **kwargs,
    ):
        if not isinstance(item, str):
            yield item


def execute_paginated_retrieval_with_max_pages(
    retrieval_function: Callable,
    max_num_pages: int,
    list_key: str | None = None,
    continue_on_404_or_403: bool = False,
    **kwargs: Any,
) -> Iterator[GoogleDriveFileType | str]:
    yield from _execute_paginated_retrieval(
        retrieval_function,
        list_key,
        continue_on_404_or_403,
        max_num_pages=max_num_pages,
        **kwargs,
    )


def _execute_paginated_retrieval(
    retrieval_function: Callable,
    list_key: str | None = None,
    continue_on_404_or_403: bool = False,
    max_num_pages: int | None = None,
    **kwargs: Any,
) -> Iterator[GoogleDriveFileType | str]:
    """Execute a paginated retrieval from Google Drive API
    Args:
        retrieval_function: The specific list function to call (e.g., service.files().list)
        list_key: If specified, each object returned by the retrieval function
                  will be accessed at the specified key and yielded from.
        continue_on_404_or_403: If True, the retrieval will continue even if the request returns a 404 or 403 error.
        max_num_pages: If specified, the retrieval will stop after the specified number of pages and yield None.
        **kwargs: Arguments to pass to the list function
    """
    if "fields" not in kwargs or "nextPageToken" not in kwargs["fields"]:
        raise ValueError(
            "fields must contain nextPageToken for execute_paginated_retrieval"
        )
    next_page_token = kwargs.get(PAGE_TOKEN_KEY, "")
    num_pages = 0
    while next_page_token is not None:
        if max_num_pages is not None and num_pages >= max_num_pages:
            yield next_page_token
            return
        num_pages += 1
        request_kwargs = kwargs.copy()
        if next_page_token:
            request_kwargs[PAGE_TOKEN_KEY] = next_page_token
        results = _execute_single_retrieval(
            retrieval_function,
            continue_on_404_or_403,
            **request_kwargs,
        )

        next_page_token = results.get(NEXT_PAGE_TOKEN_KEY)
        if list_key:
            for item in results.get(list_key, []):
                yield item
        else:
            yield results
