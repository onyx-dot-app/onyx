"""
Wrapper class for sensitive values that require explicit masking decisions.

This module provides a wrapper for encrypted values that forces developers to
make an explicit decision about whether to mask the value when accessing it.
This prevents accidental exposure of sensitive data in API responses.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from typing import Generic
from typing import NoReturn
from typing import TypeVar
from unittest.mock import MagicMock

from onyx.utils.encryption import mask_credential_dict
from onyx.utils.encryption import mask_string


T = TypeVar("T", str, dict[str, Any])


def make_mock_sensitive_value(value: dict[str, Any] | str | None) -> MagicMock:
    """
    Create a mock SensitiveValue for use in tests.

    This helper makes it easy to create mock objects that behave like
    SensitiveValue for testing code that uses credentials.

    Args:
        value: The value to return from get_value(). Can be a dict, string, or None.

    Returns:
        A MagicMock configured to behave like a SensitiveValue.

    Example:
        >>> mock_credential = MagicMock()
        >>> mock_credential.credential_json = make_mock_sensitive_value({"api_key": "secret"})
        >>> # Now mock_credential.credential_json.get_value(apply_mask=False) returns {"api_key": "secret"}
    """
    if value is None:
        return None  # type: ignore[return-value]

    mock = MagicMock(spec=SensitiveValue)
    mock.get_value.return_value = value
    mock.__bool__ = lambda self: True  # noqa: ARG005
    return mock


class SensitiveAccessError(Exception):
    """Raised when attempting to access a SensitiveValue without explicit masking decision."""


class SensitiveValue(Generic[T]):
    """
    Wrapper requiring explicit masking decisions for sensitive data.

    This class wraps encrypted data and forces callers to make an explicit
    decision about whether to mask the value when accessing it. This prevents
    accidental exposure of sensitive data.

    Usage:
        # Get raw value (for internal use like connectors)
        raw_value = sensitive.get_value(apply_mask=False)

        # Get masked value (for API responses)
        masked_value = sensitive.get_value(apply_mask=True)

    Raises SensitiveAccessError when:
        - Attempting to convert to string via str() or repr()
        - Attempting to iterate over the value
        - Attempting to subscript the value (e.g., value["key"])
        - Attempting to serialize to JSON without explicit get_value()
    """

    def __init__(
        self,
        *,
        encrypted_bytes: bytes,
        decrypt_fn: Callable[[bytes], str],
        is_json: bool = False,
    ) -> None:
        """
        Initialize a SensitiveValue wrapper.

        Args:
            encrypted_bytes: The encrypted bytes to wrap
            decrypt_fn: Function to decrypt bytes to string
            is_json: If True, the decrypted value is JSON and will be parsed to dict
        """
        self._encrypted_bytes = encrypted_bytes
        self._decrypt_fn = decrypt_fn
        self._is_json = is_json
        # Cache for decrypted value to avoid repeated decryption
        self._decrypted_value: T | None = None

    def _decrypt(self) -> T:
        """Lazily decrypt and cache the value."""
        if self._decrypted_value is None:
            decrypted_str = self._decrypt_fn(self._encrypted_bytes)
            if self._is_json:
                self._decrypted_value = json.loads(decrypted_str)
            else:
                self._decrypted_value = decrypted_str  # type: ignore[assignment]
        # The return type should always match T based on is_json flag
        return self._decrypted_value  # type: ignore[return-value]

    def get_value(
        self,
        *,
        apply_mask: bool,
        mask_fn: Callable[[T], T] | None = None,
    ) -> T:
        """
        Get the value with explicit masking decision.

        Args:
            apply_mask: Required. True = return masked value, False = return raw value
            mask_fn: Optional custom masking function. Defaults to mask_string for
                     strings and mask_credential_dict for dicts.

        Returns:
            The value, either masked or raw depending on apply_mask.
        """
        value = self._decrypt()

        if not apply_mask:
            return value

        # Apply masking
        if mask_fn is not None:
            return mask_fn(value)

        # Use default masking based on type
        # Type narrowing doesn't work well here due to the generic T,
        # but at runtime the types will match
        if isinstance(value, dict):
            return mask_credential_dict(value)
        elif isinstance(value, str):
            return mask_string(value)
        else:
            raise ValueError(f"Cannot mask value of type {type(value)}")

    def __bool__(self) -> bool:
        """Allow truthiness checks without exposing the value."""
        return True

    def __str__(self) -> NoReturn:
        """Prevent accidental string conversion."""
        raise SensitiveAccessError(
            "Cannot convert SensitiveValue to string. "
            "Use .get_value(apply_mask=True/False) to access the value."
        )

    def __repr__(self) -> str:
        """Prevent accidental repr exposure."""
        return "<SensitiveValue: use .get_value(apply_mask=True/False) to access>"

    def __iter__(self) -> NoReturn:
        """Prevent iteration over the value."""
        raise SensitiveAccessError(
            "Cannot iterate over SensitiveValue. "
            "Use .get_value(apply_mask=True/False) to access the value."
        )

    def __getitem__(self, key: Any) -> NoReturn:
        """Prevent subscript access."""
        raise SensitiveAccessError(
            "Cannot subscript SensitiveValue. "
            "Use .get_value(apply_mask=True/False) to access the value."
        )

    def __eq__(self, other: Any) -> bool:
        """Prevent direct comparison which might expose value."""
        if isinstance(other, SensitiveValue):
            # Compare encrypted bytes for equality check
            return self._encrypted_bytes == other._encrypted_bytes
        raise SensitiveAccessError(
            "Cannot compare SensitiveValue with non-SensitiveValue. "
            "Use .get_value(apply_mask=True/False) to access the value for comparison."
        )

    def __hash__(self) -> int:
        """Allow hashing based on encrypted bytes."""
        return hash(self._encrypted_bytes)

    # Prevent JSON serialization
    def __json__(self) -> Any:
        """Prevent JSON serialization."""
        raise SensitiveAccessError(
            "Cannot serialize SensitiveValue to JSON. "
            "Use .get_value(apply_mask=True/False) to access the value."
        )

    # For Pydantic compatibility
    @classmethod
    def __get_pydantic_core_schema__(cls, source_type: Any, handler: Any) -> Any:
        """Prevent Pydantic from serializing without explicit get_value()."""
        raise SensitiveAccessError(
            "Cannot serialize SensitiveValue in Pydantic model. "
            "Use .get_value(apply_mask=True/False) to access the value before serialization."
        )
