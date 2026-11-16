"""The one-time import of old credentials into the integration tables.

For each tenant it reads each old secret with the old models and writes it
in the new form:

- MCP: the admin connection config gives the OAuth client, the organization
  connection and the header template; the user configs (keyed by email) give
  user connections, only when the email is the email of exactly one active
  user.
- OpenAPI tools: ``oauth_config`` gives the OAuth client, ``oauth_user_token``
  gives user connections, and the plain ``custom_headers`` become an
  encrypted organization connection.
- External apps: ``organization_credentials`` gives the OAuth client of a
  preset or the organization connection of a custom app, and
  ``external_app_user_credential`` gives user connections. It also sets the
  final sign-in mode of a custom app.

A row that exists is skipped, so a second run changes nothing. A dead token
is imported as Needs reconnect.
"""

import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from mcp.shared.auth import OAuthClientInformationFull
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheLockAcquisitionError
from onyx.cache.locks import cache_shared_lock
from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
)
from onyx.db.integration_connection import (
    fetch_integration,
    get_active_user_ids,
    get_oauth_client,
    get_oauth_config_by_id,
    get_single_active_user_id_by_email,
    insert_connection_if_absent__no_commit,
    list_external_app_user_credentials,
    list_external_apps_with_integration,
    list_mcp_servers_with_integration,
    list_mcp_user_connection_configs,
    list_oauth_user_tokens,
    list_openapi_tools_with_integration,
)
from onyx.db.models import ExternalApp, Integration, MCPServer, Tool
from onyx.integrations.connection_models import (
    SIGN_IN_EXPIRED_REASON,
    SIGN_IN_REJECTED_REASON,
    ConnectionSecret,
)
from onyx.integrations.connections import (
    credential_import_done,
    set_credential_import_done,
)
from onyx.integrations.oauth import preset_credentials_to_secret
from onyx.server.features.mcp.credentials import (
    extract_connection_data,
    get_mcp_auth_template,
)
from onyx.server.features.mcp.models import MCPConnectionData, MCPOAuthKeys
from onyx.server.features.mcp.oauth import (
    INTEGRATION_CLIENT_INFO_KEY,
    INTEGRATION_OAUTH_METADATA_KEY,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")
_BEARER_ACCESS_TOKEN = "Bearer {access_token}"
_IMPORT_LOCK_LEASE_S = 15 * 60.0


class CredentialImportReport(BaseModel):
    inserted: int = 0
    skipped_existing: int = 0
    skipped_users: int = 0


class _Importer:
    def __init__(self, db_session: Session) -> None:
        self.db_session = db_session
        self.report = CredentialImportReport()

    def insert(
        self,
        integration: Integration,
        user_id: UUID | None,
        secret: ConnectionSecret,
        *,
        expires_at: datetime | None = None,
        granted_scopes: list[str] | None = None,
        dead_reason: str | None = None,
    ) -> None:
        inserted = insert_connection_if_absent__no_commit(
            self.db_session,
            integration_id=integration.id,
            user_id=user_id,
            secret=secret.model_dump(mode="json"),
            expires_at=expires_at,
            granted_scopes=granted_scopes,
            status=(
                IntegrationConnectionStatus.NEEDS_RECONNECT
                if dead_reason
                else IntegrationConnectionStatus.CONNECTED
            ),
            status_reason=dead_reason,
        )
        if inserted:
            self.report.inserted += 1
        else:
            self.report.skipped_existing += 1

    def fill_oauth_client(
        self,
        integration: Integration,
        *,
        client_id: str | None,
        client_secret: str | None,
        registration: dict[str, Any] | None = None,
    ) -> None:
        """Fill only the empty values: an admin edit after the upgrade wins."""
        oauth_client = get_oauth_client(
            self.db_session, integration.id, for_update=True
        )
        if oauth_client is None:
            return
        if oauth_client.client_id is None and client_id:
            oauth_client.client_id = client_id  # ty: ignore[invalid-assignment]
            if client_secret:
                oauth_client.client_secret = client_secret  # ty: ignore[invalid-assignment]
        if oauth_client.registration is None and registration:
            oauth_client.registration = registration  # ty: ignore[invalid-assignment]
        self.db_session.flush()

    def set_header_template(
        self, integration: Integration, template: Mapping[str, str]
    ) -> None:
        if integration.header_template is None and template:
            integration.header_template = dict(template)
            self.db_session.flush()

    def active_user_ids(self, user_ids: list[UUID]) -> set[UUID]:
        active = get_active_user_ids(self.db_session, user_ids)
        self.report.skipped_users += len(set(user_ids) - active)
        return active


def _dead_reason(expires_at: datetime | None, refresh_token: str | None) -> str | None:
    if (
        expires_at is not None
        and expires_at <= datetime.now(timezone.utc)
        and not refresh_token
    ):
        return SIGN_IN_EXPIRED_REASON
    return None


def _str_values(values: Mapping[str, Any]) -> dict[str, str]:
    return {
        key: value for key, value in values.items() if isinstance(value, str) and value
    }


def _placeholders(template: Mapping[str, str]) -> set[str]:
    return {
        name for value in template.values() for name in _PLACEHOLDER_RE.findall(value)
    }


# MCP


def _mcp_fields(data: MCPConnectionData) -> dict[str, str]:
    fields = _str_values(data.get("header_substitutions", {}))
    if api_token := data.get("api_token"):
        fields["api_key"] = api_token
    return fields


def _mcp_oauth_secret(
    data: MCPConnectionData,
) -> tuple[ConnectionSecret, datetime | None, list[str] | None] | None:
    tokens = data.get(MCPOAuthKeys.TOKENS.value) or {}
    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return None
    expires_raw = data.get(MCPOAuthKeys.TOKEN_EXPIRES_AT.value)
    expires_at = (
        datetime.fromtimestamp(float(expires_raw), tz=timezone.utc)
        if expires_raw is not None
        else None
    )
    refresh_token = tokens.get("refresh_token")
    scope = tokens.get("scope")
    return (
        ConnectionSecret(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            token_type="Bearer",
            fields=_mcp_fields(data),
        ),
        expires_at,
        scope.split() if isinstance(scope, str) and scope else None,
    )


def _import_mcp_oauth_row(
    importer: _Importer,
    integration: Integration,
    user_id: UUID | None,
    data: MCPConnectionData,
) -> None:
    parsed = _mcp_oauth_secret(data)
    if parsed is None:
        return
    secret, expires_at, scopes = parsed
    dead_reason = (
        SIGN_IN_REJECTED_REASON
        if data.get("reauth_required")
        else _dead_reason(expires_at, secret.refresh_token)
    )
    importer.insert(
        integration,
        user_id,
        secret,
        expires_at=expires_at,
        granted_scopes=scopes,
        dead_reason=dead_reason,
    )


def _import_mcp_fields_row(
    importer: _Importer,
    integration: Integration,
    user_id: UUID | None,
    fields: dict[str, str],
    reauth_required: bool,
) -> None:
    if not fields:
        return
    importer.insert(
        integration,
        user_id,
        ConnectionSecret(fields=fields),
        dead_reason=SIGN_IN_REJECTED_REASON if reauth_required else None,
    )


def _mcp_client_registration(
    datas: list[MCPConnectionData],
) -> tuple[OAuthClientInformationFull | None, dict[str, Any] | None]:
    client_info: OAuthClientInformationFull | None = None
    registration: dict[str, Any] = {}
    for data in datas:
        client_raw = data.get(MCPOAuthKeys.CLIENT_INFO.value)
        if client_info is None and client_raw:
            try:
                client_info = OAuthClientInformationFull.model_validate(client_raw)
            except ValidationError:
                continue
            registration[INTEGRATION_CLIENT_INFO_KEY] = client_info.model_dump(
                mode="json"
            )
        metadata_raw = data.get(MCPOAuthKeys.METADATA.value)
        if INTEGRATION_OAUTH_METADATA_KEY not in registration and metadata_raw:
            registration[INTEGRATION_OAUTH_METADATA_KEY] = metadata_raw
    return client_info, registration or None


def _import_mcp_server(
    importer: _Importer, mcp_server: MCPServer, integration: Integration
) -> None:
    db_session = importer.db_session
    admin_data = (
        extract_connection_data(mcp_server.admin_connection_config)
        if mcp_server.admin_connection_config is not None
        else MCPConnectionData(headers={})
    )
    auth_template = get_mcp_auth_template(mcp_server)
    template_headers = dict(auth_template.headers) if auth_template else {}
    # OAuth and the Onyx login generate the Authorization header.
    token_headers = {
        name: value
        for name, value in template_headers.items()
        if name.lower() != "authorization"
    }
    token_headers["Authorization"] = _BEARER_ACCESS_TOKEN
    required_fields = auth_template.required_fields if auth_template else []
    auth_type = mcp_server.auth_type
    per_user = mcp_server.auth_performer is MCPAuthenticationPerformer.PER_USER

    user_rows: list[tuple[UUID, MCPConnectionData]] = []
    for config in list_mcp_user_connection_configs(db_session, mcp_server.id):
        user_id = get_single_active_user_id_by_email(db_session, config.user_email)
        if user_id is None:
            importer.report.skipped_users += 1
            continue
        user_rows.append((user_id, extract_connection_data(config)))

    if auth_type is MCPAuthenticationType.OAUTH:
        importer.set_header_template(integration, token_headers)
        client_info, registration = _mcp_client_registration(
            [admin_data, *[data for _, data in user_rows]]
        )
        if client_info is not None:
            importer.fill_oauth_client(
                integration,
                client_id=client_info.client_id,
                client_secret=client_info.client_secret,
                registration=registration,
            )
        if per_user:
            for user_id, data in user_rows:
                _import_mcp_oauth_row(importer, integration, user_id, data)
        else:
            _import_mcp_oauth_row(importer, integration, None, admin_data)
        return

    if auth_type is MCPAuthenticationType.PT_OAUTH:
        importer.set_header_template(integration, token_headers)
        return

    if auth_type is MCPAuthenticationType.API_TOKEN:
        if template_headers:
            importer.set_header_template(integration, template_headers)
            admin_fields = _mcp_fields(admin_data)
        else:
            # Old admin rows with rendered headers and no template.
            plain_headers = _str_values(admin_data.get("headers", {}))
            importer.set_header_template(
                integration, {name: "{" + name + "}" for name in plain_headers}
            )
            admin_fields = plain_headers
        if per_user:
            for user_id, data in user_rows:
                _import_mcp_fields_row(
                    importer,
                    integration,
                    user_id,
                    _mcp_fields(data),
                    bool(data.get("reauth_required")),
                )
        else:
            _import_mcp_fields_row(
                importer,
                integration,
                None,
                admin_fields,
                bool(admin_data.get("reauth_required")),
            )
        return

    # No sign-in: a template with fields the user types becomes individual
    # api_key, since resolve never fills fields in mode none.
    importer.set_header_template(integration, template_headers)
    if required_fields and integration.auth_mode is IntegrationAuthMode.NONE:
        integration.auth_mode = IntegrationAuthMode.INDIVIDUAL
        integration.auth_method = IntegrationAuthMethod.API_KEY
        db_session.flush()
    if integration.auth_mode is IntegrationAuthMode.INDIVIDUAL:
        for user_id, data in user_rows:
            _import_mcp_fields_row(
                importer,
                integration,
                user_id,
                _mcp_fields(data),
                bool(data.get("reauth_required")),
            )


# OpenAPI tools


def _custom_header_values(tool: Tool) -> dict[str, str]:
    return {
        header["key"]: header["value"]
        for header in tool.custom_headers or []
        if header.get("key") and header.get("value")
    }


def _import_openapi_tool(
    importer: _Importer, tool: Tool, integration: Integration
) -> None:
    db_session = importer.db_session
    custom_headers = _custom_header_values(tool)

    if integration.auth_mode is IntegrationAuthMode.SHARED and custom_headers:
        # The plain headers become an encrypted organization connection.
        importer.set_header_template(
            integration, {name: "{" + name + "}" for name in custom_headers}
        )
        importer.insert(integration, None, ConnectionSecret(fields=custom_headers))
        return

    if tool.oauth_config_id is None and not tool.passthrough_auth:
        return
    # With a user token, the static headers stay on the template as before.
    importer.set_header_template(
        integration, {**custom_headers, "Authorization": _BEARER_ACCESS_TOKEN}
    )
    if tool.oauth_config_id is None:
        return
    oauth_config = get_oauth_config_by_id(db_session, tool.oauth_config_id)
    if oauth_config is None:
        return
    importer.fill_oauth_client(
        integration,
        client_id=(
            oauth_config.client_id.get_value(apply_mask=False)
            if oauth_config.client_id is not None
            else None
        ),
        client_secret=(
            oauth_config.client_secret.get_value(apply_mask=False)
            if oauth_config.client_secret is not None
            else None
        ),
    )
    tokens = list_oauth_user_tokens(db_session, oauth_config.id)
    active = importer.active_user_ids([token.user_id for token in tokens])
    for token in tokens:
        if token.user_id not in active or token.token_data is None:
            continue
        token_data = token.token_data.get_value(apply_mask=False)
        access_token = token_data.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            continue
        refresh_token = token_data.get("refresh_token")
        token_type = token_data.get("token_type")
        expires_raw = token_data.get("expires_at")
        expires_at = (
            datetime.fromtimestamp(expires_raw, tz=timezone.utc)
            if isinstance(expires_raw, (int, float))
            else None
        )
        scope = token_data.get("scope")
        secret = ConnectionSecret(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            token_type=token_type if isinstance(token_type, str) else None,
        )
        importer.insert(
            integration,
            token.user_id,
            secret,
            expires_at=expires_at,
            granted_scopes=scope.split() if isinstance(scope, str) and scope else None,
            dead_reason=_dead_reason(expires_at, secret.refresh_token),
        )


# External apps


def _import_external_app(
    importer: _Importer, app: ExternalApp, integration: Integration
) -> None:
    db_session = importer.db_session
    org_values = _str_values(app.organization_credentials.get_value(apply_mask=False))
    user_credentials = list_external_app_user_credentials(db_session, app.id)
    active = importer.active_user_ids([row.user_id for row in user_credentials])

    if app.app_type.is_built_in:
        importer.fill_oauth_client(
            integration,
            client_id=org_values.get("client_id"),
            client_secret=org_values.get("client_secret"),
        )
        importer.set_header_template(integration, _str_values(app.auth_template))
        for row in user_credentials:
            if row.user_id not in active:
                continue
            secret, expires_at = preset_credentials_to_secret(
                row.user_credentials.get_value(apply_mask=False)
            )
            if not secret.access_token:
                continue
            importer.insert(
                integration,
                row.user_id,
                secret,
                expires_at=expires_at,
                granted_scopes=row.granted_scopes,
                dead_reason=_dead_reason(expires_at, secret.refresh_token),
            )
        return

    template = _str_values(app.auth_template)
    if not template:
        return
    importer.set_header_template(integration, template)
    # The final mode: shared when the organization values fill the template,
    # else each user types the rest.
    if _placeholders(template) <= set(org_values):
        integration.auth_mode = IntegrationAuthMode.SHARED
        integration.auth_method = IntegrationAuthMethod.API_KEY
        db_session.flush()
        importer.insert(integration, None, ConnectionSecret(fields=org_values))
        return
    integration.auth_mode = IntegrationAuthMode.INDIVIDUAL
    integration.auth_method = IntegrationAuthMethod.API_KEY
    db_session.flush()
    for row in user_credentials:
        if row.user_id not in active:
            continue
        # As the old merge did: the user's values win over the organization's.
        fields = {
            **org_values,
            **_str_values(row.user_credentials.get_value(apply_mask=False)),
        }
        importer.insert(integration, row.user_id, ConnectionSecret(fields=fields))


def import_legacy_credentials(db_session: Session) -> CredentialImportReport:
    """Copy every old credential of the current tenant into the integration
    tables and commit. Safe to run again: it skips rows that exist."""
    importer = _Importer(db_session)

    for mcp_server in list_mcp_servers_with_integration(db_session):
        integration = (
            fetch_integration(db_session, mcp_server.integration_id)
            if mcp_server.integration_id is not None
            else None
        )
        if integration is not None:
            _import_mcp_server(importer, mcp_server, integration)

    for tool in list_openapi_tools_with_integration(db_session):
        integration = (
            fetch_integration(db_session, tool.integration_id)
            if tool.integration_id is not None
            else None
        )
        if integration is not None:
            _import_openapi_tool(importer, tool, integration)

    for app in list_external_apps_with_integration(db_session):
        integration = (
            fetch_integration(db_session, app.integration_id)
            if app.integration_id is not None
            else None
        )
        if integration is not None:
            _import_external_app(importer, app, integration)

    db_session.commit()
    return importer.report


def run_credential_import_if_needed(db_session: Session) -> bool:
    """Run the import once for the current tenant and set the done flag.
    A cheap no-op once the flag is set. Returns whether it ran."""
    if credential_import_done():
        return False
    try:
        with cache_shared_lock(
            f"integration_credential_import:{get_current_tenant_id()}",
            max_time_lock_held_s=_IMPORT_LOCK_LEASE_S,
            wait_for_lock_s=0.0,
            logger=logger,
        ):
            if credential_import_done():
                return False
            report = import_legacy_credentials(db_session)
            set_credential_import_done()
    except CacheLockAcquisitionError:
        return False
    logger.info(
        "integration_credential_import.done inserted=%s skipped_existing=%s "
        "skipped_users=%s",
        report.inserted,
        report.skipped_existing,
        report.skipped_users,
    )
    return True
