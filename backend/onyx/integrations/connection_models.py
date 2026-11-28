"""The integration tables migration copied the old secrets as they were and
named their format in ``legacy_format``. The readers here give the same
shapes for the new format and for each old format. Each write saves the new
format and clears ``legacy_format``."""

import datetime
import hashlib
from enum import Enum
from typing import Any
from uuid import UUID

from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
from pydantic import AnyUrl, BaseModel, ConfigDict, Field

from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationConnectionStatus,
    IntegrationLegacyFormat,
    IntegrationOAuthProviderMode,
)
from onyx.db.models import IntegrationConnection, IntegrationOAuthClient
from onyx.oauth.models import (
    OAuthConfigurationFingerprint,
    PKCECodeVerifier,
    SafeOAuthReturnPath,
)
from onyx.server.features.mcp.models import (
    DENYLISTED_MCP_HEADERS,
    MCPOAuthKeys,
    merge_mcp_headers,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Reason texts that a user reads.
SIGN_IN_SETTINGS_CHANGED_REASON = "Your admin changed the sign-in settings"
SIGN_IN_REJECTED_REASON = "The service no longer accepts this sign-in. Reconnect."
SIGN_IN_EXPIRED_REASON = "The sign-in expired and cannot be renewed. Reconnect."

# Keys of integration_oauth_client.registration.
OAUTH_CLIENT_INFO_KEY = "client_info"
OAUTH_METADATA_KEY = "oauth_metadata"

_PRESET_TOKEN_FIELDS = frozenset(
    {"access_token", "refresh_token", "token_type", "expires_in", "expires_at", "scope"}
)
_PRESET_CLIENT_FIELDS = frozenset({"client_id", "client_secret"})


class ConnectionSecret(BaseModel):
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    # api_key values and other typed fields, keyed by placeholder name.
    fields: dict[str, str] = Field(default_factory=dict)
    # Headers that the connection itself sends, in the syntax of
    # header_template. The header_template of the integration wins.
    headers: dict[str, str] = Field(default_factory=dict)


class ConnectionRecord(BaseModel):
    secret: ConnectionSecret
    expires_at: datetime.datetime | None
    granted_scopes: list[str] | None
    status: IntegrationConnectionStatus
    status_reason: str | None


class OAuthClientCredentials(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    # The registration in the new format: OAUTH_CLIENT_INFO_KEY and
    # OAUTH_METADATA_KEY.
    registration: dict[str, Any] = Field(default_factory=dict)
    # Account settings of a preset, such as the Zendesk subdomain.
    host_values: dict[str, str] = Field(default_factory=dict)


class _LegacyConnection(BaseModel):
    secret: ConnectionSecret
    expires_at: datetime.datetime | None = None
    granted_scopes: list[str] | None = None
    rejected: bool = False


def literal_header_value(value: str) -> str:
    """The header_template form of a value that must go out unchanged."""
    return value.replace("{", "{{").replace("}", "}}")


def _str_values(values: object) -> dict[str, str]:
    if not isinstance(values, dict):
        return {}
    return {
        key: value
        for key, value in values.items()
        if isinstance(key, str) and isinstance(value, str) and value
    }


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


def _unix_time(value: object) -> datetime.datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return datetime.datetime.fromtimestamp(float(value), tz=datetime.timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _scopes(value: object) -> list[str] | None:
    return value.split() if isinstance(value, str) and value else None


def _without(headers: dict[str, str], names: set[str]) -> dict[str, str]:
    return {name: value for name, value in headers.items() if name.lower() not in names}


def preset_credentials_to_secret(
    credentials: dict[str, Any],
) -> tuple[ConnectionSecret, datetime.datetime | None]:
    """Map the credential dict of a built-in provider (or the field values
    of a custom app) to the one secret shape and its expiry."""
    expires_at_raw = credentials.get("expires_at")
    expires_at: datetime.datetime | None = None
    if isinstance(expires_at_raw, str):
        try:
            expires_at = datetime.datetime.fromisoformat(expires_at_raw)
        except ValueError:
            expires_at = datetime.datetime.now(datetime.timezone.utc)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)
    return (
        ConnectionSecret(
            access_token=_optional_str(credentials.get("access_token")),
            refresh_token=_optional_str(credentials.get("refresh_token")),
            token_type=_optional_str(credentials.get("token_type")),
            fields={
                key: value
                for key, value in _str_values(credentials).items()
                if key not in _PRESET_TOKEN_FIELDS
            },
        ),
        expires_at,
    )


def _read_mcp_config(data: dict[str, Any]) -> _LegacyConnection:
    """The old ``MCPConnectionData``. The headers are the stored headers
    with the admin template on top, as the old MCP resolver merged them."""
    tokens = _dict(data.get(MCPOAuthKeys.TOKENS.value))
    headers = merge_mcp_headers(
        {
            name: literal_header_value(value)
            for name, value in _str_values(data.get("headers")).items()
        },
        _str_values(data.get("header_template")),
    )
    dropped = set(DENYLISTED_MCP_HEADERS)
    if tokens:
        # The old OAuth writes kept a copy of the token in the headers.
        dropped.add("authorization")
    fields = _str_values(data.get("header_substitutions"))
    if api_token := _optional_str(data.get("api_token")):
        fields["api_key"] = api_token
    return _LegacyConnection(
        secret=ConnectionSecret(
            access_token=_optional_str(tokens.get("access_token")),
            refresh_token=_optional_str(tokens.get("refresh_token")),
            token_type=_optional_str(tokens.get("token_type")),
            fields=fields,
            headers=_without(headers, dropped),
        ),
        expires_at=_unix_time(data.get(MCPOAuthKeys.TOKEN_EXPIRES_AT.value)),
        granted_scopes=_scopes(tokens.get("scope")),
        rejected=bool(data.get("reauth_required")),
    )


def _read_oauth_user_token(data: dict[str, Any]) -> _LegacyConnection:
    return _LegacyConnection(
        secret=ConnectionSecret(
            access_token=_optional_str(data.get("access_token")),
            refresh_token=_optional_str(data.get("refresh_token")),
            token_type=_optional_str(data.get("token_type")),
        ),
        expires_at=_unix_time(data.get("expires_at")),
        granted_scopes=_scopes(data.get("scope")),
    )


def _read_tool_headers(raw: object) -> _LegacyConnection:
    """The plain ``tool.custom_headers`` list of {key, value}."""
    headers: dict[str, str] = {}
    for header in raw if isinstance(raw, list) else []:
        values = _str_values(header)
        if (key := values.get("key")) and (value := values.get("value")):
            headers[key] = literal_header_value(value)
    return _LegacyConnection(secret=ConnectionSecret(headers=headers))


def _read_legacy_connection(
    legacy_format: IntegrationLegacyFormat, raw: object
) -> _LegacyConnection:
    match legacy_format:
        case IntegrationLegacyFormat.MCP_CONFIG:
            return _read_mcp_config(_dict(raw))
        case IntegrationLegacyFormat.OAUTH_USER_TOKEN:
            return _read_oauth_user_token(_dict(raw))
        case IntegrationLegacyFormat.EXTERNAL_APP_USER:
            data = _dict(raw)
            if "access_token" not in data:
                # The field values of a custom app, which can use any name.
                return _LegacyConnection(
                    secret=ConnectionSecret(fields=_str_values(data))
                )
            secret, expires_at = preset_credentials_to_secret(data)
            return _LegacyConnection(secret=secret, expires_at=expires_at)
        case IntegrationLegacyFormat.EXTERNAL_APP_ORG:
            return _LegacyConnection(secret=ConnectionSecret(fields=_str_values(raw)))
        case IntegrationLegacyFormat.TOOL_HEADERS:
            return _read_tool_headers(raw)


def read_connection(connection: IntegrationConnection) -> ConnectionRecord:
    # tool_headers rows hold a JSON list, not a dict.
    raw: Any = connection.secret.get_value(apply_mask=False)
    if connection.legacy_format is None:
        return ConnectionRecord(
            secret=ConnectionSecret.model_validate(raw),
            expires_at=connection.expires_at,
            granted_scopes=connection.granted_scopes,
            status=connection.status,
            status_reason=connection.status_reason,
        )
    legacy = _read_legacy_connection(
        IntegrationLegacyFormat(connection.legacy_format), raw
    )
    status, status_reason = connection.status, connection.status_reason
    if legacy.rejected and status is IntegrationConnectionStatus.CONNECTED:
        status = IntegrationConnectionStatus.NEEDS_RECONNECT
        status_reason = SIGN_IN_REJECTED_REASON
    return ConnectionRecord(
        secret=legacy.secret,
        expires_at=connection.expires_at or legacy.expires_at,
        granted_scopes=connection.granted_scopes or legacy.granted_scopes,
        status=status,
        status_reason=status_reason,
    )


def read_connection_secret(connection: IntegrationConnection) -> ConnectionSecret:
    return read_connection(connection).secret


def secret_fingerprint(secret: ConnectionSecret) -> str:
    return hashlib.sha256(secret.model_dump_json().encode()).hexdigest()


def access_token_fingerprint(access_token: str) -> str:
    return hashlib.sha256(access_token.encode()).hexdigest()


def connection_secret_fingerprint(connection: IntegrationConnection) -> str:
    return secret_fingerprint(read_connection_secret(connection))


def legacy_organization_defaults(
    organization: IntegrationConnection, *, template_in_headers: bool
) -> ConnectionSecret | None:
    """What an old organization row gave the other connections of its
    integration: the header template of an MCP admin config, or the field
    values of a custom app, which a user's values override. None for a row
    in the new format. ``template_in_headers``: an old per-user API key
    server kept its template in the admin headers."""
    if organization.legacy_format is None:
        return None
    try:
        raw: Any = organization.secret.get_value(apply_mask=False)
    except ValueError as error:
        # The migration gave an old row that does not read no template, so
        # the other connections of the integration get no defaults from it.
        logger.warning(
            "Integration %s: the old organization row does not read (%s)",
            organization.integration_id,
            type(error).__name__,
        )
        return None
    match IntegrationLegacyFormat(organization.legacy_format):
        case IntegrationLegacyFormat.MCP_CONFIG:
            data = _dict(raw)
            template = data.get("header_template")
            if template is None and template_in_headers:
                template = data.get("headers")
            return ConnectionSecret(
                headers=_without(_str_values(template), set(DENYLISTED_MCP_HEADERS))
            )
        case IntegrationLegacyFormat.EXTERNAL_APP_ORG:
            return ConnectionSecret(fields=_str_values(raw))
        case _:
            return None


def merge_legacy_defaults(
    secret: ConnectionSecret, defaults: ConnectionSecret
) -> ConnectionSecret:
    """The secret's own values win over the defaults, and the template wins
    over the stored headers. A token sign-in makes its own Authorization."""
    headers = merge_mcp_headers(secret.headers, defaults.headers)
    if secret.access_token:
        headers = _without(headers, {"authorization"})
    return secret.model_copy(
        update={"fields": {**defaults.fields, **secret.fields}, "headers": headers}
    )


def read_oauth_client(oauth_client: IntegrationOAuthClient) -> OAuthClientCredentials:
    registration: Any = (
        oauth_client.registration.get_value(apply_mask=False)
        if oauth_client.registration is not None
        else {}
    )
    if oauth_client.legacy_format is None:
        return OAuthClientCredentials(
            client_id=(
                oauth_client.client_id.get_value(apply_mask=False) or None
                if oauth_client.client_id is not None
                else None
            ),
            client_secret=(
                oauth_client.client_secret.get_value(apply_mask=False) or None
                if oauth_client.client_secret is not None
                else None
            ),
            registration=_dict(registration),
            host_values=(
                _str_values(oauth_client.additional_params)
                if oauth_client.provider_mode is IntegrationOAuthProviderMode.PRESET
                else {}
            ),
        )
    data = _dict(registration)
    match IntegrationLegacyFormat(oauth_client.legacy_format):
        case IntegrationLegacyFormat.MCP_CONFIG:
            client_info = _dict(data.get(MCPOAuthKeys.CLIENT_INFO.value))
            new_registration: dict[str, Any] = {}
            if client_info:
                new_registration[OAUTH_CLIENT_INFO_KEY] = client_info
            if metadata := _dict(data.get(MCPOAuthKeys.METADATA.value)):
                new_registration[OAUTH_METADATA_KEY] = metadata
            return OAuthClientCredentials(
                client_id=_optional_str(client_info.get("client_id"))
                or _optional_str(data.get("client_id")),
                client_secret=_optional_str(client_info.get("client_secret"))
                or _optional_str(data.get("client_secret")),
                registration=new_registration,
            )
        case IntegrationLegacyFormat.EXTERNAL_APP_ORG:
            values = _str_values(data)
            return OAuthClientCredentials(
                client_id=values.get("client_id"),
                client_secret=values.get("client_secret"),
                host_values={
                    key: value
                    for key, value in values.items()
                    if key not in _PRESET_CLIENT_FIELDS
                },
            )
        case _:
            raise ValueError(
                f"Unknown OAuth client format: {oauth_client.legacy_format}"
            )


class ConnectionState(str, Enum):
    CONNECTED = "connected"
    NOT_CONNECTED = "not_connected"
    NEEDS_RECONNECT = "needs_reconnect"
    NOT_SET_UP = "not_set_up"


def expiry_from_expires_in(
    expires_in: int | float | None, now: datetime.datetime
) -> datetime.datetime | None:
    if expires_in is None:
        return None
    return now + datetime.timedelta(seconds=float(expires_in))


def connection_refresh_lock_name(integration_id: int, user_id: UUID | None) -> str:
    """One lock per connection, shared by every refresh path."""
    owner = str(user_id) if user_id is not None else "organization"
    return (
        f"integration_connection_refresh:{get_current_tenant_id()}:"
        f"{integration_id}:{owner}"
    )


class ResolvedConnection(BaseModel):
    integration_id: int
    connection_id: int | None
    secret: ConnectionSecret | None
    # The fingerprint of the stored secret of the connection row.
    secret_fingerprint: str | None = None
    # When the access token expires; None when unknown.
    expires_at: datetime.datetime | None = None


class ConnectionProblem(BaseModel):
    code: ConnectionState
    reason: str


class IntegrationStatus(BaseModel):
    state: ConnectionState
    reason: str | None


class SignInSettings(BaseModel):
    """A change of only the client secret or a label keeps the connections."""

    auth_method: IntegrationAuthMethod | None
    client_id: str | None
    authorization_url: str | None
    token_url: str | None
    scopes: list[str] | None
    host: str | None


class RefreshedGrant(BaseModel):
    secret: ConnectionSecret
    expires_in: float | None


class IntegrationMCPAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    redirect_uri: AnyUrl
    client_information_fingerprint: OAuthConfigurationFingerprint
    protected_resource_metadata: ProtectedResourceMetadata | None = None
    oauth_metadata: OAuthMetadata | None = None
    authorization_server_url: str | None = None
    protocol_version: str | None = None
    scope: str | None = None
    resource: AnyUrl | None = None


class IntegrationOAuthAttemptPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    integration_id: int
    for_organization: bool
    configuration_fingerprint: OAuthConfigurationFingerprint
    code_verifier: PKCECodeVerifier | None = None
    return_path: SafeOAuthReturnPath | None = None
    mcp: IntegrationMCPAttempt | None = None


class IntegrationOAuthCallbackResult(BaseModel):
    integration_id: int
    for_organization: bool
    return_path: str | None
