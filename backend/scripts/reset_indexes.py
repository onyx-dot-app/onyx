# This file is purely for development use, not included in any builds
import os
import sys
from time import sleep

import requests
from requests.exceptions import RequestException

# makes it so `PYTHONPATH=.` is not required when running this script
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from onyx.configs.app_configs import DOCUMENT_INDEX_NAME  # noqa: E402
from onyx.document_index.vespa.index import DOCUMENT_ID_ENDPOINT  # noqa: E402
from onyx.utils.logger import setup_logger  # noqa: E402

logger = setup_logger()


def wipe_vespa_index() -> bool:
    """
    Wipes the Vespa index by deleting all documents.
    """
    continuation = None
    should_continue = True
    RETRIES = 3

    while should_continue:
        params = {"selection": "true", "cluster": DOCUMENT_INDEX_NAME}
        if continuation:
            params["continuation"] = continuation

        for attempt in range(RETRIES):
            try:
                response = requests.delete(DOCUMENT_ID_ENDPOINT, params=params)
                response.raise_for_status()

                response_json = response.json()
                logger.info(f"Response: {response_json}")

                continuation = response_json.get("continuation")
                should_continue = bool(continuation)
                break  # Exit the retry loop if the request is successful

            except RequestException:
                logger.exception("Request failed")
                sleep(2**attempt)  # Exponential backoff
        else:
            logger.error(f"Max retries ({RETRIES}) exceeded. Exiting.")
            return False

    return True


def main() -> int:
    """
    Main function to execute the script.
    """
    try:
        succeeded = wipe_vespa_index()
    except Exception:
        logger.exception("wipe_vespa_index exceptioned.")
        return 1

    if not succeeded:
        logger.info("Vespa index wipe failed.")
        return 0

    logger.info("Vespa index wiped successfully.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
