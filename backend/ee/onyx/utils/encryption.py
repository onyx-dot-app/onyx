"""Encryption of secrets at rest.

Two ciphertext formats are readable and one is written:

- Envelope: AES-GCM under a key from ``ENCRYPTION_KEYS``. A header names the
  format version and the key id, and the header is authenticated with the body.
  Written when ``ENCRYPTION_WRITE_KEY_ID`` is set.
- Legacy: AES-CBC under ``ENCRYPTION_KEY_SECRET`` with a random IV first, or plain
  UTF-8 text when that secret is unset. Written when ``ENCRYPTION_WRITE_KEY_ID``
  is unset, which keeps an existing deployment on the format it already has.

A value that starts with the envelope magic is an envelope. A malformed header,
an unknown version or key id, or a failed authentication tag raises; the legacy
reader is never tried on it. Plain text never starts with the magic because its
first byte is not valid UTF-8, and a random legacy IV starts with the magic
with a chance of about 2^-40 per value.
"""

import base64
import binascii
import json
import re
from enum import Enum
from functools import cache
from os import urandom

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from pydantic import BaseModel, ConfigDict

from onyx.configs.app_configs import (
    ENCRYPTION_KEY_SECRET,
    ENCRYPTION_KEYS_JSON,
    ENCRYPTION_WRITE_KEY_ID,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

ENVELOPE_MAGIC = b"\xffONYX"
ENVELOPE_VERSION = 1
# Id under which a key derived from ENCRYPTION_KEY_SECRET can also write envelopes.
LEGACY_KEY_ID = "legacy"
# The AES-CBC key bytes are never used for AES-GCM: the envelope key under the
# legacy id is derived from them, so the two modes never share a key.
_LEGACY_ENVELOPE_KEY_INFO = b"onyx-envelope-v1-legacy"
KEY_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
ENVELOPE_KEY_BYTES = 32
_NONCE_BYTES = 12
_TAG_BYTES = 16
_CBC_IV_BYTES = 16
_LEGACY_KEY_SIZES = (32, 24, 16)
_SELF_TEST_TEXT = "Onyx encryption self-test"


class EncryptionConfigError(RuntimeError):
    """The encryption settings cannot be used. Raised at startup and on first use."""


class DecryptionError(ValueError):
    """The bytes cannot be read with the configured keys."""


class UnsupportedCiphertextError(DecryptionError):
    """An envelope that names a format version or key id this process does not have."""


class CiphertextFormat(str, Enum):
    PLAINTEXT = "plaintext"
    LEGACY_CBC = "legacy_cbc"
    ENVELOPE = "envelope"


class EnvelopeHeader(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int
    key_id: str


class DecryptedValue(BaseModel):
    model_config = ConfigDict(frozen=True)

    plaintext: str
    format: CiphertextFormat
    # The envelope key id, LEGACY_KEY_ID for AES-CBC, None for plain text.
    key_id: str | None


class Keyring(BaseModel):
    """The keys one process can read with, and the way it writes."""

    model_config = ConfigDict(frozen=True)

    # Envelope keys by id. Holds a key derived from the legacy secret under
    # LEGACY_KEY_ID when that secret is set.
    keys: dict[str, bytes]
    # AES-CBC key for legacy ciphertext, None when ENCRYPTION_KEY_SECRET is unset.
    legacy_key: bytes | None
    # None writes the legacy format.
    write_key_id: str | None

    @property
    def write_format(self) -> CiphertextFormat:
        if self.write_key_id is not None:
            return CiphertextFormat.ENVELOPE
        if self.legacy_key is not None:
            return CiphertextFormat.LEGACY_CBC
        return CiphertextFormat.PLAINTEXT


def _legacy_aes_key(secret: str) -> bytes:
    """The AES key the legacy format derives from ENCRYPTION_KEY_SECRET: the UTF-8
    bytes cut to the largest AES key size that fits."""
    encoded = secret.encode()
    for size in _LEGACY_KEY_SIZES:
        if len(encoded) >= size:
            return encoded[:size]
    raise EncryptionConfigError(
        "ENCRYPTION_KEY_SECRET is too short: it needs at least 16 bytes"
    )


def _legacy_envelope_key(legacy_key: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=ENVELOPE_KEY_BYTES,
        salt=None,
        info=_LEGACY_ENVELOPE_KEY_INFO,
    ).derive(legacy_key)


def _quoted_key_id(value: str) -> str:
    """A key id for an error message. A value that is not a valid id is not
    echoed: an operator who swaps an id and a key puts the key there."""
    return repr(value) if KEY_ID_PATTERN.match(value) else "(not a valid key id)"


def _reject_duplicate_key_ids(pairs: list[tuple[str, object]]) -> dict[str, object]:
    seen: set[str] = set()
    for key_id, _ in pairs:
        if key_id in seen:
            raise EncryptionConfigError(
                f"ENCRYPTION_KEYS names key id {_quoted_key_id(key_id)} more than once"
            )
        seen.add(key_id)
    return dict(pairs)


def _parse_envelope_keys(keys_json: str) -> dict[str, bytes]:
    try:
        parsed = json.loads(keys_json, object_pairs_hook=_reject_duplicate_key_ids)
    except json.JSONDecodeError as e:
        raise EncryptionConfigError(f"ENCRYPTION_KEYS is not valid JSON: {e}") from e
    if not isinstance(parsed, dict):
        raise EncryptionConfigError(
            "ENCRYPTION_KEYS must be a JSON object of key id -> base64 key"
        )

    keys: dict[str, bytes] = {}
    for position, (key_id, encoded) in enumerate(parsed.items(), start=1):
        if not isinstance(key_id, str) or not KEY_ID_PATTERN.match(key_id):
            # Not echoed: an id in the wrong place may be a key.
            raise EncryptionConfigError(
                f"ENCRYPTION_KEYS key id #{position} must match {KEY_ID_PATTERN.pattern}"
            )
        if key_id == LEGACY_KEY_ID:
            raise EncryptionConfigError(
                f"ENCRYPTION_KEYS key id {LEGACY_KEY_ID!r} is reserved for "
                "ENCRYPTION_KEY_SECRET"
            )
        if not isinstance(encoded, str):
            raise EncryptionConfigError(
                f"ENCRYPTION_KEYS value for {key_id!r} must be a base64 string"
            )
        try:
            key = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as e:
            raise EncryptionConfigError(
                f"ENCRYPTION_KEYS value for {key_id!r} is not standard base64"
            ) from e
        if len(key) != ENVELOPE_KEY_BYTES:
            raise EncryptionConfigError(
                f"ENCRYPTION_KEYS value for {key_id!r} decodes to {len(key)} bytes, "
                f"not {ENVELOPE_KEY_BYTES}"
            )
        keys[key_id] = key
    return keys


def build_keyring(legacy_secret: str, keys_json: str, write_key_id: str) -> Keyring:
    """Validate the three settings together. Pure, so tests and tools can build a
    keyring that is not the process one."""
    legacy_key = _legacy_aes_key(legacy_secret) if legacy_secret else None
    keys = _parse_envelope_keys(keys_json) if keys_json else {}
    if legacy_key is not None:
        keys[LEGACY_KEY_ID] = _legacy_envelope_key(legacy_key)

    if write_key_id and write_key_id not in keys:
        if write_key_id == LEGACY_KEY_ID:
            raise EncryptionConfigError(
                f"ENCRYPTION_WRITE_KEY_ID={LEGACY_KEY_ID!r} needs ENCRYPTION_KEY_SECRET"
            )
        raise EncryptionConfigError(
            f"ENCRYPTION_WRITE_KEY_ID {_quoted_key_id(write_key_id)} is not in "
            f"ENCRYPTION_KEYS (configured: {sorted(keys)})"
        )
    return Keyring(keys=keys, legacy_key=legacy_key, write_key_id=write_key_id or None)


@cache
def get_keyring() -> Keyring:
    """The process keyring, built from the environment on first use."""
    return build_keyring(
        ENCRYPTION_KEY_SECRET, ENCRYPTION_KEYS_JSON, ENCRYPTION_WRITE_KEY_ID
    )


def _envelope_header(key_id: str) -> bytes:
    return ENVELOPE_MAGIC + bytes([ENVELOPE_VERSION, len(key_id)]) + key_id.encode()


def parse_envelope_header(data: bytes) -> tuple[EnvelopeHeader, int] | None:
    """The header and its length, or None when the bytes are not an envelope.

    Raises DecryptionError for bytes that start with the magic but do not carry
    a well-formed header: those are never read as legacy ciphertext.
    """
    if not data.startswith(ENVELOPE_MAGIC):
        return None
    fixed_length = len(ENVELOPE_MAGIC) + 2
    if len(data) < fixed_length:
        raise DecryptionError("Envelope is shorter than its fixed header")
    version = data[len(ENVELOPE_MAGIC)]
    key_id_length = data[len(ENVELOPE_MAGIC) + 1]
    header_length = fixed_length + key_id_length
    key_id = data[fixed_length:header_length].decode("ascii", errors="replace")
    if key_id_length == 0 or not KEY_ID_PATTERN.match(key_id):
        raise DecryptionError("Envelope header does not carry a valid key id")
    if len(data) < header_length + _NONCE_BYTES + _TAG_BYTES:
        raise DecryptionError("Envelope is shorter than a nonce and a tag")
    return EnvelopeHeader(version=version, key_id=key_id), header_length


def _encrypt_envelope(key_id: str, key: bytes, plaintext: str) -> bytes:
    header = _envelope_header(key_id)
    nonce = urandom(_NONCE_BYTES)
    body = AESGCM(key).encrypt(nonce, plaintext.encode(), header)
    return header + nonce + body


def _decrypt_envelope(keyring: Keyring, data: bytes) -> DecryptedValue:
    parsed = parse_envelope_header(data)
    if parsed is None:
        raise AssertionError("caller checks for an envelope first")
    header, header_length = parsed
    if header.version != ENVELOPE_VERSION:
        raise UnsupportedCiphertextError(
            f"Envelope format version {header.version} is not supported"
        )
    key = keyring.keys.get(header.key_id)
    if key is None:
        raise UnsupportedCiphertextError(
            f"Envelope key id {header.key_id!r} is not in the keyring "
            f"(configured: {sorted(keyring.keys)})"
        )
    nonce = data[header_length : header_length + _NONCE_BYTES]
    body = data[header_length + _NONCE_BYTES :]
    try:
        plaintext = AESGCM(key).decrypt(nonce, body, data[:header_length])
    except InvalidTag as e:
        raise DecryptionError(
            f"Envelope under key id {header.key_id!r} failed authentication"
        ) from e
    try:
        text = plaintext.decode()
    except UnicodeDecodeError as e:
        raise DecryptionError("Envelope plaintext is not UTF-8") from e
    return DecryptedValue(
        plaintext=text, format=CiphertextFormat.ENVELOPE, key_id=header.key_id
    )


def _encrypt_legacy_cbc(key: bytes, plaintext: str) -> bytes:
    iv = urandom(_CBC_IV_BYTES)
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plaintext.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return iv + encryptor.update(padded) + encryptor.finalize()


def _decrypt_legacy_cbc(key: bytes, data: bytes) -> str:
    iv = data[:_CBC_IV_BYTES]
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(data[_CBC_IV_BYTES:]) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode()


def _decrypt_legacy(keyring: Keyring, data: bytes) -> DecryptedValue:
    if keyring.legacy_key is not None:
        try:
            return DecryptedValue(
                plaintext=_decrypt_legacy_cbc(keyring.legacy_key, data),
                format=CiphertextFormat.LEGACY_CBC,
                key_id=LEGACY_KEY_ID,
            )
        except (ValueError, UnicodeDecodeError):
            # Values stored before the deployment had a key are plain text.
            logger.warning(
                "Stored value is not AES-CBC under ENCRYPTION_KEY_SECRET; reading it "
                "as plain text. Run scripts/reencrypt_secrets.py to convert it."
            )
    try:
        return DecryptedValue(
            plaintext=data.decode(), format=CiphertextFormat.PLAINTEXT, key_id=None
        )
    except UnicodeDecodeError as e:
        raise DecryptionError(
            "Stored value is not an envelope, not AES-CBC under "
            "ENCRYPTION_KEY_SECRET, and not UTF-8 text"
        ) from e


def encrypt_with_keyring(keyring: Keyring, plaintext: str) -> bytes:
    if keyring.write_key_id is not None:
        return _encrypt_envelope(
            keyring.write_key_id, keyring.keys[keyring.write_key_id], plaintext
        )
    if keyring.legacy_key is not None:
        return _encrypt_legacy_cbc(keyring.legacy_key, plaintext)
    return plaintext.encode()


def decrypt_with_keyring(keyring: Keyring, data: bytes) -> DecryptedValue:
    if data.startswith(ENVELOPE_MAGIC):
        return _decrypt_envelope(keyring, data)
    return _decrypt_legacy(keyring, data)


# IMPORTANT DO NOT DELETE, THIS IS USED BY fetch_versioned_implementation
def _encrypt_string(input_str: str) -> bytes:
    return encrypt_with_keyring(get_keyring(), input_str)


# IMPORTANT DO NOT DELETE, THIS IS USED BY fetch_versioned_implementation
def _decrypt_bytes(input_bytes: bytes) -> str:
    return decrypt_with_keyring(get_keyring(), input_bytes).plaintext


def describe_keyring(keyring: Keyring) -> str:
    """Key ids and the write mode, for a startup log line. Never key material."""
    write_mode = (
        f"envelope under {keyring.write_key_id!r}"
        if keyring.write_key_id is not None
        else keyring.write_format.value
    )
    return f"readable key ids {sorted(keyring.keys)}, writes {write_mode}"


# IMPORTANT DO NOT DELETE, THIS IS USED BY fetch_versioned_implementation
def _validate_encryption_configuration() -> None:
    """Fail a process at startup when its encryption settings are unusable."""
    keyring = get_keyring()
    round_trip = decrypt_with_keyring(
        keyring, encrypt_with_keyring(keyring, _SELF_TEST_TEXT)
    )
    if round_trip.plaintext != _SELF_TEST_TEXT:
        raise EncryptionConfigError("Encryption self-test did not round-trip")
    logger.info("Encryption keyring: %s", describe_keyring(keyring))
