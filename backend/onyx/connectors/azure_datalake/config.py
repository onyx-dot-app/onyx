import re
from typing import Annotated, Any

from pydantic import field_validator

from onyx.connectors.azure_datalake.models import (
    ACCOUNT_NAME_KEY,
    AUTHENTICATION_METHOD_KEY,
    AzureDataLakeAuthMethod,
)
from onyx.connectors.connector_config import (
    ConnectorConfig,
    CredentialBinding,
    field_format_error,
)
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeOpaque

# https://learn.microsoft.com/en-us/azure/azure-resource-manager/management/resource-name-rules#microsoftstorage
_ACCOUNT_NAME_PATTERN = re.compile(r"[a-z0-9]{3,24}")
_CONTAINER_NAME_PATTERN = re.compile(r"[a-z0-9](?!.*--)[a-z0-9-]{1,61}[a-z0-9]")


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class AzureDataLakeCredentialBinding(CredentialBinding):
    # The account name becomes the request host, so it is validated strictly.
    account_name: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]

    @field_validator("account_name", mode="before")
    @classmethod
    def _strip_account_name(cls, value: Any) -> Any:
        return _strip(value)

    @field_validator("account_name")
    @classmethod
    def _valid_account_name(cls, value: str) -> str:
        if not _ACCOUNT_NAME_PATTERN.fullmatch(value):
            raise field_format_error(
                "Enter the storage account name: 3 to 24 lowercase letters and digits."
            )
        return value

    def validate_credential(self, credential_json: dict[str, Any]) -> None:
        """An account key opens only the account it belongs to."""
        if (
            credential_json.get(AUTHENTICATION_METHOD_KEY)
            != AzureDataLakeAuthMethod.ACCOUNT_KEY
        ):
            return
        key_account: str = str(credential_json.get(ACCOUNT_NAME_KEY) or "").strip()
        if key_account != self.account_name:
            raise ConnectorValidationError(
                f"This account key belongs to the storage account '{key_account}', "
                f"not '{self.account_name}'."
            )


class AzureDataLakeConnectorConfig(AzureDataLakeCredentialBinding, ConnectorConfig):
    # Document ids contain the container name.
    container_name: Annotated[str, FieldPolicy(FieldClass.IDENTITY)]
    # A path prefix, not a list: a longer prefix narrows and a shorter one widens.
    path_prefix: Annotated[str, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())] = ""

    @field_validator("container_name", mode="before")
    @classmethod
    def _strip_container_name(cls, value: Any) -> Any:
        return _strip(value)

    @field_validator("container_name")
    @classmethod
    def _valid_container_name(cls, value: str) -> str:
        if not _CONTAINER_NAME_PATTERN.fullmatch(value):
            raise field_format_error(
                "Enter the container name: 3 to 63 lowercase letters, digits and "
                "single hyphens."
            )
        return value

    # Listing paths have no leading or trailing slash.
    @field_validator("path_prefix", mode="before")
    @classmethod
    def _strip_slashes(cls, value: Any) -> Any:
        return value.strip().strip("/") if isinstance(value, str) else value
