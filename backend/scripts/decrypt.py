"""Decrypt a raw hex-encoded credential value.

Usage:
    python -m scripts.decrypt <hex_value>
    python -m scripts.decrypt <hex_value> --key "my-encryption-key"
    python -m scripts.decrypt <hex_value> --key ""

Pass --key "" to skip decryption and just decode the raw bytes as UTF-8.
Omit --key to use the keyring from the environment (ENCRYPTION_KEY_SECRET and
ENCRYPTION_KEYS), which also reads envelope values.
"""

import argparse
import binascii
import json
import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from ee.onyx.utils.encryption import (  # noqa: E402
    build_keyring,
    decrypt_with_keyring,
    get_keyring,
)


def decrypt_raw_credential(encrypted_value: str, key: str | None = None) -> None:
    """Decrypt and display a raw encrypted credential value.

    Args:
        encrypted_value: The hex-encoded encrypted credential value.
        key: Legacy encryption key to use. None means use the process keyring
             from the environment, empty string means just decode as UTF-8.
    """
    # Strip common hex prefixes
    if encrypted_value.startswith("\\x"):
        encrypted_value = encrypted_value[2:]
    elif encrypted_value.startswith("x"):
        encrypted_value = encrypted_value[1:]

    try:
        raw_bytes = binascii.unhexlify(encrypted_value)
    except binascii.Error:
        print("Error: Invalid hex-encoded string")
        sys.exit(1)

    keyring = get_keyring() if key is None else build_keyring(key, "", "")
    try:
        decrypted_str = decrypt_with_keyring(keyring, raw_bytes).plaintext
    except Exception as e:
        print(f"Error decrypting value: {e}")
        sys.exit(1)

    # Try to pretty-print as JSON, otherwise print raw
    try:
        parsed = json.loads(decrypted_str)
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError:
        print(decrypted_str)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decrypt a hex-encoded credential value."
    )
    parser.add_argument(
        "value",
        help="Hex-encoded encrypted value to decrypt.",
    )
    parser.add_argument(
        "--key",
        default=None,
        help=(
            "Legacy encryption key. Omit to use the keyring from the environment. "
            'Pass "" (empty) to just decode as UTF-8 without decryption.'
        ),
    )
    args = parser.parse_args()

    decrypt_raw_credential(args.value, key=args.key)


if __name__ == "__main__":
    main()
