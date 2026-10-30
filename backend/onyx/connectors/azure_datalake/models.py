from datetime import datetime
from enum import Enum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel

from onyx.connectors.microsoft_credential import ACCOUNT_KEY_AUTHENTICATION_METHOD
from onyx.connectors.models import ConnectorCheckpoint
from onyx.utils.logger import setup_logger

logger = setup_logger()


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

    @field_validator("adls_account_name", mode="before")
    @classmethod
    def _strip_account_name(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def _account_key_is_set(self) -> "AzureDataLakeCredentials":
        if (
            self.authentication_method is AzureDataLakeAuthMethod.ACCOUNT_KEY
            and not self.adls_account_key
        ):
            raise ValueError("The account key is missing.")
        return self


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


class AzureDataLakeCheckpoint(ConnectorCheckpoint):
    # The listing cursor of the next page. None before the first page.
    continuation_token: str | None = None


class AzureDataLakeAccessControl(BaseModel):
    """A path's POSIX access control, with principals as Entra object ids."""

    # "$superuser" when no principal owns the path.
    owner: str
    group: str
    # The short form, e.g. "rwxr-x---+".
    permissions: str
    # Comma-separated entries, e.g. "user::rwx,group:<id>:r-x,mask::r-x".
    acl: str


class AzureDataLakeContainerAccess(BaseModel):
    # True when the container's anonymous access level is blob or container.
    anonymous_read: bool


class ArmModel(BaseModel):
    """Azure Resource Manager JSON: camelCase keys, a resource's fields under
    ``properties``, and null for an absent value. A missing required field
    raises."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _flatten_properties(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        properties: Any = data.get("properties")
        merged: dict[str, Any] = (
            {**properties, **data} if isinstance(properties, dict) else data
        )
        return {key: value for key, value in merged.items() if value is not None}


class AzureSubscription(ArmModel):
    subscription_id: str


class AzureSubscriptionPage(ArmModel):
    subscriptions: list[AzureSubscription] = Field(default_factory=list, alias="value")
    next_link: str | None = None


class AzureStorageAccountResource(ArmModel):
    """A storage account as Azure Resource Manager describes it."""

    # The ARM resource id, "/subscriptions/<id>/resourceGroups/<name>/...".
    id: str
    name: str
    # None when the account does not say, which Azure reads as allowed.
    allow_blob_public_access: bool | None = None


class AzureStorageAccountPage(ArmModel):
    accounts: list[AzureStorageAccountResource] = Field(
        default_factory=list, alias="value"
    )
    next_link: str | None = None


class AzurePrincipalType(str, Enum):
    USER = "User"
    GROUP = "Group"
    SERVICE_PRINCIPAL = "ServicePrincipal"
    FOREIGN_GROUP = "ForeignGroup"
    DEVICE = "Device"
    # A deny assignment that applies to every principal.
    SYSTEM_DEFINED = "SystemDefined"
    EVERYONE = "Everyone"


def _known_principal_type(value: Any) -> Any:
    if value is None or isinstance(value, AzurePrincipalType):
        return value
    try:
        return AzurePrincipalType(value)
    except ValueError:
        logger.debug("Unknown Azure principal type %s", value)
        return None


# None when ARM names no type, or one Onyx does not know.
PrincipalType = Annotated[
    AzurePrincipalType | None, BeforeValidator(_known_principal_type)
]


class AzureRoleAssignment(ArmModel):
    id: str
    principal_id: str
    principal_type: PrincipalType = None
    role_definition_id: str
    # An ABAC condition. Onyx cannot evaluate it.
    condition: str | None = None


class AzureRolePermission(ArmModel):
    data_actions: list[str] = Field(default_factory=list)
    not_data_actions: list[str] = Field(default_factory=list)


class AzureRoleDefinition(ArmModel):
    id: str
    permissions: list[AzureRolePermission] = Field(default_factory=list)


class AzurePrincipal(ArmModel):
    id: str
    type: PrincipalType = None


class AzureDenyAssignment(ArmModel):
    id: str
    scope: str
    permissions: list[AzureRolePermission] = Field(default_factory=list)
    principals: list[AzurePrincipal] = Field(default_factory=list)
    exclude_principals: list[AzurePrincipal] = Field(default_factory=list)
    do_not_apply_to_child_scopes: bool = False
