import re
import time
from typing import cast

import httpx

from onyx.configs.app_configs import MANAGED_VESPA
from onyx.configs.app_configs import VESPA_CLOUD_CERT_PATH
from onyx.configs.app_configs import VESPA_CLOUD_KEY_PATH
from onyx.configs.app_configs import VESPA_REQUEST_TIMEOUT
from onyx.document_index.vespa_constants import VESPA_APP_CONTAINER_URL
from onyx.utils.logger import setup_logger

logger = setup_logger()

# NOTE: This does not seem to be used in reality despite the Vespa Docs pointing to this code
# See here for reference: https://docs.vespa.ai/en/documents.html
# https://github.com/vespa-engine/vespa/blob/master/vespajlib/src/main/java/com/yahoo/text/Text.java

# Define allowed ASCII characters
ALLOWED_ASCII_CHARS: list[bool] = [False] * 0x80
ALLOWED_ASCII_CHARS[0x9] = True  # tab
ALLOWED_ASCII_CHARS[0xA] = True  # newline
ALLOWED_ASCII_CHARS[0xD] = True  # carriage return
for i in range(0x20, 0x7F):
    ALLOWED_ASCII_CHARS[i] = True  # printable ASCII chars
ALLOWED_ASCII_CHARS[0x7F] = True  # del - discouraged, but allowed


def is_text_character(codepoint: int) -> bool:
    """Returns whether the given codepoint is a valid text character."""
    if codepoint < 0x80:
        return ALLOWED_ASCII_CHARS[codepoint]
    if codepoint < 0xD800:
        return True
    if codepoint <= 0xDFFF:
        return False
    if codepoint < 0xFDD0:
        return True
    if codepoint <= 0xFDEF:
        return False
    if codepoint >= 0x10FFFE:
        return False
    return (codepoint & 0xFFFF) < 0xFFFE


def replace_invalid_doc_id_characters(text: str) -> str:
    """Replaces invalid document ID characters in text.
    NOTE: this must be called at the start of every vespa-related operation or else we
    risk discrepancies -> silent failures on deletion/update/insertion."""
    # There may be a more complete set of replacements that need to be made but Vespa docs are unclear
    # and users only seem to be running into this error with single quotes
    return text.replace("'", "_")


def remove_invalid_unicode_chars(text: str) -> str:
    """Vespa does not take in unicode chars that aren't valid for XML.
    This removes them."""
    _illegal_xml_chars_RE: re.Pattern = re.compile(
        "[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufdd0-\ufdef\ufffe\uffff]"
    )
    return _illegal_xml_chars_RE.sub("", text)


def get_vespa_http_client(no_timeout: bool = False, http2: bool = True) -> httpx.Client:
    """
    Configure and return an HTTP client for communicating with Vespa,
    including authentication if needed.
    """

    return httpx.Client(
        cert=(
            cast(tuple[str, str], (VESPA_CLOUD_CERT_PATH, VESPA_CLOUD_KEY_PATH))
            if MANAGED_VESPA
            else None
        ),
        verify=False if not MANAGED_VESPA else True,
        timeout=None if no_timeout else VESPA_REQUEST_TIMEOUT,
        http2=http2,
    )


def wait_for_vespa_with_timeout(wait_interval: int = 5, wait_limit: int = 60) -> bool:
    """Waits for Vespa to become ready subject to a timeout.
    Returns True if Vespa is ready, False otherwise."""

    time_start = time.monotonic()
    logger.info("Vespa: Readiness probe starting.")
    while True:
        try:
            client = get_vespa_http_client()
            response = client.get(f"{VESPA_APP_CONTAINER_URL}/state/v1/health")
            response.raise_for_status()

            response_dict = response.json()
            if response_dict["status"]["code"] == "up":
                logger.info("Vespa: Readiness probe succeeded. Continuing...")
                return True
        except Exception:
            pass

        time_elapsed = time.monotonic() - time_start
        if time_elapsed > wait_limit:
            logger.info(
                f"Vespa: Readiness probe did not succeed within the timeout "
                f"({wait_limit} seconds)."
            )
            return False

        logger.info(
            f"Vespa: Readiness probe ongoing. elapsed={time_elapsed:.1f} timeout={wait_limit:.1f}"
        )

        time.sleep(wait_interval)
