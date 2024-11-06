import re
from typing import cast

import httpx

from danswer.configs.app_configs import MANAGED_VESPA
from danswer.configs.app_configs import VESPA_CLOUD_CERT_PATH
from danswer.configs.app_configs import VESPA_CLOUD_KEY_PATH
from danswer.configs.app_configs import VESPA_REQUEST_TIMEOUT

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
    """Replaces invalid document ID characters in text."""
    # There may be a more complete set of replacements that need to be made but Vespa docs are unclear
    # and users only seem to be running into this error with single quotes
    return text.replace("'", "_")


def remove_invalid_unicode_chars(text: str) -> str:
    """Vespa does not take in unicode chars that aren't valid for XML.
    This removes them."""
    _illegal_xml_chars_RE: re.Pattern = re.compile(
        "[\x00-\x08\x0b\x0c\x0e-\x1F\uD800-\uDFFF\uFFFE\uFFFF]"
    )
    return _illegal_xml_chars_RE.sub("", text)


def get_vespa_http_client(no_timeout: bool = False) -> httpx.Client:
    """
    Configure and return an HTTP client for communicating with Vespa,
    including authentication if needed.
    """

    return httpx.Client(
        cert=cast(tuple[str, str], (VESPA_CLOUD_CERT_PATH, VESPA_CLOUD_KEY_PATH))
        if MANAGED_VESPA
        else None,
        verify=False if not MANAGED_VESPA else True,
        timeout=None if no_timeout else VESPA_REQUEST_TIMEOUT,
        http2=True,
    )
