import binascii
import json
import sys

from onyx.utils.encryption import decrypt_bytes_to_string


def decrypt_raw_credential(encrypted_value: str) -> None:
    """Decrypt and display a raw encrypted credential value

    Args:
        encrypted_value: The hex encoded encrypted credential value
    """
    try:
        # If string starts with 'x', remove it as it's just a prefix indicating hex
        if encrypted_value.startswith("x"):
            encrypted_value = encrypted_value[1:]
        elif encrypted_value.startswith("\\x"):
            encrypted_value = encrypted_value[2:]

        # Convert hex string to bytes
        encrypted_bytes = binascii.unhexlify(encrypted_value)

        # Decrypt the bytes
        decrypted_str = decrypt_bytes_to_string(encrypted_bytes)

        # Parse and pretty print the decrypted JSON
        decrypted_json = json.loads(decrypted_str)
        print("Decrypted credential value:")
        print(json.dumps(decrypted_json, indent=2))

    except binascii.Error:
        print("Error: Invalid hex encoded string")

    except json.JSONDecodeError as e:
        print(f"Decrypted raw value (not JSON): {e}")

    except Exception as e:
        print(f"Error decrypting value: {e}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python decrypt.py <hex_encoded_encrypted_value>")
        sys.exit(1)

    encrypted_value = sys.argv[1]
    decrypt_raw_credential(encrypted_value)
