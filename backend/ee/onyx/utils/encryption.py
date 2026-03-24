from functools import lru_cache
from os import urandom

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import algorithms
from cryptography.hazmat.primitives.ciphers import Cipher
from cryptography.hazmat.primitives.ciphers import modes

from onyx.configs.app_configs import ENCRYPTION_KEY_SECRET
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import fetch_versioned_implementation

logger = setup_logger()


@lru_cache(maxsize=2)
def _get_trimmed_key(key: str) -> bytes:
    encoded_key = key.encode()
    key_length = len(encoded_key)
    if key_length < 16:
        raise RuntimeError("Invalid ENCRYPTION_KEY_SECRET - too short")

    # Trim to the largest valid AES key size that fits
    valid_lengths = [32, 24, 16]
    for size in valid_lengths:
        if key_length >= size:
            return encoded_key[:size]

    raise AssertionError("unreachable")


def _encrypt_string(input_str: str, key: str | None = None) -> bytes:
    effective_key = key if key is not None else ENCRYPTION_KEY_SECRET
    if not effective_key:
        return input_str.encode()

    trimmed = _get_trimmed_key(effective_key)
    iv = urandom(16)
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded_data = padder.update(input_str.encode()) + padder.finalize()

    cipher = Cipher(algorithms.AES(trimmed), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

    return iv + encrypted_data


def _decrypt_bytes(input_bytes: bytes, key: str | None = None) -> str:
    effective_key = key if key is not None else ENCRYPTION_KEY_SECRET
    if not effective_key:
        return input_bytes.decode()

    trimmed = _get_trimmed_key(effective_key)
    try:
        iv = input_bytes[:16]
        encrypted_data = input_bytes[16:]

        cipher = Cipher(
            algorithms.AES(trimmed), modes.CBC(iv), backend=default_backend()
        )
        decryptor = cipher.decryptor()
        decrypted_padded_data = decryptor.update(encrypted_data) + decryptor.finalize()

        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        decrypted_data = unpadder.update(decrypted_padded_data) + unpadder.finalize()

        return decrypted_data.decode()
    except (ValueError, UnicodeDecodeError):
        if key is not None:
            # Explicit key was provided — don't fall back silently
            raise
        # Read path: attempt raw UTF-8 decode as a fallback for legacy data.
        # Does NOT handle data encrypted with a different key — that
        # ciphertext is not valid UTF-8 and will raise below.
        logger.warning(
            "AES decryption failed — falling back to raw decode. Run the re-encrypt secrets script to rotate to the current key."
        )
        try:
            return input_bytes.decode()
        except UnicodeDecodeError:
            raise ValueError(
                "Data is not valid UTF-8 — likely encrypted with a different key. "
                "Run the re-encrypt secrets script to rotate to the current key."
            ) from None


def encrypt_string_to_bytes(input_str: str, key: str | None = None) -> bytes:
    versioned_encryption_fn = fetch_versioned_implementation(
        "onyx.utils.encryption", "_encrypt_string"
    )
    return versioned_encryption_fn(input_str, key=key)


def decrypt_bytes_to_string(input_bytes: bytes, key: str | None = None) -> str:
    versioned_decryption_fn = fetch_versioned_implementation(
        "onyx.utils.encryption", "_decrypt_bytes"
    )
    return versioned_decryption_fn(input_bytes, key=key)


def test_encryption() -> None:
    test_string = "PrivateGPT is the BEST!"
    encrypted_bytes = encrypt_string_to_bytes(test_string)
    decrypted_string = decrypt_bytes_to_string(encrypted_bytes)
    if test_string != decrypted_string:
        raise RuntimeError("Encryption decryption test failed")
