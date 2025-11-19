import base64
from enum import Enum
from typing import Protocol

from fastapi import HTTPException
from fastapi import UploadFile

from onyx.server.documents.document_utils import validate_pkcs12_content


class ProcessPrivateKeyFileProtocol(Protocol):
    def __call__(self, file: UploadFile) -> str:
        """
        Accepts a file-like object, validates the file (e.g., checks extension and content),
        and returns its contents as a base64-encoded string if valid.
        Raises an exception if validation fails.
        """
        ...


class PrivateKeyFileTypes(Enum):
    SHAREPOINT_PFX_FILE = "sharepoint_pfx_file"


def process_sharepoint_private_key_file(file: UploadFile) -> str:
    """
    Process and validate a private key file upload.

    Validates both the file extension and file content to ensure it's a valid PKCS#12 file.
    Content validation prevents attacks that rely on file extension spoofing.
    """
    # First check file extension (basic filter)
    if not (file.filename and file.filename.lower().endswith(".pfx")):
        raise HTTPException(
            status_code=400, detail="Invalid file type. Only .pfx files are supported."
        )

    # Read file content for validation and processing
    private_key_bytes = file.file.read()

    # Validate file content to prevent extension spoofing attacks
    if not validate_pkcs12_content(private_key_bytes):
        raise HTTPException(
            status_code=400,
            detail="Invalid file content. The uploaded file does not appear to be a valid PKCS#12 (.pfx) file.",
        )

    # Convert to base64 if validation passes
    pfx_64 = base64.b64encode(private_key_bytes).decode("ascii")
    return pfx_64


FILE_TYPE_TO_FILE_PROCESSOR: dict[
    PrivateKeyFileTypes, ProcessPrivateKeyFileProtocol
] = {
    PrivateKeyFileTypes.SHAREPOINT_PFX_FILE: process_sharepoint_private_key_file,
}
