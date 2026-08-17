from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    ValidationError,
)

AUTHENTICATION_METHOD_FIELD = "authentication_method"

_HTTP_URL_ADAPTER = TypeAdapter(HttpUrl)
_MY_DOMAIN_HOST_SUFFIX = ".my.salesforce.com"
_INSTANCE_HOST_SUFFIX = ".salesforce.com"
_MAX_HOST_LENGTH = 253
_MAX_HOST_LABEL_LENGTH = 63


class SalesforceAuthenticationMethod(StrEnum):
    PASSWORD = "password"
    OAUTH = "oauth"


class SalesforceGrantType(StrEnum):
    AUTHORIZATION_CODE = "authorization_code"
    REFRESH_TOKEN = "refresh_token"


def _valid_host_label(label: str) -> bool:
    return (
        0 < len(label) <= _MAX_HOST_LABEL_LENGTH
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
    )


def _validate_salesforce_url(value: str, host_suffix: str) -> str:
    try:
        parsed = _HTTP_URL_ADAPTER.validate_python(value)
    except ValidationError as error:
        raise ValueError("Salesforce URL is invalid") from error

    if parsed.scheme != "https":
        raise ValueError("Salesforce URL must use HTTPS")
    if "@" in value or parsed.username is not None or parsed.password is not None:
        raise ValueError("Salesforce URL must not contain credentials")
    if parsed.query is not None or parsed.fragment is not None:
        raise ValueError("Salesforce URL must not contain a query or fragment")
    if parsed.path != "/":
        raise ValueError("Salesforce URL must not contain a path")
    if parsed.port != 443:
        raise ValueError("Salesforce URL must use the default HTTPS port")

    hostname = parsed.host
    if not hostname or not hostname.endswith(host_suffix):
        raise ValueError("Salesforce URL has an unsupported host")
    if len(hostname) > _MAX_HOST_LENGTH or any(
        not _valid_host_label(label) for label in hostname.split(".")
    ):
        raise ValueError("Salesforce URL has an invalid host")

    return f"https://{hostname}"


def validate_salesforce_my_domain_url(value: str) -> str:
    return _validate_salesforce_url(value, _MY_DOMAIN_HOST_SUFFIX)


def validate_salesforce_instance_url(value: str) -> str:
    return _validate_salesforce_url(value, _INSTANCE_HOST_SUFFIX)


SalesforceMyDomainUrl = Annotated[
    str, AfterValidator(validate_salesforce_my_domain_url)
]
SalesforceInstanceUrl = Annotated[str, AfterValidator(validate_salesforce_instance_url)]


class SalesforceLegacyCredentials(BaseModel):
    model_config = ConfigDict(extra="ignore")

    authentication_method: Literal[SalesforceAuthenticationMethod.PASSWORD] | None = (
        None
    )
    sf_username: str = Field(min_length=1)
    sf_password: str = Field(min_length=1)
    sf_security_token: str = Field(min_length=1)
    is_sandbox: bool = False


class SalesforceOAuthCredentials(BaseModel):
    model_config = ConfigDict(extra="ignore")

    authentication_method: Literal[SalesforceAuthenticationMethod.OAUTH]
    sf_access_token: str = Field(min_length=1)
    sf_refresh_token: str = Field(min_length=1)
    sf_instance_url: SalesforceInstanceUrl
    sf_login_url: SalesforceMyDomainUrl


SalesforceCredentials = SalesforceLegacyCredentials | SalesforceOAuthCredentials


class SalesforceTokenResponse(BaseModel):
    access_token: str = Field(min_length=1)
    refresh_token: str | None = None
    instance_url: SalesforceInstanceUrl


class SalesforceAuthorizationCodeTokenRequest(BaseModel):
    grant_type: Literal[SalesforceGrantType.AUTHORIZATION_CODE] = (
        SalesforceGrantType.AUTHORIZATION_CODE
    )
    code: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)
    redirect_uri: str = Field(min_length=1)
    code_verifier: str = Field(min_length=1)


class SalesforceRefreshTokenRequest(BaseModel):
    grant_type: Literal[SalesforceGrantType.REFRESH_TOKEN] = (
        SalesforceGrantType.REFRESH_TOKEN
    )
    refresh_token: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    client_secret: str = Field(min_length=1)


class SalesforceSessionCredentials(BaseModel):
    sf_access_token: str = Field(min_length=1)
    sf_instance_host: str = Field(min_length=1)


def parse_salesforce_credentials(credentials: dict[str, Any]) -> SalesforceCredentials:
    authentication_method = credentials.get(AUTHENTICATION_METHOD_FIELD)
    if authentication_method is None:
        return SalesforceLegacyCredentials.model_validate(credentials)
    if authentication_method == SalesforceAuthenticationMethod.PASSWORD:
        return SalesforceLegacyCredentials.model_validate(credentials)
    if authentication_method == SalesforceAuthenticationMethod.OAUTH:
        return SalesforceOAuthCredentials.model_validate(credentials)
    raise ValueError(
        f"Unsupported Salesforce authentication method: {authentication_method}"
    )
