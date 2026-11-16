"""One module makes, stores, refreshes and applies every integration
credential.

- ``resolve_connection`` picks the credential a call uses, by the mode of the
  integration. It never falls back from one mode to the other.
- ``render_headers`` puts a credential on a request through the
  ``header_template`` of the integration.
- ``ensure_fresh_connection`` is the one refresh function.
- ``integration_status`` gives the one status for the plugin page, the admin
  page and the agent error.
- The lifecycle helpers disconnect a user and reset connections when an
  admin changes the sign-in settings.
"""

import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import requests
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.oauth_refresher import refresh_oauth_account_sync
from onyx.auth.oauth_token_manager import validate_oauth_endpoint_url
from onyx.cache.interface import CacheLockAcquisitionError
from onyx.cache.locks import cache_shared_lock
from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationKind,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration_connection import (
    delete_connection__no_commit,
    get_connection,
    get_external_app_for_integration,
    get_mcp_server_for_integration,
    get_oauth_client,
    mark_connection_needs_reconnect__no_commit,
    mark_integration_connections_needs_reconnect__no_commit,
    update_connection_secret__no_commit,
)
from onyx.db.models import (
    Integration,
    IntegrationConnection,
    IntegrationOAuthClient,
    OAuthAccount,
    User,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.providers.base import (
    OAuthExternalAppProvider,
    TokenRefreshTerminalError,
    TokenRefreshTransientError,
)
from onyx.external_apps.providers.registry import get_provider_for_app
from onyx.integrations.connection_models import (
    SIGN_IN_EXPIRED_REASON,
    SIGN_IN_SETTINGS_CHANGED_REASON,
    ConnectionProblemCode,
    ConnectionSecret,
    ConnectionState,
    connection_refresh_lock_name,
    expiry_from_expires_in,
    read_connection_secret,
)
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.features.mcp.oauth import (
    IntegrationTokenStorage,
    integration_mcp_server_connection,
    make_integration_oauth_provider,
)
from onyx.server.features.mcp.ssrf import mcp_ssrf_httpx_client_factory
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_async_sync_no_cancel
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

# Refresh this long before expiry so no request leaves with an expired token.
REFRESH_SKEW = timedelta(seconds=120)
# The lock must outlast one token POST plus a few writes.
_TOKEN_REQUEST_TIMEOUT_S = 30.0
_REFRESH_LOCK_WAIT_S = _TOKEN_REQUEST_TIMEOUT_S + 5.0
_REFRESH_LOCK_LEASE_S = 60.0
# Onyx login tokens: refresh inside this window, as the web refresher does.
_LOGIN_REFRESH_WINDOW_S = 300

CREDENTIAL_IMPORT_DONE_KEY = "integration_credential_import_done"

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")
_PERMANENT_REFRESH_STATUSES = frozenset({400, 401})
_TOKEN_KEYS = frozenset(
    {"access_token", "refresh_token", "token_type", "expires_in", "expires_at"}
)


class ResolvedConnection(BaseModel):
    """The credential a call uses. ``secret`` is None for an integration with
    no sign-in."""

    integration_id: int
    connection_id: int | None
    secret: ConnectionSecret | None


class ConnectionProblem(BaseModel):
    code: ConnectionProblemCode
    reason: str


class IntegrationStatus(BaseModel):
    state: ConnectionState
    reason: str | None
    # True while the one-time import of old credentials has not finished.
    moving_credentials: bool


class SignInSettings(BaseModel):
    """The settings whose change resets every connection of an integration.
    A change of only the client secret or a label keeps the connections."""

    auth_method: IntegrationAuthMethod | None
    client_id: str | None
    authorization_url: str | None
    token_url: str | None
    scopes: list[str] | None
    host: str | None


class MissingHeaderValueError(OnyxError):
    def __init__(self, placeholders: list[str]) -> None:
        super().__init__(
            OnyxErrorCode.CREDENTIAL_INVALID,
            "The connection has no value for: " + ", ".join(placeholders),
        )
        self.placeholders = placeholders


class _RefreshPermanentError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _RefreshTemporaryError(Exception):
    pass


class _RefreshedGrant(BaseModel):
    access_token: str
    refresh_token: str | None
    token_type: str | None
    expires_in: float | None
    fields: dict[str, str] = {}


# Import flag


def credential_import_done() -> bool:
    try:
        return bool(get_kv_store().load(CREDENTIAL_IMPORT_DONE_KEY))
    except KvKeyNotFoundError:
        return False


def set_credential_import_done() -> None:
    get_kv_store().store(CREDENTIAL_IMPORT_DONE_KEY, True)


# Messages


def _not_set_up_reason(integration: Integration) -> str:
    return f"{integration.name} is not set up for your organization. Ask your admin."


def _not_connected_reason(integration: Integration) -> str:
    return f"Connect your {integration.name} account to use it."


def _needs_reconnect_reason(
    integration: Integration, connection: IntegrationConnection
) -> str:
    return connection.status_reason or (
        f"Reconnect your {integration.name} account to use it."
    )


# Resolve


def _is_signed_out(user: User | None) -> bool:
    return user is None or user.is_anonymous


def _connection_or_problem(
    integration: Integration,
    connection: IntegrationConnection | None,
    missing: ConnectionProblem,
    db_session: Session,
) -> ResolvedConnection | ConnectionProblem:
    if connection is None:
        return missing
    if connection.status is IntegrationConnectionStatus.CONNECTED:
        connection = ensure_fresh_connection(connection, integration, db_session)
    if connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT:
        return ConnectionProblem(
            code=ConnectionProblemCode.NEEDS_RECONNECT,
            reason=_needs_reconnect_reason(integration, connection),
        )
    return ResolvedConnection(
        integration_id=integration.id,
        connection_id=connection.id,
        secret=read_connection_secret(connection),
    )


def resolve_connection(
    integration: Integration, acting_user: User | None, db_session: Session
) -> ResolvedConnection | ConnectionProblem:
    """The credential for one call by ``acting_user``, or why there is none.
    The caller always gives the acting user: the chat user, the sandbox
    owner, the owner of a scheduled task, or the user a bot resolves."""
    if integration.auth_mode is IntegrationAuthMode.NONE:
        return ResolvedConnection(
            integration_id=integration.id, connection_id=None, secret=None
        )

    if integration.auth_mode is IntegrationAuthMode.SHARED:
        return _connection_or_problem(
            integration,
            get_connection(db_session, integration.id, None),
            ConnectionProblem(
                code=ConnectionProblemCode.NOT_SET_UP,
                reason=_not_set_up_reason(integration),
            ),
            db_session,
        )

    not_connected = ConnectionProblem(
        code=ConnectionProblemCode.NOT_CONNECTED,
        reason=_not_connected_reason(integration),
    )
    if acting_user is None or _is_signed_out(acting_user):
        return not_connected

    if integration.auth_method is IntegrationAuthMethod.ONYX_LOGIN:
        return _resolve_onyx_login(integration, acting_user, db_session)

    return _connection_or_problem(
        integration,
        get_connection(db_session, integration.id, acting_user.id),
        not_connected,
        db_session,
    )


def _live_login_account(user: User) -> OAuthAccount | None:
    if not user.oauth_accounts:
        return None
    return max(user.oauth_accounts, key=lambda link: link.expires_at or 0)


def _login_token_stale(account: OAuthAccount, now: float) -> bool:
    return (
        account.expires_at is not None
        and account.expires_at - now < _LOGIN_REFRESH_WINDOW_S
    )


def _reload_account(db_session: Session, account: OAuthAccount) -> OAuthAccount:
    """The account row in this session, re-read. The user may come from the
    auth session of the request, so its rows can belong to another session."""
    db_account = db_session.get(OAuthAccount, account.id)
    if db_account is None:
        return account
    db_session.refresh(db_account)
    return db_account


def fresh_onyx_login_token(user: User, db_session: Session) -> str | None:
    """The user's Onyx login token, refreshed when it is near expiry. Works
    with no web request. None when the user has no live login token."""
    account = _live_login_account(user)
    if account is None:
        return None
    if not _login_token_stale(account, datetime.now(timezone.utc).timestamp()):
        return account.access_token
    if account.refresh_token:
        try:
            with cache_shared_lock(
                f"onyx_login_refresh:{get_current_tenant_id()}:{user.id}",
                max_time_lock_held_s=_REFRESH_LOCK_LEASE_S,
                wait_for_lock_s=_REFRESH_LOCK_WAIT_S,
                logger=logger,
            ):
                account = _reload_account(db_session, account)
                db_user = db_session.get(User, user.id)
                if (
                    db_user is not None
                    and _login_token_stale(
                        account, datetime.now(timezone.utc).timestamp()
                    )
                    and refresh_oauth_account_sync(db_user, account, db_session)
                ):
                    db_session.commit()
        except CacheLockAcquisitionError:
            account = _reload_account(db_session, account)
    if (
        account.expires_at is not None
        and account.expires_at <= datetime.now(timezone.utc).timestamp()
    ):
        return None
    return account.access_token


def _resolve_onyx_login(
    integration: Integration, user: User, db_session: Session
) -> ResolvedConnection | ConnectionProblem:
    token = fresh_onyx_login_token(user, db_session)
    if token is None:
        return ConnectionProblem(
            code=ConnectionProblemCode.NEEDS_RECONNECT,
            reason=f"Sign in to Onyx again to use {integration.name}.",
        )
    return ResolvedConnection(
        integration_id=integration.id,
        connection_id=None,
        secret=ConnectionSecret(access_token=token, token_type="Bearer"),
    )


# Headers


def _placeholder_values(
    secret: ConnectionSecret, extra_values: Mapping[str, str] | None
) -> dict[str, str]:
    token_values = {
        "access_token": secret.access_token,
        "refresh_token": secret.refresh_token,
        "token_type": secret.token_type,
    }
    return {
        **(extra_values or {}),
        **secret.fields,
        **{key: value for key, value in token_values.items() if value},
    }


def render_headers(
    header_template: Mapping[str, str] | None,
    secret: ConnectionSecret | None,
    *,
    extra_values: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Fill each ``{placeholder}`` of the template from the secret: the
    token values and the typed fields. ``extra_values`` adds values Onyx
    fills itself, such as ``user_email``. A placeholder with no value raises
    ``MissingHeaderValueError``: the call must not go out with a header
    missing."""
    if not header_template:
        return {}
    values = _placeholder_values(secret or ConnectionSecret(), extra_values)
    missing = sorted(
        {
            name
            for template in header_template.values()
            for name in _PLACEHOLDER_RE.findall(template)
            if not values.get(name)
        }
    )
    if missing:
        raise MissingHeaderValueError(missing)
    return {
        name: _PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], template)
        for name, template in header_template.items()
    }


# Refresh


def _needs_refresh(connection: IntegrationConnection, now: datetime) -> bool:
    return (
        connection.expires_at is not None
        and connection.expires_at - now <= REFRESH_SKEW
    )


def ensure_fresh_connection(
    connection: IntegrationConnection,
    integration: Integration,
    db_session: Session,
) -> IntegrationConnection:
    """Refresh the access token of a connection that expires soon. A fast
    no-op for a fresh token or a token with no expiry.

    One lock per connection: concurrent callers make one call to the
    service, and a waiter reads the token the winner stored. A temporary
    error keeps the current token. A permanent error sets Needs reconnect
    with a reason and keeps the row. Returns the connection, re-read."""
    if connection.status is not IntegrationConnectionStatus.CONNECTED:
        return connection
    if not _needs_refresh(connection, datetime.now(timezone.utc)):
        return connection
    try:
        with cache_shared_lock(
            connection_refresh_lock_name(integration.id, connection.user_id),
            max_time_lock_held_s=_REFRESH_LOCK_LEASE_S,
            wait_for_lock_s=_REFRESH_LOCK_WAIT_S,
            logger=logger,
        ):
            # Another caller may have refreshed while this one waited.
            db_session.refresh(connection)
            if (
                connection.status is IntegrationConnectionStatus.CONNECTED
                and _needs_refresh(connection, datetime.now(timezone.utc))
            ):
                _refresh_under_lock(connection, integration, db_session)
    except CacheLockAcquisitionError:
        logger.info(
            "integration_connection.refresh.lock_contended connection_id=%s",
            connection.id,
        )
        db_session.refresh(connection)
    return connection


def _refresh_under_lock(
    connection: IntegrationConnection,
    integration: Integration,
    db_session: Session,
) -> None:
    secret = read_connection_secret(connection)
    if not secret.refresh_token:
        if connection.expires_at is not None and connection.expires_at <= datetime.now(
            timezone.utc
        ):
            mark_connection_needs_reconnect__no_commit(
                db_session, connection, SIGN_IN_EXPIRED_REASON
            )
            db_session.commit()
        return

    try:
        grant = _request_refreshed_grant(integration, connection, secret, db_session)
    except _RefreshTemporaryError as error:
        logger.warning(
            "integration_connection.refresh.temporary connection_id=%s error=%s",
            connection.id,
            error,
        )
        return
    except _RefreshPermanentError as error:
        logger.warning(
            "integration_connection.refresh.permanent connection_id=%s",
            connection.id,
        )
        mark_connection_needs_reconnect__no_commit(db_session, connection, error.reason)
        db_session.commit()
        return

    refreshed = ConnectionSecret(
        access_token=grant.access_token,
        refresh_token=grant.refresh_token or secret.refresh_token,
        token_type=grant.token_type or secret.token_type,
        fields={**secret.fields, **grant.fields},
    )
    update_connection_secret__no_commit(
        db_session,
        connection,
        secret=refreshed.model_dump(mode="json"),
        expires_at=expiry_from_expires_in(grant.expires_in, datetime.now(timezone.utc)),
    )
    db_session.commit()
    logger.info(
        "integration_connection.refresh.succeeded connection_id=%s", connection.id
    )


def _request_refreshed_grant(
    integration: Integration,
    connection: IntegrationConnection,
    secret: ConnectionSecret,
    db_session: Session,
) -> _RefreshedGrant:
    oauth_client = get_oauth_client(db_session, integration.id)
    if oauth_client is None:
        raise _RefreshTemporaryError("the integration has no OAuth client")
    if integration.kind is IntegrationKind.MCP_SERVER:
        return _refresh_with_mcp_sdk(integration, connection, oauth_client, db_session)
    if oauth_client.provider_mode is IntegrationOAuthProviderMode.PRESET:
        return _refresh_with_preset(integration, secret, oauth_client, db_session)
    return _refresh_with_token_url(secret, oauth_client)


def _client_credentials(
    oauth_client: IntegrationOAuthClient,
) -> tuple[str | None, str | None]:
    client_id = (
        oauth_client.client_id.get_value(apply_mask=False)
        if oauth_client.client_id is not None
        else None
    )
    client_secret = (
        oauth_client.client_secret.get_value(apply_mask=False)
        if oauth_client.client_secret is not None
        else None
    )
    return client_id or None, client_secret or None


def _send_token_request(request: httpx.Request, *, mcp: bool) -> httpx.Response:
    """POST to a token endpoint through the SSRF guard of its kind."""
    if mcp:

        async def _send() -> httpx.Response:
            async with mcp_ssrf_httpx_client_factory(
                timeout=httpx.Timeout(_TOKEN_REQUEST_TIMEOUT_S)
            ) as client:
                response = await client.send(request)
                await response.aread()
                return response

        return run_async_sync_no_cancel(_send())
    validate_oauth_endpoint_url(str(request.url))
    with httpx.Client(
        timeout=_TOKEN_REQUEST_TIMEOUT_S, follow_redirects=False
    ) as client:
        return client.send(request)


def _oauth_error_code(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        error = body.get("error")
        return error if isinstance(error, str) else None
    return None


def _grant_from_token_response(request: httpx.Request, mcp: bool) -> _RefreshedGrant:
    try:
        response = _send_token_request(request, mcp=mcp)
    except (httpx.HTTPError, OnyxError, ValueError) as error:
        raise _RefreshTemporaryError(f"token request failed: {error}") from error

    oauth_error = _oauth_error_code(response)
    if response.status_code in _PERMANENT_REFRESH_STATUSES or (
        oauth_error == "invalid_grant"
    ):
        detail = f" ({oauth_error})" if oauth_error else ""
        raise _RefreshPermanentError(
            f"The service refused to renew the sign-in{detail}. Reconnect."
        )
    if response.status_code != 200:
        raise _RefreshTemporaryError(f"token endpoint status {response.status_code}")
    try:
        body = response.json()
    except ValueError as error:
        raise _RefreshTemporaryError("token endpoint returned no JSON") from error
    if not isinstance(body, dict):
        raise _RefreshTemporaryError("token endpoint returned no JSON object")
    access_token = body.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise _RefreshTemporaryError("token response has no access token")
    refresh_token = body.get("refresh_token")
    token_type = body.get("token_type")
    expires_in = body.get("expires_in")
    return _RefreshedGrant(
        access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        token_type=token_type if isinstance(token_type, str) else None,
        expires_in=(
            float(expires_in)
            if isinstance(expires_in, (int, float)) and not isinstance(expires_in, bool)
            else None
        ),
    )


def _refresh_with_token_url(
    secret: ConnectionSecret, oauth_client: IntegrationOAuthClient
) -> _RefreshedGrant:
    if not oauth_client.token_url:
        raise _RefreshTemporaryError("the OAuth client has no token URL")
    client_id, client_secret = _client_credentials(oauth_client)
    data: dict[str, str] = {
        "grant_type": "refresh_token",
        "refresh_token": secret.refresh_token or "",
    }
    if client_id:
        data["client_id"] = client_id
    if client_secret:
        data["client_secret"] = client_secret
    request = httpx.Request(
        "POST",
        oauth_client.token_url,
        data=data,
        headers={"Accept": "application/json"},
    )
    return _grant_from_token_response(request, mcp=False)


def preset_host_values(integration: Integration, db_session: Session) -> dict[str, str]:
    """The account settings a preset needs to build its endpoints, such as
    the Zendesk subdomain. They are host settings of the kind, not secrets."""
    app = get_external_app_for_integration(db_session, integration.id)
    if app is None:
        return {}
    org_credentials = app.organization_credentials.get_value(apply_mask=False)
    return {
        key: value
        for key, value in org_credentials.items()
        if key not in ("client_id", "client_secret") and isinstance(value, str)
    }


def preset_provider_for(
    integration: Integration, db_session: Session
) -> OAuthExternalAppProvider | None:
    app = get_external_app_for_integration(db_session, integration.id)
    if app is None:
        return None
    provider = get_provider_for_app(app)
    return provider if isinstance(provider, OAuthExternalAppProvider) else None


def _refresh_with_preset(
    integration: Integration,
    secret: ConnectionSecret,
    oauth_client: IntegrationOAuthClient,
    db_session: Session,
) -> _RefreshedGrant:
    provider = preset_provider_for(integration, db_session)
    client_id, client_secret = _client_credentials(oauth_client)
    if provider is None or not client_id or not client_secret:
        raise _RefreshTemporaryError("the preset has no provider or client")
    try:
        token_url = provider.resolve_oauth_flow(
            preset_host_values(integration, db_session)
        ).token_url
    except OnyxError as error:
        raise _RefreshTemporaryError("the preset token URL is unknown") from error
    stored: dict[str, Any] = {
        **secret.fields,
        "access_token": secret.access_token,
        "refresh_token": secret.refresh_token,
        "token_type": secret.token_type,
    }
    try:
        refreshed = provider.refresh_credentials(
            stored, client_id, client_secret, token_url=token_url
        )
    except TokenRefreshTransientError as error:
        raise _RefreshTemporaryError(str(error)) from error
    except TokenRefreshTerminalError as error:
        raise _RefreshPermanentError(
            f"The service refused to renew the sign-in ({error}). Reconnect."
        ) from error
    except requests.RequestException as error:
        raise _RefreshTemporaryError(str(error)) from error
    access_token = refreshed.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise _RefreshTemporaryError("the preset refresh gave no access token")
    refresh_token = refreshed.get("refresh_token")
    token_type = refreshed.get("token_type")
    expires_in = refreshed.get("expires_in")
    try:
        expires_in_value = float(expires_in) if expires_in is not None else None
    except (TypeError, ValueError):
        expires_in_value = 0.0
    return _RefreshedGrant(
        access_token=access_token,
        refresh_token=refresh_token if isinstance(refresh_token, str) else None,
        token_type=token_type if isinstance(token_type, str) else None,
        expires_in=expires_in_value,
        fields={
            key: value
            for key, value in refreshed.items()
            if key not in _TOKEN_KEYS and key != "scope" and isinstance(value, str)
        },
    )


def _refresh_with_mcp_sdk(
    integration: Integration,
    connection: IntegrationConnection,
    oauth_client: IntegrationOAuthClient,
    db_session: Session,
) -> _RefreshedGrant:
    mcp_server = get_mcp_server_for_integration(db_session, integration.id)
    if mcp_server is None:
        raise _RefreshTemporaryError("the integration has no MCP server")
    storage = IntegrationTokenStorage(
        integration.id, connection.user_id, cimd_enabled=oauth_client.cimd_enabled
    )
    provider = make_integration_oauth_provider(
        integration_mcp_server_connection(mcp_server, integration, oauth_client),
        storage,
    )
    try:
        request = run_async_sync_no_cancel(provider.build_refresh_request())
    except Exception as error:
        raise _RefreshTemporaryError(f"could not build refresh: {error}") from error
    if request is None:
        raise _RefreshPermanentError(SIGN_IN_EXPIRED_REASON)
    return _grant_from_token_response(request, mcp=True)


# Status


def oauth_client_configured(
    integration: Integration, oauth_client: IntegrationOAuthClient | None
) -> bool:
    """An OAuth integration needs a client id, except with discovery, where
    registration gives one at the first sign-in."""
    if integration.auth_method is not IntegrationAuthMethod.OAUTH2:
        return True
    if oauth_client is None:
        return False
    if oauth_client.provider_mode is IntegrationOAuthProviderMode.DISCOVERY:
        return True
    client_id, _ = _client_credentials(oauth_client)
    return client_id is not None


def _status_of_row(
    integration: Integration,
    connection: IntegrationConnection | None,
    missing: ConnectionState,
    missing_reason: str,
    moving: bool,
) -> IntegrationStatus:
    if connection is None:
        return IntegrationStatus(
            state=missing, reason=missing_reason, moving_credentials=moving
        )
    if connection.status is IntegrationConnectionStatus.NEEDS_RECONNECT:
        return IntegrationStatus(
            state=ConnectionState.NEEDS_RECONNECT,
            reason=_needs_reconnect_reason(integration, connection),
            moving_credentials=moving,
        )
    return IntegrationStatus(
        state=ConnectionState.CONNECTED, reason=None, moving_credentials=moving
    )


def integration_status(
    integration: Integration, user: User | None, db_session: Session
) -> IntegrationStatus:
    """Connected, Not connected, Needs reconnect or Not set up, with the
    reason the user reads. Reads only: it never calls the service."""
    moving = not credential_import_done()
    if integration.auth_mode is IntegrationAuthMode.NONE:
        return IntegrationStatus(
            state=ConnectionState.CONNECTED, reason=None, moving_credentials=moving
        )
    if not oauth_client_configured(
        integration, get_oauth_client(db_session, integration.id)
    ):
        return IntegrationStatus(
            state=ConnectionState.NOT_SET_UP,
            reason=_not_set_up_reason(integration),
            moving_credentials=moving,
        )
    if integration.auth_mode is IntegrationAuthMode.SHARED:
        return _status_of_row(
            integration,
            get_connection(db_session, integration.id, None),
            ConnectionState.NOT_SET_UP,
            _not_set_up_reason(integration),
            moving,
        )
    if user is None or _is_signed_out(user):
        return IntegrationStatus(
            state=ConnectionState.NOT_CONNECTED,
            reason=_not_connected_reason(integration),
            moving_credentials=moving,
        )
    if integration.auth_method is IntegrationAuthMethod.ONYX_LOGIN:
        account = _live_login_account(user)
        if account is None:
            return IntegrationStatus(
                state=ConnectionState.NOT_CONNECTED,
                reason=f"Sign in to Onyx with single sign-on to use {integration.name}.",
                moving_credentials=moving,
            )
        return IntegrationStatus(
            state=ConnectionState.CONNECTED, reason=None, moving_credentials=moving
        )
    return _status_of_row(
        integration,
        get_connection(db_session, integration.id, user.id),
        ConnectionState.NOT_CONNECTED,
        _not_connected_reason(integration),
        moving,
    )


# Lifecycle


def disconnect(integration: Integration, user: User, db_session: Session) -> bool:
    """Delete the user's connection. Returns whether a row went."""
    deleted = delete_connection__no_commit(db_session, integration.id, user.id)
    db_session.commit()
    return deleted


def sign_in_settings_for(
    integration: Integration,
    oauth_client: IntegrationOAuthClient | None,
    host: str | None,
) -> SignInSettings:
    """A snapshot to compare before and after an admin edit. ``host`` is the
    kind's host setting: the MCP server URL or the preset account host."""
    client_id, _ = (
        _client_credentials(oauth_client) if oauth_client is not None else (None, None)
    )
    return SignInSettings(
        auth_method=integration.auth_method,
        client_id=client_id,
        authorization_url=(
            oauth_client.authorization_url if oauth_client is not None else None
        ),
        token_url=oauth_client.token_url if oauth_client is not None else None,
        scopes=(
            sorted(oauth_client.scopes)
            if oauth_client is not None and oauth_client.scopes is not None
            else None
        ),
        host=host,
    )


def sign_in_settings_changed(old: SignInSettings, new: SignInSettings) -> bool:
    return old != new


def mark_sign_in_settings_changed(integration_id: int, db_session: Session) -> int:
    """Set every connection of the integration to Needs reconnect. Does not
    commit: the caller commits with the settings change."""
    return mark_integration_connections_needs_reconnect__no_commit(
        db_session, integration_id, SIGN_IN_SETTINGS_CHANGED_REASON
    )
