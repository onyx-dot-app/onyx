import time
from typing import cast

import httpx

from onyx.configs.app_configs import (
    MANAGED_VESPA,
    VESPA_CLOUD_CERT_PATH,
    VESPA_CLOUD_KEY_PATH,
    VESPA_REQUEST_TIMEOUT,
)
from onyx.document_index.vespa_constants import VESPA_APP_CONTAINER_URL
from onyx.utils.logger import setup_logger

logger = setup_logger()


def replace_invalid_doc_id_characters(text: str) -> str:
    """Replaces invalid document ID characters in text.
    NOTE: this must be called at the start of every vespa-related operation or else we
    risk discrepancies -> silent failures on deletion/update/insertion."""
    # There may be a more complete set of replacements that need to be made but Vespa docs are unclear
    # and users only seem to be running into this error with single quotes
    return text.replace("'", "_")


def get_vespa_http_client(
    no_timeout: bool = False, http2: bool = True, timeout: int | None = None
) -> httpx.Client:
    """
    Configures and returns an HTTP client for communicating with Vespa,
    including authentication if needed.
    """
    return httpx.Client(
        cert=(
            cast(tuple[str, str], (VESPA_CLOUD_CERT_PATH, VESPA_CLOUD_KEY_PATH))
            if MANAGED_VESPA
            else None
        ),
        verify=False if not MANAGED_VESPA else True,
        timeout=None if no_timeout else (timeout or VESPA_REQUEST_TIMEOUT),
        http2=http2,
    )


def wait_for_vespa_with_timeout(wait_interval: int = 5, wait_limit: int = 60) -> bool:
    """Waits for Vespa to become ready subject to a timeout.
    Returns True if Vespa is ready, False otherwise."""

    time_start = time.monotonic()
    logger.info("Vespa: Readiness probe starting.")
    while True:
        url = f"{VESPA_APP_CONTAINER_URL}/state/v1/health"
        try:
            client = get_vespa_http_client()
            response = client.get(url)
            response.raise_for_status()

            response_dict = response.json()
            if response_dict["status"]["code"] == "up":
                logger.info("Vespa: Readiness probe succeeded. Continuing...")
                return True
        except Exception as e:
            logger.warning(
                "Vespa: Readiness probe failed trying to connect to %s. Exception: %s",
                url,
                e,
            )

        time_elapsed = time.monotonic() - time_start
        if time_elapsed > wait_limit:
            logger.info(
                "Vespa: Readiness probe did not succeed within the timeout (%s seconds).",
                wait_limit,
            )
            return False

        logger.info(
            "Vespa: Readiness probe ongoing. elapsed=%s timeout=%s",
            format(time_elapsed, ".1f"),
            format(wait_limit, ".1f"),
        )

        time.sleep(wait_interval)
