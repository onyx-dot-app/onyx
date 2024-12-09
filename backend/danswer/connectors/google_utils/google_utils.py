import re
import time
from collections.abc import Callable
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from typing import Any

from googleapiclient.errors import HttpError  # type: ignore

from danswer.connectors.google_drive.models import GoogleDriveFileType
from danswer.utils.logger import setup_logger
from danswer.utils.retry_wrapper import retry_builder

logger = setup_logger()


# Google Drive APIs are quite flakey and may 500 for an
# extended period of time. Trying to combat here by adding a very
# long retry period (~20 minutes of trying every minute)
add_retries = retry_builder(tries=50, max_delay=30)


def _execute_with_retry(request: Any) -> Any:
    max_attempts = 10
    attempt = 1

    while attempt < max_attempts:
        # Note for reasons unknown, the Google API will sometimes return a 429
        # and even after waiting the retry period, it will return another 429.
        # It could be due to a few possibilities:
        # 1. Other things are also requesting from the Gmail API with the same key
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


def execute_paginated_retrieval(
    retrieval_function: Callable,
    list_key: str | None = None,
    continue_on_404_or_403: bool = False,
    **kwargs: Any,
) -> Iterator[GoogleDriveFileType]:
    """Execute a paginated retrieval from Google Drive API
    Args:
        retrieval_function: The specific list function to call (e.g., service.files().list)
        **kwargs: Arguments to pass to the list function
    """
    next_page_token = ""
    while next_page_token is not None:
        request_kwargs = kwargs.copy()
        if next_page_token:
            request_kwargs["pageToken"] = next_page_token

        try:
            results = retrieval_function(**request_kwargs).execute()
        except HttpError as e:
            if e.resp.status >= 500:
                results = add_retries(
                    lambda: retrieval_function(**request_kwargs).execute()
                )()
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

        next_page_token = results.get("nextPageToken")
        if list_key:
            for item in results.get(list_key, []):
                yield item
        else:
            yield results
