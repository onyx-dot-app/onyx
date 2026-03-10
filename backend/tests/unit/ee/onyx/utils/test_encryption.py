"""Tests for EE AES-CBC encryption/decryption with explicit key support.

With EE mode enabled (via conftest), fetch_versioned_implementation resolves
to the EE implementations, so no patching of the MIT layer is needed.
"""

from unittest.mock import patch

import pytest

from ee.onyx.utils.encryption import _decrypt_bytes
from ee.onyx.utils.encryption import _encrypt_string
from ee.onyx.utils.encryption import _get_trimmed_key
from ee.onyx.utils.encryption import decrypt_bytes_to_string
from ee.onyx.utils.encryption import encrypt_string_to_bytes

EE_MODULE = "ee.onyx.utils.encryption"

# Keys must be exactly 16, 24, or 32 bytes for AES
KEY_16 = "a" * 16
KEY_16_ALT = "b" * 16
KEY_24 = "d" * 24
KEY_32 = "c" * 32


@pytest.fixture(autouse=True)
def _clear_key_cache() -> None:
    _get_trimmed_key.cache_clear()


class TestEncryptDecryptRoundTrip:
    def test_roundtrip_with_env_key(self) -> None:
        with patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", KEY_16):
            encrypted = _encrypt_string("hello world")
            assert encrypted != b"hello world"
            assert _decrypt_bytes(encrypted) == "hello world"

    def test_roundtrip_with_explicit_key(self) -> None:
        encrypted = _encrypt_string("secret data", key=KEY_32)
        assert encrypted != b"secret data"
        assert _decrypt_bytes(encrypted, key=KEY_32) == "secret data"

    def test_roundtrip_no_key(self) -> None:
        """Without any key, data is raw-encoded (no encryption)."""
        with patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", ""):
            encrypted = _encrypt_string("plain text")
            assert encrypted == b"plain text"
            assert _decrypt_bytes(encrypted) == "plain text"

    def test_explicit_key_overrides_env(self) -> None:
        with patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", KEY_16):
            encrypted = _encrypt_string("data", key=KEY_16_ALT)
            with pytest.raises(ValueError):
                _decrypt_bytes(encrypted, key=KEY_16)
            assert _decrypt_bytes(encrypted, key=KEY_16_ALT) == "data"

    def test_different_encryptions_produce_different_bytes(self) -> None:
        """Each encryption uses a random IV, so results differ."""
        a = _encrypt_string("same", key=KEY_16)
        b = _encrypt_string("same", key=KEY_16)
        assert a != b

    def test_roundtrip_empty_string(self) -> None:
        encrypted = _encrypt_string("", key=KEY_16)
        assert encrypted != b""
        assert _decrypt_bytes(encrypted, key=KEY_16) == ""

    def test_roundtrip_unicode(self) -> None:
        text = "日本語テスト 🔐 émojis"
        encrypted = _encrypt_string(text, key=KEY_16)
        assert _decrypt_bytes(encrypted, key=KEY_16) == text


class TestDecryptFallbackBehavior:
    def test_wrong_env_key_falls_back_to_raw_decode(self) -> None:
        """Default key path: AES fails on non-AES data → fallback to raw decode."""
        raw = "readable text".encode()
        with patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", KEY_16):
            assert _decrypt_bytes(raw) == "readable text"

    def test_explicit_wrong_key_raises(self) -> None:
        """Explicit key path: AES fails → raises, no fallback."""
        encrypted = _encrypt_string("secret", key=KEY_16)
        with pytest.raises(ValueError):
            _decrypt_bytes(encrypted, key=KEY_16_ALT)

    def test_explicit_none_key_with_no_env(self) -> None:
        """key=None with empty env → raw decode."""
        with patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", ""):
            assert _decrypt_bytes(b"hello", key=None) == "hello"

    def test_explicit_empty_string_key(self) -> None:
        """key='' means no encryption."""
        encrypted = _encrypt_string("test", key="")
        assert encrypted == b"test"
        assert _decrypt_bytes(encrypted, key="") == "test"


class TestKeyValidation:
    def test_key_too_short_raises(self) -> None:
        with pytest.raises(RuntimeError, match="too short"):
            _encrypt_string("data", key="short")

    def test_16_byte_key(self) -> None:
        encrypted = _encrypt_string("data", key=KEY_16)
        assert _decrypt_bytes(encrypted, key=KEY_16) == "data"

    def test_24_byte_key(self) -> None:
        encrypted = _encrypt_string("data", key=KEY_24)
        assert _decrypt_bytes(encrypted, key=KEY_24) == "data"

    def test_32_byte_key(self) -> None:
        encrypted = _encrypt_string("data", key=KEY_32)
        assert _decrypt_bytes(encrypted, key=KEY_32) == "data"

    def test_long_key_truncated_to_32(self) -> None:
        """Keys longer than 32 bytes are truncated to 32."""
        long_key = "e" * 64
        encrypted = _encrypt_string("data", key=long_key)
        assert _decrypt_bytes(encrypted, key=long_key) == "data"

    def test_20_byte_key_trimmed_to_16(self) -> None:
        """A 20-byte key is trimmed to the largest valid AES size that fits (16)."""
        key_20 = "f" * 20
        encrypted = _encrypt_string("data", key=key_20)
        assert _decrypt_bytes(encrypted, key=key_20) == "data"

        # Verify it was trimmed to 16 by checking that the first 16 bytes
        # of the key can also decrypt it
        key_16_same_prefix = "f" * 16
        assert _decrypt_bytes(encrypted, key=key_16_same_prefix) == "data"

    def test_25_byte_key_trimmed_to_24(self) -> None:
        """A 25-byte key is trimmed to the largest valid AES size that fits (24)."""
        key_25 = "g" * 25
        encrypted = _encrypt_string("data", key=key_25)
        assert _decrypt_bytes(encrypted, key=key_25) == "data"

        key_24_same_prefix = "g" * 24
        assert _decrypt_bytes(encrypted, key=key_24_same_prefix) == "data"

    def test_30_byte_key_trimmed_to_24(self) -> None:
        """A 30-byte key is trimmed to the largest valid AES size that fits (24)."""
        key_30 = "h" * 30
        encrypted = _encrypt_string("data", key=key_30)
        assert _decrypt_bytes(encrypted, key=key_30) == "data"

        key_24_same_prefix = "h" * 24
        assert _decrypt_bytes(encrypted, key=key_24_same_prefix) == "data"


class TestWrapperFunctions:
    """Test encrypt_string_to_bytes / decrypt_bytes_to_string pass key through.

    With EE mode enabled, the wrappers resolve to EE implementations automatically.
    """

    def test_wrapper_passes_key(self) -> None:
        encrypted = encrypt_string_to_bytes("payload", key=KEY_16)
        assert decrypt_bytes_to_string(encrypted, key=KEY_16) == "payload"

    def test_wrapper_no_key_uses_env(self) -> None:
        with patch(f"{EE_MODULE}.ENCRYPTION_KEY_SECRET", KEY_32):
            encrypted = encrypt_string_to_bytes("payload")
            assert decrypt_bytes_to_string(encrypted) == "payload"
