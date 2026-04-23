from typing import Any

from onyx.configs.app_configs import ENCRYPTION_KEY_SECRET
from onyx.configs.constants import MASK_CREDENTIAL_CHAR
from onyx.configs.constants import MASK_CREDENTIAL_LONG_RE
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
)
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


# IMPORTANT DO NOT DELETE, THIS IS USED BY fetch_versioned_implementation
def _encrypt_string(input_str: str, key: str | None = None) -> bytes:
    if ENCRYPTION_KEY_SECRET:
        logger.warning("MIT version of Onyx does not support encryption of secrets.")
    elif key is not None:
        logger.debug("MIT encrypt called with explicit key — key ignored.")
    return input_str.encode()


# IMPORTANT DO NOT DELETE, THIS IS USED BY fetch_versioned_implementation
def _decrypt_bytes(input_bytes: bytes, key: str | None = None) -> str:
    if ENCRYPTION_KEY_SECRET:
        logger.warning("MIT version of Onyx does not support decryption of secrets.")
    elif key is not None:
        logger.debug("MIT decrypt called with explicit key — key ignored.")
    return input_bytes.decode()


def mask_string(sensitive_str: str) -> str:
    """Masks a sensitive string, showing first and last few characters.
    If the string is too short to safely mask, returns a fully masked placeholder.
    """
    visible_start = 4
    visible_end = 4
    min_masked_chars = 6

    if len(sensitive_str) < visible_start + visible_end + min_masked_chars:
        return "••••••••••••"

    return f"{sensitive_str[:visible_start]}...{sensitive_str[-visible_end:]}"


def is_masked_credential(value: str) -> bool:
    """Return True if the string looks like a `mask_string` placeholder.

    `mask_string` has two output formats:
    - Short strings (< 14 chars): "••••••••••••" (U+2022 BULLET)
    - Long strings (>= 14 chars): "abcd...wxyz" (first4 + "..." + last4)
    """
    return MASK_CREDENTIAL_CHAR in value or bool(MASK_CREDENTIAL_LONG_RE.match(value))


def reject_masked_credentials(credentials: dict[str, Any]) -> None:
    """Raise if any credential string value contains mask placeholder characters.

    Used as a defensive net at write boundaries so that masked values
    round-tripped from `mask_string` are never persisted as real credentials.

    Recurses into nested dicts and lists to stay symmetric with
    `mask_credential_dict`, which masks nested string values. The error
    message includes a dotted path like `oauth.client_secret` or
    `keys[2]` so callers can pinpoint the offending field.
    """
    _reject_masked_in_dict(credentials, path="")


def _reject_masked_in_dict(credentials: dict[str, Any], path: str) -> None:
    for key, val in credentials.items():
        field_path = f"{path}.{key}" if path else key
        _reject_masked_in_value(val, field_path)


def _reject_masked_in_value(val: Any, path: str) -> None:
    if isinstance(val, str):
        if is_masked_credential(val):
            raise ValueError(
                f"Credential field '{path}' contains masked placeholder "
                "characters. Please provide the actual credential value."
            )
        return
    if isinstance(val, dict):
        _reject_masked_in_dict(val, path=path)
        return
    if isinstance(val, list):
        for index, item in enumerate(val):
            _reject_masked_in_value(item, f"{path}[{index}]")


MASK_CREDENTIALS_WHITELIST = {
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
    "wiki_base",
    "cloud_name",
    "cloud_id",
}


def mask_credential_dict(credential_dict: dict[str, Any]) -> dict[str, Any]:
    masked_creds: dict[str, Any] = {}
    for key, val in credential_dict.items():
        if isinstance(val, str):
            # we want to pass the authentication_method field through so the frontend
            # can disambiguate credentials created by different methods
            if key in MASK_CREDENTIALS_WHITELIST:
                masked_creds[key] = val
            else:
                masked_creds[key] = mask_string(val)
        elif isinstance(val, dict):
            masked_creds[key] = mask_credential_dict(val)
        elif isinstance(val, list):
            masked_creds[key] = _mask_list(val)
        elif isinstance(val, (bool, type(None))):
            masked_creds[key] = val
        elif isinstance(val, (int, float)):
            masked_creds[key] = "*****"
        else:
            masked_creds[key] = "*****"

    return masked_creds


def _mask_list(items: list[Any]) -> list[Any]:
    masked: list[Any] = []
    for item in items:
        if isinstance(item, dict):
            masked.append(mask_credential_dict(item))
        elif isinstance(item, str):
            masked.append(mask_string(item))
        elif isinstance(item, list):
            masked.append(_mask_list(item))
        elif isinstance(item, (bool, type(None))):
            masked.append(item)
        else:
            masked.append("*****")
    return masked


def encrypt_string_to_bytes(intput_str: str, key: str | None = None) -> bytes:
    versioned_encryption_fn = fetch_versioned_implementation(
        "onyx.utils.encryption", "_encrypt_string"
    )
    return versioned_encryption_fn(intput_str, key=key)


def decrypt_bytes_to_string(intput_bytes: bytes, key: str | None = None) -> str:
    versioned_decryption_fn = fetch_versioned_implementation(
        "onyx.utils.encryption", "_decrypt_bytes"
    )
    return versioned_decryption_fn(intput_bytes, key=key)
