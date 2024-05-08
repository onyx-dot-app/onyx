from danswer.configs.app_configs import ENCRYPTION_KEY_SECRET
from danswer.utils.logger import setup_logger
from danswer.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


def _encrypt_string(input_str: str) -> bytes:
    if ENCRYPTION_KEY_SECRET:
        logger.warning("MIT version of Danswer does not support encryption of secrets.")
    return input_str.encode()


def _decrypt_bytes(input_bytes: bytes) -> str:
    # No need to double warn. If you wish to learn more about encryption features
    # refer to the Danswer EE code
    return input_bytes.decode()


def encrypt_string_to_bytes(intput_str: str) -> bytes:
    versioned_encryption_fn = fetch_versioned_implementation(
        "danswer.utils.encryption", "_encrypt_string"
    )
    return versioned_encryption_fn(intput_str)


def decrypt_bytes_to_string(intput_bytes: bytes) -> str:
    versioned_decryption_fn = fetch_versioned_implementation(
        "danswer.utils.encryption", "_decrypt_bytes"
    )
    return versioned_decryption_fn(intput_bytes)
