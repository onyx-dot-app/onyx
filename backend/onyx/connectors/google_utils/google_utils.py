import json
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
    next_page_token = kwargs.get(PAGE_TOKEN_KEY, "")
    while next_page_token is not None:
        request_kwargs = kwargs.copy()
        if next_page_token:
            request_kwargs[PAGE_TOKEN_KEY] = next_page_token

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

        next_page_token = results.get(NEXT_PAGE_TOKEN_KEY)
        if list_key:
            for item in results.get(list_key, []):
                yield item
        else:
            yield results


# https://developers.google.com/apps-script/api/reference/rest/v1/File#FileType
class AppsScriptFileType(str, Enum):
    UNSPECIFIED = "ENUM_TYPE_UNSPECIFIED"
    SERVER_JS = "SERVER_JS"
    HTML = "HTML"
    JSON = "JSON"


SMART_CHIP_RETRIEVAL_FUNCTIONS = [
    ("docToChips", ["document_id"]),
    ("getKey", ["tabInd", "paragraphInd", "nonTextInd"]),
    ("parseParagraph", ["paragraph", "callback"]),
    ("parseTable", ["table", "callback"]),
]

SMART_CHIP_SCRIPT_FILE_NAME = "Smart_Chip_Extractor"


# https://developers.google.com/apps-script/api/reference/rest/v1/projects/updateContent
def create_scripts_file_objects() -> list[GoogleDriveFileType]:
    with open("onyx/connectors/google_drive/smart_chip_retrieval.gs", "r") as f:
        script_source = f.read()
    with open("onyx/connectors/google_drive/appsscript.json", "r") as f:
        appsscript_source = json.loads(f.read())
    return [
        {
            "name": "appsscript",
            "type": AppsScriptFileType.JSON.value,
            "source": json.dumps(appsscript_source),
        },
        {
            "name": SMART_CHIP_SCRIPT_FILE_NAME,
            "type": AppsScriptFileType.SERVER_JS.value,
            "source": script_source,
            "functionSet": {
                "values": [
                    {
                        "name": name,
                        "parameters": params,
                    }
                    for name, params in SMART_CHIP_RETRIEVAL_FUNCTIONS
                ],
            },
        },
    ]
