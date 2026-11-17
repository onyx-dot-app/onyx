import re
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import requests
from sqlalchemy.orm import Session

from onyx.auth.oauth_refresher import (
    onyx_login_refresh_lock_name,
    refresh_oauth_account_sync,
)
from onyx.auth.oauth_token_manager import validate_oauth_endpoint_url
from onyx.cache.interface import CacheLockAcquisitionError
from onyx.cache.locks import cache_shared_lock
from onyx.db.enums import (
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationKind,
    IntegrationLegacyFormat,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration import (
    get_external_app_for_integration,
    get_mcp_server_for_integration,
)
from onyx.db.integration_connection import (
    delete_connection__no_commit,
    get_connection,
    get_connection_by_id,
    get_oauth_client,
    mark_connection_needs_reconnect__no_commit,
    mark_integration_connections_needs_reconnect__no_commit,
    reload_connection,
    update_connection_secret__no_commit,
)
from onyx.db.models import (
    Integration,
    IntegrationConnection,
    IntegrationOAuthClient,
    OAuthAccount,
    User,
)
from onyx.db.users import fetch_user_by_id, reload_oauth_account
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
    ConnectionProblem,
    ConnectionRecord,
    ConnectionSecret,
    ConnectionState,
    IntegrationStatus,
    RefreshedGrant,
    ResolvedConnection,
    SignInSettings,
    connection_refresh_lock_name,
    expiry_from_expires_in,
    legacy_organization_defaults,
    merge_legacy_defaults,
    preset_credentials_to_secret,
    read_connection,
    read_connection_secret,
    read_oauth_client,
)
from onyx.server.features.mcp.models import merge_mcp_headers
from onyx.server.features.mcp.oauth import (
    IntegrationTokenStorage,
    integration_mcp_server_connection,
    make_integration_oauth_provider,
)
from onyx.server.features.mcp.ssrf import mcp_ssrf_httpx_client_factory
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import run_async_sync_no_cancel

logger = setup_logger()

# Refresh this long before expiry so no request leaves with an expired token.
REFRESH_SKEW = timedelta(seconds=120)
# The lock must outlast one token POST plus a few writes.
_TOKEN_REQUEST_TIMEOUT_S = 30.0
_REFRESH_LOCK_WAIT_S = _TOKEN_REQUEST_TIMEOUT_S + 5.0
_REFRESH_LOCK_LEASE_S = 60.0
# Onyx login tokens: refresh inside this window, as the web refresher does.
_LOGIN_REFRESH_WINDOW_S = 300

# "{{" and "}}" are literal braces; "{name}" is a placeholder.
_TEMPLATE_TOKEN_RE = re.compile(r"\{\{|\}\}|\{([^{}]+)\}")
_PERMANENT_REFRESH_STATUSES = frozenset({400, 401})


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


def not_set_up_reason(integration: Integration) -> str:
    return f"{integration.name} is not set up for your organization. Ask your admin."


def _not_connected_reason(integration: Integration) -> str:
    return f"Connect your {integration.name} account to use it."


def _needs_reconnect_reason(integration: Integration, record: ConnectionRecord) -> str:
    return record.status_reason or (
        f"Reconnect your {integration.name} account to use it."
    )


def _signed_in(user: User | None) -> User | None:
    return None if user is None or user.is_anonymous else user


def _connection_or_problem(
    integration: Integration,
    connection: IntegrationConnection | None,
    missing: ConnectionProblem,
    db_session: Session,
    refresh: bool,
) -> ResolvedConnection | ConnectionProblem:
    if connection is None:
        return missing
    if refresh:
        connection = ensure_fresh_connection(connection, integration, db_session)
    record = read_connection(connection)
    if record.status is IntegrationConnectionStatus.NEEDS_RECONNECT:
        return ConnectionProblem(
            code=ConnectionState.NEEDS_RECONNECT,
            reason=_needs_reconnect_reason(integration, record),
        )
    if (
        record.expires_at is not None
        and record.expires_at <= datetime.now(timezone.utc)
        and not record.secret.refresh_token
    ):
        return ConnectionProblem(
            code=ConnectionState.NEEDS_RECONNECT, reason=SIGN_IN_EXPIRED_REASON
        )
    return ResolvedConnection(
        integration_id=integration.id,
        connection_id=connection.id,
        secret=record.secret,
    )


def resolve_connection(
    integration: Integration,
    acting_user: User | None,
    db_session: Session,
    *,
    refresh: bool = True,
) -> ResolvedConnection | ConnectionProblem:
    """The credential for one call by ``acting_user``, or why there is none.
    The caller always gives the acting user: the chat user, the sandbox
    owner, the owner of a scheduled task, or the user a bot resolves. With
    ``refresh=False`` it only reads and never calls the service."""
    return _with_legacy_defaults(
        integration,
        acting_user,
        _resolve_by_mode(integration, acting_user, db_session, refresh),
        db_session,
    )


def _may_have_legacy_defaults(integration: Integration) -> bool:
    """An MCP server, or a custom app with a per-user API key, that the
    migration copied with an old organization row."""
    if integration.auth_mode is IntegrationAuthMode.SHARED:
        return False
    if integration.kind is IntegrationKind.MCP:
        return True
    return (
        integration.auth_mode is IntegrationAuthMode.INDIVIDUAL
        and integration.auth_method is IntegrationAuthMethod.API_KEY
    )


def _fills_template(
    integration: Integration, secret: ConnectionSecret, user: User | None
) -> bool:
    try:
        render_headers(
            integration.header_template,
            secret,
            extra_values={"user_email": user.email} if user is not None else None,
        )
    except MissingHeaderValueError:
        return False
    return True


def _with_legacy_defaults(
    integration: Integration,
    acting_user: User | None,
    resolved: ResolvedConnection | ConnectionProblem,
    db_session: Session,
) -> ResolvedConnection | ConnectionProblem:
    """Add what an old organization row gave every user: the template of
    an MCP admin config, or the field values of a custom app. As the old
    code did, a custom app user with no row calls with the organization
    values when they fill the template, and an MCP server with no sign-in
    needs the values a user saved for its template."""
    if not _may_have_legacy_defaults(integration) or (
        isinstance(resolved, ConnectionProblem)
        and resolved.code is not ConnectionState.NOT_CONNECTED
    ):
        return resolved
    organization = get_connection(db_session, integration.id, None)
    defaults = (
        legacy_organization_defaults(
            organization,
            template_in_headers=integration.auth_method
            is IntegrationAuthMethod.API_KEY,
        )
        if organization is not None
        else None
    )
    if organization is None or defaults is None:
        return resolved
    signed_in_user = _signed_in(acting_user)
    if isinstance(resolved, ConnectionProblem):
        if (
            signed_in_user is not None
            and organization.legacy_format
            == IntegrationLegacyFormat.EXTERNAL_APP_ORG.value
            and integration.header_template
            and _fills_template(integration, defaults, signed_in_user)
        ):
            return ResolvedConnection(
                integration_id=integration.id,
                connection_id=organization.id,
                secret=defaults,
            )
        return resolved
    secret = resolved.secret
    if resolved.connection_id is None:
        # No sign-in or the Onyx login: the old MCP server filled its
        # template with the values the user saved.
        user_row = (
            get_connection(db_session, integration.id, signed_in_user.id)
            if signed_in_user is not None
            else None
        )
        saved = read_connection(user_row).secret if user_row else ConnectionSecret()
        saved = (
            saved.model_copy(
                update={
                    "access_token": secret.access_token,
                    "token_type": secret.token_type,
                }
            )
            if secret is not None
            else saved
        )
        merged = merge_legacy_defaults(saved, defaults)
        if not _fills_template(integration, merged, signed_in_user):
            return ConnectionProblem(
                code=ConnectionState.NOT_CONNECTED,
                reason=_not_connected_reason(integration),
            )
        return resolved.model_copy(update={"secret": merged})
    if secret is None:
        return resolved
    return resolved.model_copy(
        update={"secret": merge_legacy_defaults(secret, defaults)}
    )


def _resolve_by_mode(
    integration: Integration,
    acting_user: User | None,
    db_session: Session,
    refresh: bool,
) -> ResolvedConnection | ConnectionProblem:
    if integration.auth_mode is IntegrationAuthMode.NONE:
        return ResolvedConnection(
            integration_id=integration.id, connection_id=None, secret=None
        )

    if integration.auth_mode is IntegrationAuthMode.SHARED:
        return _connection_or_problem(
            integration,
            get_connection(db_session, integration.id, None),
            ConnectionProblem(
                code=ConnectionState.NOT_SET_UP,
                reason=not_set_up_reason(integration),
            ),
            db_session,
            refresh,
        )

    not_connected = ConnectionProblem(
        code=ConnectionState.NOT_CONNECTED,
        reason=_not_connected_reason(integration),
    )
    user = _signed_in(acting_user)
    if user is None:
        return not_connected

    if integration.auth_method is IntegrationAuthMethod.ONYX_LOGIN:
        return _resolve_onyx_login(integration, user, db_session, refresh)

    return _connection_or_problem(
        integration,
        get_connection(db_session, integration.id, user.id),
        not_connected,
        db_session,
        refresh,
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
    return reload_oauth_account(db_session, account.id) or account


def _fresh_onyx_login_token(
    user: User, account: OAuthAccount, db_session: Session
) -> str | None:
    """Refreshes a token near expiry with no web request. None when the
    token expired and could not be renewed."""
    if not _login_token_stale(account, datetime.now(timezone.utc).timestamp()):
        return account.access_token
    if account.refresh_token:
        try:
            with cache_shared_lock(
                onyx_login_refresh_lock_name(user.id),
                max_time_lock_held_s=_REFRESH_LOCK_LEASE_S,
                wait_for_lock_s=_REFRESH_LOCK_WAIT_S,
                logger=logger,
            ):
                account = _reload_account(db_session, account)
                db_user = fetch_user_by_id(db_session, user.id)
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
    integration: Integration, user: User, db_session: Session, refresh: bool
) -> ResolvedConnection | ConnectionProblem:
    account = _live_login_account(user)
    if account is None:
        return ConnectionProblem(
            code=ConnectionState.NOT_CONNECTED,
            reason=f"Sign in to Onyx with single sign-on to use {integration.name}.",
        )
    token = (
        _fresh_onyx_login_token(user, account, db_session)
        if refresh
        else account.access_token
    )
    if token is None:
        return ConnectionProblem(
            code=ConnectionState.NEEDS_RECONNECT,
            reason=f"Sign in to Onyx again to use {integration.name}.",
        )
    return ResolvedConnection(
        integration_id=integration.id,
        connection_id=None,
        secret=ConnectionSecret(access_token=token, token_type="Bearer"),
    )


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
    """``{{``/``}}`` are literal; a missing placeholder raises
    ``MissingHeaderValueError``."""
    secret = secret or ConnectionSecret()
    templates = merge_mcp_headers(secret.headers, dict(header_template or {}))
    values = _placeholder_values(secret, extra_values)
    missing = sorted(
        {
            match.group(1)
            for template in templates.values()
            for match in _TEMPLATE_TOKEN_RE.finditer(template)
            if match.group(1) is not None and not values.get(match.group(1))
        }
    )
    if missing:
        raise MissingHeaderValueError(missing)

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        return match.group(0)[0] if name is None else values[name]

    return {
        name: _TEMPLATE_TOKEN_RE.sub(fill, template)
        for name, template in templates.items()
    }


def _needs_refresh(record: ConnectionRecord, now: datetime) -> bool:
    return (
        record.status is IntegrationConnectionStatus.CONNECTED
        and record.expires_at is not None
        and record.expires_at - now <= REFRESH_SKEW
    )


def ensure_fresh_connection(
    connection: IntegrationConnection,
    integration: Integration,
    db_session: Session,
) -> IntegrationConnection:
    """One lock per connection; a permanent error sets Needs reconnect and
    keeps the row."""
    if not _needs_refresh(read_connection(connection), datetime.now(timezone.utc)):
        return connection
    try:
        with cache_shared_lock(
            connection_refresh_lock_name(integration.id, connection.user_id),
            max_time_lock_held_s=_REFRESH_LOCK_LEASE_S,
            wait_for_lock_s=_REFRESH_LOCK_WAIT_S,
            logger=logger,
        ):
            # Another caller may have refreshed while this one waited.
            reload_connection(db_session, connection)
            record = read_connection(connection)
            if _needs_refresh(record, datetime.now(timezone.utc)):
                _refresh_under_lock(connection, record, integration, db_session)
    except CacheLockAcquisitionError:
        logger.info(
            "integration_connection.refresh.lock_contended connection_id=%s",
            connection.id,
        )
        reload_connection(db_session, connection)
    return connection


def _still_holds(
    connection: IntegrationConnection, secret: ConnectionSecret, db_session: Session
) -> bool:
    """Lock the row and check that it still holds ``secret``. An OAuth
    callback does not take the refresh lock, so it can store a new grant
    while a refresh runs."""
    current = get_connection_by_id(db_session, connection.id, for_update=True)
    if current is not None:
        stored = read_connection_secret(current)
        if (stored.access_token, stored.refresh_token) == (
            secret.access_token,
            secret.refresh_token,
        ):
            return True
    db_session.rollback()
    logger.info(
        "integration_connection.refresh.superseded connection_id=%s", connection.id
    )
    return False


def _refresh_under_lock(
    connection: IntegrationConnection,
    record: ConnectionRecord,
    integration: Integration,
    db_session: Session,
) -> None:
    secret = record.secret
    if not secret.refresh_token:
        if (
            record.expires_at is not None
            and record.expires_at <= datetime.now(timezone.utc)
            and _still_holds(connection, secret, db_session)
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
        if not _still_holds(connection, secret, db_session):
            return
        mark_connection_needs_reconnect__no_commit(db_session, connection, error.reason)
        db_session.commit()
        return

    refreshed = secret.model_copy(
        update={
            "access_token": grant.secret.access_token,
            "refresh_token": grant.secret.refresh_token or secret.refresh_token,
            "token_type": grant.secret.token_type or secret.token_type,
            "fields": {**secret.fields, **grant.secret.fields},
        }
    )
    if not _still_holds(connection, secret, db_session):
        return
    update_connection_secret__no_commit(
        db_session,
        connection,
        secret=refreshed.model_dump(mode="json"),
        expires_at=expiry_from_expires_in(grant.expires_in, datetime.now(timezone.utc)),
        granted_scopes=record.granted_scopes,
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
) -> RefreshedGrant:
    oauth_client = get_oauth_client(db_session, integration.id)
    if oauth_client is None:
        raise _RefreshTemporaryError("the integration has no OAuth client")
    if integration.kind is IntegrationKind.MCP:
        return _refresh_with_mcp_sdk(integration, connection, oauth_client, db_session)
    if oauth_client.provider_mode is IntegrationOAuthProviderMode.PRESET:
        return _refresh_with_preset(integration, secret, oauth_client, db_session)
    return _refresh_with_token_url(secret, oauth_client)


def _client_credentials(
    oauth_client: IntegrationOAuthClient,
) -> tuple[str | None, str | None]:
    credentials = read_oauth_client(oauth_client)
    return credentials.client_id, credentials.client_secret


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


def _expires_in(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _grant_from_token_response(request: httpx.Request, mcp: bool) -> RefreshedGrant:
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
    return RefreshedGrant(
        secret=ConnectionSecret(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            token_type=token_type if isinstance(token_type, str) else None,
        ),
        expires_in=_expires_in(body.get("expires_in")),
    )


def _refresh_with_token_url(
    secret: ConnectionSecret, oauth_client: IntegrationOAuthClient
) -> RefreshedGrant:
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
    oauth_client = get_oauth_client(db_session, integration.id)
    if oauth_client is None:
        return {}
    return read_oauth_client(oauth_client).host_values


def preset_provider_for(
    integration: Integration, db_session: Session
) -> OAuthExternalAppProvider | None:
    app = get_external_app_for_integration(integration.id, db_session)
    if app is None:
        return None
    provider = get_provider_for_app(app)
    return provider if isinstance(provider, OAuthExternalAppProvider) else None


def _refresh_with_preset(
    integration: Integration,
    secret: ConnectionSecret,
    oauth_client: IntegrationOAuthClient,
    db_session: Session,
) -> RefreshedGrant:
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
    refreshed_secret, _ = preset_credentials_to_secret(refreshed)
    if not refreshed_secret.access_token:
        raise _RefreshTemporaryError("the preset refresh gave no access token")
    return RefreshedGrant(
        secret=refreshed_secret, expires_in=_expires_in(refreshed.get("expires_in"))
    )


def _refresh_with_mcp_sdk(
    integration: Integration,
    connection: IntegrationConnection,
    oauth_client: IntegrationOAuthClient,
    db_session: Session,
) -> RefreshedGrant:
    mcp_server = get_mcp_server_for_integration(integration.id, db_session)
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


def oauth_client_configured(
    integration: Integration, oauth_client: IntegrationOAuthClient | None
) -> bool:
    if integration.auth_method is not IntegrationAuthMethod.OAUTH2:
        return True
    if oauth_client is None:
        return False
    if oauth_client.provider_mode is IntegrationOAuthProviderMode.DISCOVERY:
        return True
    client_id, _ = _client_credentials(oauth_client)
    return client_id is not None


def integration_status(
    integration: Integration, user: User | None, db_session: Session
) -> IntegrationStatus:
    if integration.auth_mode is not IntegrationAuthMode.NONE and (
        not oauth_client_configured(
            integration, get_oauth_client(db_session, integration.id)
        )
    ):
        return IntegrationStatus(
            state=ConnectionState.NOT_SET_UP, reason=not_set_up_reason(integration)
        )
    result = resolve_connection(integration, user, db_session, refresh=False)
    if isinstance(result, ConnectionProblem):
        return IntegrationStatus(state=result.code, reason=result.reason)
    return IntegrationStatus(state=ConnectionState.CONNECTED, reason=None)


def disconnect(integration: Integration, user: User, db_session: Session) -> bool:
    deleted = delete_connection__no_commit(db_session, integration.id, user.id)
    db_session.commit()
    return deleted


def sign_in_settings_for(
    integration: Integration,
    oauth_client: IntegrationOAuthClient | None,
    host: str | None,
) -> SignInSettings:
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


def mark_sign_in_settings_changed(integration_id: int, db_session: Session) -> None:
    """Does not commit: the caller commits with the settings change."""
    mark_integration_connections_needs_reconnect__no_commit(
        db_session, integration_id, SIGN_IN_SETTINGS_CHANGED_REASON
    )
