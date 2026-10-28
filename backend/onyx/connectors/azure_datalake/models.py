from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from onyx.connectors.microsoft_credential import ACCOUNT_KEY_AUTHENTICATION_METHOD
from onyx.connectors.microsoft_utils.models import MicrosoftTokenInfo
from onyx.connectors.models import ConnectorCheckpoint

AUTHENTICATION_METHOD_KEY = "authentication_method"
ACCOUNT_NAME_KEY = "adls_account_name"


class AzureDataLakeAuthMethod(str, Enum):
    CLIENT_SECRET = "client_secret"
    CERTIFICATE = "certificate"
    ACCOUNT_KEY = ACCOUNT_KEY_AUTHENTICATION_METHOD


class AzureDataLakeCredentials(BaseModel):
    """The credential in the Azure Data Lake shape. An app registration keeps
    the Microsoft family fields under the ``adls_`` prefix; an account key
    names its storage account."""

    model_config = ConfigDict(extra="ignore", hide_input_in_errors=True)

    authentication_method: AzureDataLakeAuthMethod = (
        AzureDataLakeAuthMethod.CLIENT_SECRET
    )
    adls_client_id: str | None = None
    adls_directory_id: str | None = None
    adls_client_secret: str | None = None
    adls_private_key: str | None = None
    adls_certificate_password: str | None = None
    adls_account_name: str | None = None
    adls_account_key: str | None = None

    # A Microsoft family credential made before certificates has no method.
    @field_validator("authentication_method", mode="before")
    @classmethod
    def _missing_means_client_secret(cls, value: Any) -> Any:
        return value or AzureDataLakeAuthMethod.CLIENT_SECRET


class AzureDataLakePath(BaseModel):
    """One entry of a container listing."""

    name: str
    is_directory: bool
    last_modified: datetime
    content_length: int


class AzureDataLakePathPage(BaseModel):
    paths: list[AzureDataLakePath]
    # None after the last page.
    continuation_token: str | None


class AzureDataLakeFile(BaseModel):
    size: int
    last_modified: datetime
    # None when the file is larger than the caller's limit.
    content: bytes | None


class AzureDataLakeSignIn(BaseModel):
    # None for an account key, which signs requests without a token.
    token: MicrosoftTokenInfo | None


class AzureDataLakeCheckpoint(ConnectorCheckpoint):
    # The listing cursor of the next page. None before the first page.
    continuation_token: str | None = None
