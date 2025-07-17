import base64
import json
import os
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.serialization import pkcs12
from fastapi import HTTPException
from fastapi import status
from fastapi import UploadFile

from onyx.connectors.google_utils.shared_constants import (
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
)


class BasicAuthenticationError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that converts datetime objects to ISO format strings."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def get_json_line(
    json_dict: dict[str, Any], encoder: type[json.JSONEncoder] = DateTimeEncoder
) -> str:
    """
    Convert a dictionary to a JSON string with datetime handling, and add a newline.

    Args:
        json_dict: The dictionary to be converted to JSON.
        encoder: JSON encoder class to use, defaults to DateTimeEncoder.

    Returns:
        A JSON string representation of the input dictionary with a newline character.
    """
    return json.dumps(json_dict, cls=encoder) + "\n"


def mask_string(sensitive_str: str) -> str:
    return "****...**" + sensitive_str[-4:]


MASK_CREDENTIALS_WHITELIST = {
    DB_CREDENTIALS_AUTHENTICATION_METHOD,
    "wiki_base",
    "cloud_name",
    "cloud_id",
}


def mask_credential_dict(credential_dict: dict[str, Any]) -> dict[str, str]:
    masked_creds = {}
    for key, val in credential_dict.items():
        if isinstance(val, str):
            # we want to pass the authentication_method field through so the frontend
            # can disambiguate credentials created by different methods
            if key in MASK_CREDENTIALS_WHITELIST:
                masked_creds[key] = val
            else:
                masked_creds[key] = mask_string(val)
            continue

        if isinstance(val, int):
            masked_creds[key] = "*****"
            continue

        raise ValueError(
            f"Unable to mask credentials of type other than string or int, cannot process request."
            f"Received type: {type(val)}"
        )

    return masked_creds


def make_short_id() -> str:
    """Fast way to generate a random 8 character id ... useful for tagging data
    to trace it through a flow. This is definitely not guaranteed to be unique and is
    targeted at the stated use case."""
    return base64.b32encode(os.urandom(5)).decode("utf-8")[:8]  # 5 bytes → 8 chars


def _validate_pkcs12_content(file_bytes: bytes) -> bool:
    """
    Validate that the file content is actually a PKCS#12 file.

    Args:
        file_bytes: The raw bytes of the uploaded file

    Returns:
        True if the content is a valid PKCS#12 file, False otherwise
    """
    try:
        # Try to load as PKCS#12 with empty password to validate format
        # This will raise an exception if the file is not valid PKCS#12
        pkcs12.load_key_and_certificates(file_bytes, password=None)
        return True
    except Exception:
        # If it fails with empty password, try with some common passwords
        # to distinguish between invalid format vs wrong password
        try:
            pkcs12.load_key_and_certificates(file_bytes, password=b"")
            return True
        except Exception:
            return False


def process_private_key_file(file: UploadFile) -> str:
    """
    Process and validate a private key file upload.

    Validates both the file extension and file content to ensure it's a valid PKCS#12 file.
    Content validation prevents attacks that rely on file extension spoofing.
    """
    # First check file extension (basic filter)
    if not (file.filename and file.filename.endswith(".pfx")):
        raise HTTPException(
            status_code=400, detail="Invalid file type. Only .pfx files are supported."
        )

    # Read file content for validation and processing
    private_key_bytes = file.file.read()

    # Validate file content to prevent extension spoofing attacks
    if not _validate_pkcs12_content(private_key_bytes):
        raise HTTPException(
            status_code=400,
            detail="Invalid file content. The uploaded file does not appear to be a valid PKCS#12 (.pfx) file.",
        )

    # Convert to base64 if validation passes
    pfx_64 = base64.b64encode(private_key_bytes).decode("ascii")
    return pfx_64
