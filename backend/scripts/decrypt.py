"""Decrypt a raw hex-encoded credential value.

Usage:
    python -m scripts.decrypt <hex_value>
    python -m scripts.decrypt <hex_value> --key "my-encryption-key"
    python -m scripts.decrypt <hex_value> --key ""

Pass --key "" to skip decryption and just decode the raw bytes as UTF-8.
Omit --key to use the current ENCRYPTION_KEY_SECRET from the environment.
"""

import argparse
import binascii
import json
import os
import sys

parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(parent_dir)

from onyx.utils.encryption import decrypt_bytes_to_string  # noqa: E402
from onyx.utils.variable_functionality import global_version  # noqa: E402


def decrypt_raw_credential(encrypted_value: str, key: str | None = None) -> None:
    """Decrypt and display a raw encrypted credential value.

    Args:
        encrypted_value: The hex-encoded encrypted credential value.
        key: Encryption key to use. None means use ENCRYPTION_KEY_SECRET,
             empty string means just decode as UTF-8.
    """
    # Strip common hex prefixes
    if encrypted_value.startswith("\\x"):
        encrypted_value = encrypted_value[2:]
    elif encrypted_value.startswith("x"):
        encrypted_value = encrypted_value[1:]
    print(encrypted_value)

    try:
        raw_bytes = binascii.unhexlify(encrypted_value)
    except binascii.Error:
        print("Error: Invalid hex-encoded string")
        sys.exit(1)

    if key == "":
        # Empty key → just decode as UTF-8, no decryption
        try:
            decrypted_str = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as e:
            print(f"Error decoding bytes as UTF-8: {e}")
            sys.exit(1)
    else:
        print(key)
        try:
            decrypted_str = decrypt_bytes_to_string(raw_bytes, key=key)
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
            "Encryption key. Omit to use ENCRYPTION_KEY_SECRET from env. "
            'Pass "" (empty) to just decode as UTF-8 without decryption.'
        ),
    )
    args = parser.parse_args()

    global_version.set_ee()
    decrypt_raw_credential(args.value, key=args.key)
    global_version.unset_ee()


if __name__ == "__main__":
    main()
