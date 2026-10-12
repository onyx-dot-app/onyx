import base64
from enum import Enum
from typing import Protocol

from fastapi import UploadFile

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.documents.document_utils import validate_pkcs12_content


class ProcessPrivateKeyFileProtocol(Protocol):
    def __call__(self, file: UploadFile) -> str:
        """Validate a PKCS12 upload and return its base64 content."""
        ...


class PrivateKeyFileTypes(Enum):
    SHAREPOINT_PFX_FILE = "sharepoint_pfx_file"
    ONEDRIVE_PFX_FILE = "onedrive_pfx_file"


def process_pkcs12_private_key_file(file: UploadFile) -> str:
    """Validate a PKCS12 private key upload and return its base64 content."""
    if not (file.filename and file.filename.lower().endswith(".pfx")):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Invalid file type. Only .pfx files are supported.",
        )

    private_key_bytes = file.file.read()

    if not validate_pkcs12_content(private_key_bytes):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Invalid file content. The uploaded file is not a valid PKCS#12 (.pfx) file.",
        )

    return base64.b64encode(private_key_bytes).decode("ascii")


FILE_TYPE_TO_FILE_PROCESSOR: dict[
    PrivateKeyFileTypes, ProcessPrivateKeyFileProtocol
] = {
    PrivateKeyFileTypes.SHAREPOINT_PFX_FILE: process_pkcs12_private_key_file,
    PrivateKeyFileTypes.ONEDRIVE_PFX_FILE: process_pkcs12_private_key_file,
}
