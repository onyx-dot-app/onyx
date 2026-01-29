"""
Tests demonstrating static type checking for SensitiveValue.

Run with: mypy tests/unit/onyx/utils/test_sensitive_typing.py --ignore-missing-imports

These tests show what mypy will catch when SensitiveValue is misused.
"""

from typing import Any

# This file demonstrates what mypy will catch.
# The commented-out code below would produce type errors.


def demonstrate_correct_usage() -> None:
    """Shows correct patterns that pass type checking."""
    from onyx.utils.sensitive import SensitiveValue
    from onyx.utils.encryption import encrypt_string_to_bytes, decrypt_bytes_to_string

    # Create a SensitiveValue
    encrypted = encrypt_string_to_bytes('{"api_key": "secret"}')
    sensitive: SensitiveValue[dict[str, Any]] = SensitiveValue(
        encrypted_bytes=encrypted,
        decrypt_fn=decrypt_bytes_to_string,
        is_json=True,
    )

    # CORRECT: Using get_value() to access the value
    raw_dict: dict[str, Any] = sensitive.get_value(apply_mask=False)
    assert raw_dict["api_key"] == "secret"

    masked_dict: dict[str, Any] = sensitive.get_value(apply_mask=True)
    assert "secret" not in str(masked_dict)

    # CORRECT: Using bool for truthiness
    if sensitive:
        print("Value exists")


# The code below demonstrates what mypy would catch.
# Uncomment to see the type errors.
"""
def demonstrate_incorrect_usage() -> None:
    '''Shows patterns that mypy will flag as errors.'''
    from onyx.utils.sensitive import SensitiveValue
    from onyx.utils.encryption import encrypt_string_to_bytes, decrypt_bytes_to_string

    encrypted = encrypt_string_to_bytes('{"api_key": "secret"}')
    sensitive: SensitiveValue[dict[str, Any]] = SensitiveValue(
        encrypted_bytes=encrypted,
        decrypt_fn=decrypt_bytes_to_string,
        is_json=True,
    )

    # ERROR: SensitiveValue doesn't support subscript access
    # mypy error: Value of type "SensitiveValue[dict[str, Any]]" is not indexable
    api_key = sensitive["api_key"]

    # ERROR: SensitiveValue doesn't support iteration
    # mypy error: "SensitiveValue[dict[str, Any]]" has no attribute "__iter__"
    for key in sensitive:
        print(key)

    # ERROR: Can't pass SensitiveValue where dict is expected
    # mypy error: Argument 1 has incompatible type "SensitiveValue[dict[str, Any]]"; expected "dict[str, Any]"
    def process_dict(d: dict[str, Any]) -> None:
        pass
    process_dict(sensitive)

    # ERROR: Can't use .get() on SensitiveValue
    # mypy error: "SensitiveValue[dict[str, Any]]" has no attribute "get"
    value = sensitive.get("api_key")
"""


def test_correct_usage_passes() -> None:
    """This test runs the correct usage demonstration."""
    demonstrate_correct_usage()
