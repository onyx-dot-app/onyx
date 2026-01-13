"""Utility functions for Box connector."""

import json
from typing import Any


def parse_box_jwt_config(env_str: str) -> dict[str, Any]:
    """
    Parse a Box JWT configuration JSON string from environment variables into a Python dictionary.

    Handles double-escaped JSON strings that may come from environment variables.
    Also ensures that newline sequences in the private key are converted to actual newlines.

    Args:
        env_str: The JSON string from environment variables (may be double-escaped)

    Returns:
        Parsed JWT config dictionary

    Raises:
        json.JSONDecodeError: If the string cannot be parsed as JSON
    """
    # First try parsing normally
    try:
        config = json.loads(env_str)
    except json.JSONDecodeError:
        # Try removing extra escaping backslashes
        unescaped = env_str.replace('\\"', '"')
        # Remove leading/trailing quotes if present
        unescaped = unescaped.strip('"')
        # Now parse the JSON
        config = json.loads(unescaped)

    # Handle case where double-parsing returns a string instead of dict
    # (e.g., if the JSON was double-encoded as a JSON string)
    if isinstance(config, str):
        # Try parsing the string as JSON again
        try:
            config = json.loads(config)
        except json.JSONDecodeError:
            # If it's not valid JSON, raise an error
            raise json.JSONDecodeError(
                "Double-parsed JSON returned a string that is not valid JSON",
                config,
                0,
            )

    # Ensure private key has actual newlines (not \n sequences)
    if "boxAppSettings" in config and "appAuth" in config["boxAppSettings"]:
        private_key = config["boxAppSettings"]["appAuth"].get("privateKey", "")
        if private_key and "\\n" in private_key:
            # Convert \n sequences to actual newlines
            config["boxAppSettings"]["appAuth"]["privateKey"] = private_key.replace(
                "\\n", "\n"
            )

    return config
