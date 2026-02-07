from typing import Any

from onyx.configs.app_configs import ENCRYPTION_KEY_SECRET
from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
)
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


# IMPORTANT DO NOT DELETE, THIS IS USED BY fetch_versioned_implementation
def _encrypt_string(input_str: str) -> bytes:
    if ENCRYPTION_KEY_SECRET:
        logger.warning("MIT version of Onyx does not support encryption of secrets.")
    return input_str.encode()


# IMPORTANT DO NOT DELETE, THIS IS USED BY fetch_versioned_implementation
def _decrypt_bytes(input_bytes: bytes) -> str:
    # No need to double warn. If you wish to learn more about encryption features
    # refer to the Onyx EE code
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


def encrypt_string_to_bytes(intput_str: str) -> bytes:
    versioned_encryption_fn = fetch_versioned_implementation(
        "onyx.utils.encryption", "_encrypt_string"
    )
    return versioned_encryption_fn(intput_str)


def decrypt_bytes_to_string(intput_bytes: bytes) -> str:
    versioned_decryption_fn = fetch_versioned_implementation(
        "onyx.utils.encryption", "_decrypt_bytes"
    )
    return versioned_decryption_fn(intput_bytes)
