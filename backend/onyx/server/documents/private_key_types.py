import base64
import binascii
from enum import Enum
from typing import Any, Protocol

from fastapi import UploadFile

from onyx.configs.constants import DocumentSource
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


# The credential key that holds each source's .pfx certificate, as base64.
PKCS12_CREDENTIAL_KEYS: dict[DocumentSource, str] = {
    DocumentSource.SHAREPOINT: "sp_private_key",
    DocumentSource.ONEDRIVE: "onedrive_private_key",
    DocumentSource.TEAMS: "teams_private_key",
    DocumentSource.OUTLOOK: "outlook_private_key",
}


def validate_pkcs12_credential_value(
    source: DocumentSource, credential_json: dict[str, Any]
) -> None:
    """A new account typed into a connector form carries its .pfx
    certificate as base64 text, the form the private-key upload stores it in.
    Checks it as that upload checks the file.

    Raises:
        ValueError: the value is not base64, or not a PKCS#12 (.pfx) file.
    """
    key = PKCS12_CREDENTIAL_KEYS.get(source)
    if key is None:
        return
    value = credential_json.get(key)
    if value is None or value == "":
        return
    if not isinstance(value, str):
        raise ValueError(f"{key} must be the .pfx file's base64 content.")
    try:
        private_key_bytes = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError(f"{key} is not valid base64.") from e
    if not validate_pkcs12_content(private_key_bytes):
        raise ValueError(f"{key} is not a valid PKCS#12 (.pfx) file.")
