"""Tests for SensitiveValue wrapper class."""

import json
from typing import Any

import pytest

from onyx.utils.sensitive import SensitiveAccessError
from onyx.utils.sensitive import SensitiveValue


def _encrypt_string(value: str) -> bytes:
    """Simple mock encryption (just encoding for tests)."""
    return value.encode("utf-8")


def _decrypt_string(value: bytes) -> str:
    """Simple mock decryption (just decoding for tests)."""
    return value.decode("utf-8")


class TestSensitiveValueString:
    """Tests for SensitiveValue with string values."""

    def test_get_value_raw(self) -> None:
        """Test getting raw unmasked value."""
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string("my-secret-token"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        assert sensitive.get_value(apply_mask=False) == "my-secret-token"

    def test_get_value_masked(self) -> None:
        """Test getting masked value with default masking."""
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string("my-very-long-secret-token-here"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        result = sensitive.get_value(apply_mask=True)
        # Default mask_string shows first 4 and last 4 chars
        assert result == "my-v...here"

    def test_get_value_masked_short_string(self) -> None:
        """Test that short strings are fully masked."""
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string("short"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        result = sensitive.get_value(apply_mask=True)
        # Short strings get fully masked
        assert result == "••••••••••••"

    def test_get_value_custom_mask_fn(self) -> None:
        """Test using a custom masking function."""
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string("secret"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        result = sensitive.get_value(
            apply_mask=True,
            mask_fn=lambda x: "REDACTED",  # noqa: ARG005
        )
        assert result == "REDACTED"

    def test_str_raises_error(self) -> None:
        """Test that str() raises SensitiveAccessError."""
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string("secret"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        with pytest.raises(SensitiveAccessError):
            str(sensitive)

    def test_repr_is_safe(self) -> None:
        """Test that repr() doesn't expose the value."""
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string("secret"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        result = repr(sensitive)
        assert "secret" not in result
        assert "SensitiveValue" in result
        assert "get_value" in result

    def test_iter_raises_error(self) -> None:
        """Test that iteration raises SensitiveAccessError."""
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string("secret"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        with pytest.raises(SensitiveAccessError):
            for _ in sensitive:  # type: ignore[attr-defined]
                pass

    def test_getitem_raises_error(self) -> None:
        """Test that subscript access raises SensitiveAccessError."""
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string("secret"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        with pytest.raises(SensitiveAccessError):
            _ = sensitive[0]

    def test_bool_returns_true(self) -> None:
        """Test that bool() works for truthiness checks."""
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string("secret"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        assert bool(sensitive) is True

    def test_equality_with_same_value(self) -> None:
        """Test equality comparison between SensitiveValues with same encrypted bytes."""
        encrypted = _encrypt_string("secret")
        sensitive1 = SensitiveValue(
            encrypted_bytes=encrypted,
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        sensitive2 = SensitiveValue(
            encrypted_bytes=encrypted,
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        assert sensitive1 == sensitive2

    def test_equality_with_different_value(self) -> None:
        """Test equality comparison between SensitiveValues with different encrypted bytes."""
        sensitive1 = SensitiveValue(
            encrypted_bytes=_encrypt_string("secret1"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        sensitive2 = SensitiveValue(
            encrypted_bytes=_encrypt_string("secret2"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        assert sensitive1 != sensitive2

    def test_equality_with_non_sensitive_raises(self) -> None:
        """Test that comparing with non-SensitiveValue raises error."""
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string("secret"),
            decrypt_fn=_decrypt_string,
            is_json=False,
        )
        with pytest.raises(SensitiveAccessError):
            _ = sensitive == "secret"


class TestSensitiveValueJson:
    """Tests for SensitiveValue with JSON/dict values."""

    def test_get_value_raw_dict(self) -> None:
        """Test getting raw unmasked dict value."""
        data: dict[str, Any] = {"api_key": "secret-key", "username": "user123"}
        sensitive: SensitiveValue[dict[str, Any]] = SensitiveValue(
            encrypted_bytes=_encrypt_string(json.dumps(data)),
            decrypt_fn=_decrypt_string,
            is_json=True,
        )
        result = sensitive.get_value(apply_mask=False)
        assert result == data

    def test_get_value_masked_dict(self) -> None:
        """Test getting masked dict value with default masking."""
        data = {"api_key": "my-very-long-api-key-value", "username": "user123456789"}
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string(json.dumps(data)),
            decrypt_fn=_decrypt_string,
            is_json=True,
        )
        result = sensitive.get_value(apply_mask=True)
        # Values should be masked
        assert "my-very-long-api-key-value" not in str(result)
        assert "user123456789" not in str(result)

    def test_getitem_raises_error_for_dict(self) -> None:
        """Test that subscript access raises SensitiveAccessError for dict."""
        data = {"api_key": "secret"}
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string(json.dumps(data)),
            decrypt_fn=_decrypt_string,
            is_json=True,
        )
        with pytest.raises(SensitiveAccessError):
            _ = sensitive["api_key"]

    def test_iter_raises_error_for_dict(self) -> None:
        """Test that iteration raises SensitiveAccessError for dict."""
        data = {"api_key": "secret"}
        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string(json.dumps(data)),
            decrypt_fn=_decrypt_string,
            is_json=True,
        )
        with pytest.raises(SensitiveAccessError):
            for _ in sensitive:  # type: ignore[attr-defined]
                pass


class TestSensitiveValueCaching:
    """Tests for lazy decryption caching."""

    def test_decryption_is_cached(self) -> None:
        """Test that decryption result is cached."""
        decrypt_count = [0]

        def counting_decrypt(value: bytes) -> str:
            decrypt_count[0] += 1
            return value.decode("utf-8")

        sensitive = SensitiveValue(
            encrypted_bytes=_encrypt_string("secret"),
            decrypt_fn=counting_decrypt,
            is_json=False,
        )

        # First access
        sensitive.get_value(apply_mask=False)
        assert decrypt_count[0] == 1

        # Second access should use cached value
        sensitive.get_value(apply_mask=False)
        assert decrypt_count[0] == 1

        # Masked access should also use cached value
        sensitive.get_value(apply_mask=True)
        assert decrypt_count[0] == 1
