import re
from collections.abc import Collection, Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
import requests
from pydantic import JsonValue, ValidationError
from sqlalchemy.orm import Session

from onyx.auth.oauth_refresher import (
    onyx_login_refresh_lock_name,
    refresh_oauth_account_sync,
)
from onyx.auth.oauth_token_manager import validate_oauth_endpoint_url
from onyx.cache.interface import CacheLockAcquisitionError
from onyx.cache.locks import cache_shared_lock
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    ApiAppType,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationConnectionStatus,
    IntegrationKind,
    IntegrationLegacyFormat,
    IntegrationOAuthProviderMode,
)
from onyx.db.integration import (
    get_api_app_for_integration,
    get_external_app_for_integration,
    get_mcp_server_for_integration,
    lock_integration__no_commit,
)
from onyx.db.integration_connection import (
    get_connection_by_id,
    get_connection_with_organization,
    get_oauth_client,
    get_oauth_clients,
    list_connections,
    mark_connection_needs_reconnect__no_commit,
    mark_integration_connections_needs_reconnect__no_commit,
    reload_connection,
    update_connection_secret__no_commit,
    upsert_connection__no_commit,
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
    connection_secret_fingerprint,
    expiry_from_expires_in,
    legacy_organization_defaults,
    merge_legacy_defaults,
    preset_credentials_to_secret,
    read_connection,
    read_oauth_client,
    secret_fingerprint,
)
from onyx.oauth.authorization_attempt import canonical_json_fingerprint
from onyx.server.features.integrations.models import CredentialField
from onyx.server.features.mcp.models import (
    DENYLISTED_MCP_HEADERS,
    merge_mcp_headers,
)
from onyx.server.features.mcp.oauth import (
    IntegrationTokenStorage,
    integration_mcp_server_connection,
    make_integration_oauth_provider,
    oauth_error_from_response,
    oauth_token_from_response,
    oauth_token_from_secret,
)
from onyx.server.features.mcp.ssrf import mcp_ssrf_httpx_client_factory
from onyx.tools.tool_implementations.api_app.openapi_parsing import (
    openapi_to_url,
    parse_openapi_document,
)
from onyx.utils.encryption import reject_masked_credentials
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
    record = read_connection(connection)
    if refresh and _needs_refresh(record, datetime.now(timezone.utc)):
        connection = ensure_fresh_connection(connection, integration, db_session)
        if connection is None:
            return missing
        record = read_connection(connection)
    if record.status is IntegrationConnectionStatus.NEEDS_RECONNECT:
        return ConnectionProblem(
            code=ConnectionState.NEEDS_RECONNECT,
            reason=_needs_reconnect_reason(integration, record),
        )
    # After a refresh attempt, a token that is still expired is not usable.
    if (
        record.expires_at is not None
        and record.expires_at <= datetime.now(timezone.utc)
        and (refresh or not record.secret.refresh_token)
    ):
        return ConnectionProblem(
            code=ConnectionState.NEEDS_RECONNECT, reason=SIGN_IN_EXPIRED_REASON
        )
    return ResolvedConnection(
        integration_id=integration.id,
        connection_id=connection.id,
        secret=record.secret,
        secret_fingerprint=secret_fingerprint(record.secret),
        expires_at=record.expires_at,
    )


def resolve_connection(
    integration: Integration,
    acting_user: User | None,
    db_session: Session,
    *,
    refresh: bool = True,
    connections: Mapping[tuple[int, UUID | None], IntegrationConnection] | None = None,
) -> ResolvedConnection | ConnectionProblem:
    """The credential for one call by ``acting_user``, or why there is none.
    The caller always gives the acting user: the chat user, the sandbox
    owner, the owner of a scheduled task, or the user a bot resolves. With
    ``refresh=False`` it only reads and never calls the service."""
    user = _signed_in(acting_user)
    legacy = _may_have_legacy_defaults(integration)
    if integration.auth_mode is IntegrationAuthMode.NONE and not legacy:
        return ResolvedConnection(
            integration_id=integration.id, connection_id=None, secret=None
        )
    if connections is None:
        organization, user_row = get_connection_with_organization(
            db_session, integration.id, user.id if user is not None else None
        )
    else:
        organization = connections.get((integration.id, None))
        user_row = (
            connections.get((integration.id, user.id)) if user is not None else None
        )
    resolved = _resolve_by_mode(
        integration, user, organization, user_row, db_session, refresh
    )
    if not legacy:
        return resolved
    return _with_legacy_defaults(integration, user, resolved, organization, user_row)


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
    signed_in_user: User | None,
    resolved: ResolvedConnection | ConnectionProblem,
    organization: IntegrationConnection | None,
    user_row: IntegrationConnection | None,
) -> ResolvedConnection | ConnectionProblem:
    """Add what an old organization row gave every user: the template of
    an MCP admin config, or the field values of a custom app. As the old
    code did, a custom app user with no row calls with the organization
    values when they fill the template, and an MCP server with no sign-in
    needs the values a user saved for its template."""
    if (
        isinstance(resolved, ConnectionProblem)
        and resolved.code is not ConnectionState.NOT_CONNECTED
    ):
        return resolved
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
    if isinstance(resolved, ConnectionProblem):
        if (
            signed_in_user is not None
            and organization.legacy_format
            == IntegrationLegacyFormat.EXTERNAL_APP_ORG.value
            and integration.header_template
            and _fills_template(integration, defaults, signed_in_user)
        ):
            organization_record = read_connection(organization)
            if (
                organization_record.status
                is IntegrationConnectionStatus.NEEDS_RECONNECT
            ):
                return ConnectionProblem(
                    code=ConnectionState.NEEDS_RECONNECT,
                    reason=_needs_reconnect_reason(integration, organization_record),
                )
            return ResolvedConnection(
                integration_id=integration.id,
                connection_id=organization.id,
                secret=defaults,
                secret_fingerprint=connection_secret_fingerprint(organization),
            )
        return resolved
    secret = resolved.secret
    if resolved.connection_id is None:
        # No sign-in or the Onyx login: the old MCP server filled its
        # template with the values the user saved.
        saved_record = read_connection(user_row) if user_row else None
        if (
            saved_record is not None
            and saved_record.status is IntegrationConnectionStatus.NEEDS_RECONNECT
        ):
            return ConnectionProblem(
                code=ConnectionState.NEEDS_RECONNECT,
                reason=_needs_reconnect_reason(integration, saved_record),
            )
        saved = saved_record.secret if saved_record else ConnectionSecret()
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
    user: User | None,
    organization: IntegrationConnection | None,
    user_row: IntegrationConnection | None,
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
            organization,
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
    if user is None:
        return not_connected

    if integration.auth_method is IntegrationAuthMethod.ONYX_LOGIN:
        return _resolve_onyx_login(integration, user, db_session, refresh)

    return _connection_or_problem(
        integration,
        user_row,
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


def _login_token_expired(account: OAuthAccount) -> bool:
    return (
        account.expires_at is not None
        and account.expires_at <= datetime.now(timezone.utc).timestamp()
    )


def _refresh_login_account(user_id: UUID, account_id: UUID) -> bool:
    """Writes in its own session, so the session of the caller stays
    unchanged. True when this call renewed the token."""
    with get_session_with_current_tenant() as db_session:
        account = reload_oauth_account(db_session, account_id)
        db_user = fetch_user_by_id(db_session, user_id)
        if (
            account is None
            or db_user is None
            or not _login_token_stale(account, datetime.now(timezone.utc).timestamp())
            or not refresh_oauth_account_sync(db_user, account, db_session)
        ):
            return False
        db_session.commit()
        return True


def _fresh_onyx_login_account(
    user: User, account: OAuthAccount, db_session: Session
) -> OAuthAccount | None:
    """Refreshes a token near expiry with no web request and returns the
    account with the current token and expiry. None when the token expired and
    could not be renewed, or the account was deleted."""
    if not _login_token_stale(account, datetime.now(timezone.utc).timestamp()):
        return account
    refreshed = False
    if account.refresh_token:
        try:
            with cache_shared_lock(
                onyx_login_refresh_lock_name(user.id),
                max_time_lock_held_s=_REFRESH_LOCK_LEASE_S,
                wait_for_lock_s=_REFRESH_LOCK_WAIT_S,
                logger=logger,
            ):
                refreshed = _refresh_login_account(user.id, account.id)
        except CacheLockAcquisitionError:
            pass
    # The user can come from the auth session of the request, so read the
    # row in the session of the caller.
    current = reload_oauth_account(db_session, account.id)
    if current is None:
        return None
    # A refresh with no expires_in keeps the old expiry.
    if not refreshed and _login_token_expired(current):
        return None
    return current


def _resolve_onyx_login(
    integration: Integration, user: User, db_session: Session, refresh: bool
) -> ResolvedConnection | ConnectionProblem:
    account = _live_login_account(user)
    if account is None:
        return ConnectionProblem(
            code=ConnectionState.NOT_CONNECTED,
            reason=f"Sign in to Onyx with single sign-on to use {integration.name}.",
        )
    current: OAuthAccount | None
    if refresh:
        current = _fresh_onyx_login_account(user, account, db_session)
    elif _login_token_expired(account) and not account.refresh_token:
        current = None
    else:
        current = account
    if current is None:
        return ConnectionProblem(
            code=ConnectionState.NEEDS_RECONNECT,
            reason=f"Sign in to Onyx again to use {integration.name}.",
        )
    return ResolvedConnection(
        integration_id=integration.id,
        connection_id=None,
        secret=ConnectionSecret(access_token=current.access_token, token_type="Bearer"),
        expires_at=(
            datetime.fromtimestamp(current.expires_at, timezone.utc)
            if current.expires_at is not None
            else None
        ),
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


def has_placeholder(template: str) -> bool:
    return any(
        match.group(1) is not None for match in _TEMPLATE_TOKEN_RE.finditer(template)
    )


def render_headers(
    header_template: Mapping[str, str] | None,
    secret: ConnectionSecret | None,
    *,
    extra_values: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """``{{``/``}}`` are literal; a missing placeholder raises
    ``MissingHeaderValueError``."""
    secret = secret or ConnectionSecret()
    templates = {
        name: template
        for name, template in merge_mcp_headers(
            secret.headers, dict(header_template or {})
        ).items()
        if name.lower() not in DENYLISTED_MCP_HEADERS
    }
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


def literal_headers(header_template: Mapping[str, str] | None) -> dict[str, str]:
    """The headers of the template that need no connection value."""
    return render_headers(
        {
            name: template
            for name, template in (header_template or {}).items()
            if not has_placeholder(template)
        },
        None,
    )


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
) -> IntegrationConnection | None:
    """One lock per connection; a permanent error sets Needs reconnect and
    keeps the row. None when another caller deleted the row."""
    if not _needs_refresh(read_connection(connection), datetime.now(timezone.utc)):
        return connection
    try:
        with cache_shared_lock(
            connection_refresh_lock_name(integration.id, connection.user_id),
            max_time_lock_held_s=_REFRESH_LOCK_LEASE_S,
            wait_for_lock_s=_REFRESH_LOCK_WAIT_S,
            logger=logger,
        ):
            _refresh_under_lock(connection.id, integration)
    except CacheLockAcquisitionError:
        logger.info(
            "integration_connection.refresh.lock_contended connection_id=%s",
            connection.id,
        )
    # Another caller can refresh or delete the row while this one waits.
    return connection if reload_connection(db_session, connection) else None


def _still_holds(
    connection: IntegrationConnection, secret: ConnectionSecret, db_session: Session
) -> bool:
    """Lock the row and check that it is still connected with ``secret``.
    An OAuth callback or a sign-in settings change does not take the refresh
    lock, so it can change the row while a refresh runs."""
    current = get_connection_by_id(db_session, connection.id, for_update=True)
    if current is not None:
        record = read_connection(current)
        if record.status is IntegrationConnectionStatus.CONNECTED and (
            record.secret.access_token,
            record.secret.refresh_token,
        ) == (secret.access_token, secret.refresh_token):
            return True
    logger.info(
        "integration_connection.refresh.superseded connection_id=%s", connection.id
    )
    return False


def _refresh_under_lock(connection_id: int, integration: Integration) -> None:
    """Writes in its own session, so the session of the caller stays
    unchanged. A return before the commit discards the row lock."""
    with get_session_with_current_tenant() as db_session:
        connection = get_connection_by_id(db_session, connection_id)
        if connection is None:
            return
        record = read_connection(connection)
        if _needs_refresh(record, datetime.now(timezone.utc)):
            _refresh_connection(connection, record, integration, db_session)


def _refresh_connection(
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
        grant = _request_refreshed_grant(integration, connection, record, db_session)
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
    record: ConnectionRecord,
    db_session: Session,
) -> RefreshedGrant:
    secret = record.secret
    oauth_client = get_oauth_client(db_session, integration.id)
    if oauth_client is None:
        raise _RefreshTemporaryError("the integration has no OAuth client")
    if integration.kind is IntegrationKind.MCP:
        return _refresh_with_mcp_sdk(
            integration, connection, record, oauth_client, db_session
        )
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

    oauth_error, _ = oauth_error_from_response(
        response.content, response.headers.get("content-type")
    )
    # Other OAuth errors, such as invalid_client, come from the client
    # settings, not from a revoked grant. An admin can fix them.
    if oauth_error == "invalid_grant" or (
        response.status_code in _PERMANENT_REFRESH_STATUSES and oauth_error is None
    ):
        detail = f" ({oauth_error})" if oauth_error else ""
        raise _RefreshPermanentError(
            f"The service refused to renew the sign-in{detail}. Reconnect."
        )
    if response.status_code != 200:
        raise _RefreshTemporaryError(f"token endpoint status {response.status_code}")
    if mcp:
        # An MCP server can answer with a form-encoded body.
        try:
            token = oauth_token_from_response(response.content)
        except ValidationError as error:
            raise _RefreshTemporaryError(
                "token response has no access token"
            ) from error
        return RefreshedGrant(
            secret=ConnectionSecret(
                access_token=token.access_token,
                refresh_token=token.refresh_token,
                token_type=token.token_type,
            ),
            expires_in=token.expires_in,
        )
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


def sign_in_host(integration: Integration, db_session: Session) -> str | None:
    """Where the credentials go: the MCP server URL, or the OpenAPI server
    URL, the GraphQL endpoint URL, the app URL patterns and the preset host
    values."""
    if integration.kind is IntegrationKind.MCP:
        mcp_server = get_mcp_server_for_integration(integration.id, db_session)
        return mcp_server.server_url if mcp_server is not None else None
    destinations: dict[str, JsonValue] = {}
    api_app = get_api_app_for_integration(integration.id, db_session)
    if api_app is not None and api_app.openapi_document is not None:
        try:
            destinations["openapi_url"] = openapi_to_url(
                parse_openapi_document(api_app.openapi_document)
            )
        except ValueError:
            destinations["openapi_url"] = None
    elif api_app is not None and api_app.api_type is ApiAppType.GRAPHQL:
        destinations["graphql_url"] = api_app.base_url
    app = get_external_app_for_integration(integration.id, db_session)
    if app is not None:
        destinations["upstream_url_patterns"] = sorted(app.upstream_url_patterns)
    host_values = preset_host_values(integration, db_session)
    if host_values:
        destinations["host_values"] = host_values
    return canonical_json_fingerprint(destinations) if destinations else None


def preset_organization_values(
    integration_id: int, db_session: Session
) -> dict[str, str]:
    """The organization settings of a preset that are not secret: the host
    values and the client id."""
    oauth_client = get_oauth_client(db_session, integration_id)
    if oauth_client is None:
        return {}
    credentials = read_oauth_client(oauth_client)
    values = dict(credentials.host_values)
    if credentials.client_id:
        values["client_id"] = credentials.client_id
    return values


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
    record: ConnectionRecord,
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
        request = run_async_sync_no_cancel(
            provider.build_refresh_request(
                oauth_token_from_secret(record.secret, record.granted_scopes)
            )
        )
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


def header_template_missing(integration: Integration) -> bool:
    """A per-user API key MCP server whose template the migration could not
    read: new users have no fields to fill. Users with an old connection keep
    its stored headers, so only the admin list treats it as not set up."""
    return (
        integration.kind is IntegrationKind.MCP
        and integration.auth_mode is IntegrationAuthMode.INDIVIDUAL
        and integration.auth_method is IntegrationAuthMethod.API_KEY
        and not integration.header_template
    )


def integration_status(
    integration: Integration, user: User | None, db_session: Session
) -> IntegrationStatus:
    return integration_statuses([integration], user, db_session)[integration.id]


def _reads_connections(integration: Integration) -> bool:
    if integration.auth_mode is IntegrationAuthMode.NONE:
        return _may_have_legacy_defaults(integration)
    return integration.auth_method is not IntegrationAuthMethod.ONYX_LOGIN or (
        _may_have_legacy_defaults(integration)
    )


def integration_statuses(
    integrations: Collection[Integration], user: User | None, db_session: Session
) -> dict[int, IntegrationStatus]:
    """The status of each integration for ``user`` (None: the organization
    connection). One query reads the OAuth clients and one the connections,
    for all integrations."""
    oauth_clients = get_oauth_clients(
        db_session,
        [
            integration.id
            for integration in integrations
            if integration.auth_method is IntegrationAuthMethod.OAUTH2
        ],
    )
    signed_in_user = _signed_in(user)
    connections = list_connections(
        db_session,
        [
            integration.id
            for integration in integrations
            if _reads_connections(integration)
        ],
        signed_in_user.id if signed_in_user is not None else None,
    )
    statuses: dict[int, IntegrationStatus] = {}
    for integration in integrations:
        if integration.auth_mode is not IntegrationAuthMode.NONE and (
            not oauth_client_configured(integration, oauth_clients.get(integration.id))
        ):
            statuses[integration.id] = IntegrationStatus(
                state=ConnectionState.NOT_SET_UP,
                reason=not_set_up_reason(integration),
            )
            continue

        organization = connections.get((integration.id, None))
        user_row = (
            connections.get((integration.id, signed_in_user.id))
            if signed_in_user is not None
            else None
        )
        result = _resolve_by_mode(
            integration,
            signed_in_user,
            organization,
            user_row,
            db_session,
            refresh=False,
        )
        if _may_have_legacy_defaults(integration):
            result = _with_legacy_defaults(
                integration, signed_in_user, result, organization, user_row
            )
        statuses[integration.id] = (
            IntegrationStatus(state=result.code, reason=result.reason)
            if isinstance(result, ConnectionProblem)
            else IntegrationStatus(state=ConnectionState.CONNECTED, reason=None)
        )
    return statuses


def credential_field_keys(integration: Integration) -> list[str]:
    """The keys a person fills for an api_key connection: the stored
    credential fields, else the placeholders of the header template."""
    if integration.credential_fields:
        return [
            str(field["key"])
            for field in integration.credential_fields
            if isinstance(field.get("key"), str)
        ]
    return header_field_keys(integration.header_template or {})


def header_field_keys(header_template: Mapping[str, str]) -> list[str]:
    """The placeholders of a header template that a person fills, in
    order. ``user_email`` is filled by Onyx."""
    keys: list[str] = []
    for value in header_template.values():
        for match in _TEMPLATE_TOKEN_RE.finditer(value):
            key = match.group(1)
            if key is not None and key != "user_email" and key not in keys:
                keys.append(key)
    return keys


def credential_fields_json(
    fields: list[CredentialField] | None,
    header_template: Mapping[str, str] | None,
    stored: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]] | None:
    """The stored credential fields: the given fields, then a secret field
    for each other placeholder of the template."""
    if fields is not None:
        stored = [field.model_dump() for field in fields]
    if not header_template:
        return stored if fields is not None else None
    kept = {field.get("key"): field for field in stored or []}
    template_fields = [
        kept.get(key) or {"key": key, "label": key.replace("_", " "), "secret": True}
        for key in header_field_keys(header_template)
    ]
    if fields is not None:
        listed = {field["key"] for field in stored or []}
        return [
            *(stored or []),
            *(f for f in template_fields if f["key"] not in listed),
        ]
    return template_fields or None


def check_connection_mode(integration: Integration, for_organization: bool) -> None:
    if for_organization != (integration.auth_mode is IntegrationAuthMode.SHARED):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{integration.name} uses "
            + (
                "one connection for the organization."
                if integration.auth_mode is IntegrationAuthMode.SHARED
                else "a connection for each user."
            ),
        )


def connect_with_fields__no_commit(
    integration: Integration,
    user: User | None,
    fields: Mapping[str, str],
    db_session: Session,
) -> None:
    """Save an api_key connection for ``user``, or for the organization when
    ``user`` is None. Each credential field needs a value; other keys are
    refused. The integration row lock orders the save with a settings
    change, which sets the connections to Needs reconnect."""
    lock_integration__no_commit(integration.id, db_session)
    if integration.auth_method is not IntegrationAuthMethod.API_KEY:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{integration.name} does not sign in with an API key.",
        )
    check_connection_mode(integration, for_organization=user is None)
    keys = credential_field_keys(integration)
    unknown = sorted(set(fields) - set(keys))
    if unknown:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Unknown fields: " + ", ".join(unknown)
        )
    missing = [key for key in keys if not fields.get(key, "").strip()]
    if missing:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Fill in: " + ", ".join(missing))
    try:
        reject_masked_credentials(dict(fields))
    except ValueError as error:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(error)) from error
    upsert_connection__no_commit(
        db_session,
        integration_id=integration.id,
        user_id=user.id if user is not None else None,
        secret=ConnectionSecret(fields=dict(fields)).model_dump(mode="json"),
        expires_at=None,
        granted_scopes=None,
    )


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
