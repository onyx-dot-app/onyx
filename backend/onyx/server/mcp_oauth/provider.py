import re
import socket
import time
from functools import lru_cache
from urllib.parse import urlencode, urlsplit

from fastmcp.server.auth import OAuthProvider
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.cimd import CIMDFetcher, CIMDFetchError, CIMDValidationError
from fastmcp.server.auth.ssrf import SSRFError
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
)
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl, BaseModel, ConfigDict
from starlette.concurrency import run_in_threadpool

from onyx.db.engine.async_sql_engine import get_async_session_context_manager
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.mcp_oauth import (
    create_mcp_oauth_grant__no_commit,
    get_mcp_oauth_client,
    get_mcp_oauth_owner,
    get_mcp_oauth_token_owner,
    load_mcp_oauth_refresh__no_commit,
    mcp_oauth_owner_is_member,
    mcp_oauth_owner_snapshot,
    register_mcp_oauth_client,
    resolve_mcp_oauth_access_token,
    revoke_mcp_oauth_token__no_commit,
    rotate_mcp_oauth_refresh__no_commit,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.mcp_oauth.attempts import (
    consume_authorization_code,
    get_authorization_code,
    store_authorization_request,
)
from onyx.mcp_oauth.config import (
    MCPOAuthSettings,
    canonical_mcp_resource,
    validate_mcp_redirect_uri,
)
from onyx.mcp_oauth.models import (
    MCPOAuthAuthorizationCode,
    MCPOAuthTokenInfo,
    MCPOAuthTokenPair,
    PendingMCPOAuthAuthorization,
    StoredMCPOAuthCode,
)
from shared_configs.contextvars import get_current_tenant_id

_PKCE_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")


class MCPClientMetadataUnavailable(OnyxError):
    def __init__(self) -> None:
        super().__init__(
            OnyxErrorCode.SERVICE_UNAVAILABLE, "Client metadata is unavailable"
        )


class AuthorizationClientSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_id: str
    client: OAuthClientInformationFull | None


@lru_cache(maxsize=128)
def _cimd_fetcher(_client_id: str) -> CIMDFetcher:
    return CIMDFetcher()


def validate_public_mcp_client(client: OAuthClientInformationFull) -> None:
    if client.token_endpoint_auth_method != "none" or client.client_secret is not None:
        raise ValueError("Only public clients with PKCE are supported")
    if not client.client_id or len(client.client_id) > 2048:
        raise ValueError("Invalid client identifier")
    if client.client_name is not None and (
        len(client.client_name) > 256
        or any(ord(character) < 32 for character in client.client_name)
    ):
        raise ValueError("Invalid client name")
    if not client.redirect_uris or len(client.redirect_uris) > 10:
        raise ValueError("Between one and ten redirect URIs are required")
    for redirect_uri in client.redirect_uris:
        validate_mcp_redirect_uri(str(redirect_uri))
    if (
        "authorization_code" not in client.grant_types
        or set(client.grant_types) - {"authorization_code", "refresh_token"}
        or client.response_types != ["code"]
    ):
        raise ValueError("Unsupported OAuth grant or response type")
    if client.scope is not None and set(client.scope.split()) != {
        Permission.READ_SEARCH.value
    }:
        raise ValueError("Only read:search access is supported")


def _create_grant(
    record: StoredMCPOAuthCode, *, issue_refresh: bool
) -> MCPOAuthTokenPair | None:
    with get_session_with_current_tenant() as session:
        owner = get_mcp_oauth_owner(session, record.user_id)
    if owner is None or not mcp_oauth_owner_is_member(
        get_current_tenant_id(), owner.email, owner.oauth_identities
    ):
        return None
    with get_session_with_current_tenant() as session:
        pair = create_mcp_oauth_grant__no_commit(
            session,
            user_id=record.user_id,
            client_id=record.authorization.client_id,
            client_name=record.authorization.client_name,
            resource=record.authorization.params.resource or "",
            issue_refresh=issue_refresh,
        )
        session.commit()
        return pair


def _refresh_owner_is_authorized(token: str, *, client_id: str, resource: str) -> bool:
    with get_session_with_current_tenant() as session:
        owner = get_mcp_oauth_token_owner(
            session, token, client_id=client_id, resource=resource
        )
    if owner is None:
        return False
    if mcp_oauth_owner_is_member(
        get_current_tenant_id(), owner.email, owner.oauth_identities
    ):
        return True
    _revoke_token(token, client_id=client_id, resource=resource)
    return False


def _load_refresh(
    token: str, *, client_id: str, resource: str
) -> MCPOAuthTokenInfo | None:
    if not _refresh_owner_is_authorized(token, client_id=client_id, resource=resource):
        return None
    with get_session_with_current_tenant() as session:
        info = load_mcp_oauth_refresh__no_commit(
            session, token, client_id=client_id, resource=resource
        )
        session.commit()
        return info


def _rotate_refresh(
    token: str, *, client_id: str, resource: str
) -> MCPOAuthTokenPair | None:
    if not _refresh_owner_is_authorized(token, client_id=client_id, resource=resource):
        return None
    with get_session_with_current_tenant() as session:
        pair = rotate_mcp_oauth_refresh__no_commit(
            session, token, client_id=client_id, resource=resource
        )
        session.commit()
        return pair


def _revoke_token(token: str, *, client_id: str, resource: str) -> None:
    with get_session_with_current_tenant() as session:
        revoke_mcp_oauth_token__no_commit(
            session, token, client_id=client_id, resource=resource
        )
        session.commit()


def _token_response(pair: MCPOAuthTokenPair) -> OAuthToken:
    return OAuthToken(
        access_token=pair.access_token,
        token_type="Bearer",
        expires_in=max(0, int(pair.expires_at.timestamp() - time.time())),
        refresh_token=pair.refresh_token,
        scope=" ".join(pair.scopes),
    )


class OnyxMCPOAuthProvider(OAuthProvider):
    def __init__(
        self,
        settings: MCPOAuthSettings,
        *,
        authorization_client: AuthorizationClientSnapshot | None = None,
    ) -> None:
        super().__init__(
            base_url=settings.issuer_url,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=[Permission.READ_SEARCH.value],
                default_scopes=[Permission.READ_SEARCH.value],
            ),
            revocation_options=RevocationOptions(enabled=True),
        )
        self.settings = settings
        self.authorization_client = authorization_client

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        if (
            self.authorization_client is not None
            and self.authorization_client.client_id == client_id
        ):
            return self.authorization_client.client
        if len(client_id) > 2048:
            return None
        if not client_id.startswith("https://"):
            return await run_in_threadpool(get_mcp_oauth_client, client_id)
        try:
            validate_mcp_redirect_uri(client_id)
            document = await _cimd_fetcher(client_id).fetch(client_id)
            if str(document.client_id) != client_id:
                return None
            client = OAuthClientInformationFull(
                client_id=client_id,
                client_name=document.client_name or urlsplit(client_id).netloc,
                redirect_uris=[
                    AnyUrl(validate_mcp_redirect_uri(uri))
                    for uri in document.redirect_uris
                ],
                grant_types=document.grant_types,
                response_types=document.response_types,
                scope=document.scope or Permission.READ_SEARCH.value,
                token_endpoint_auth_method=document.token_endpoint_auth_method,
            )
            validate_public_mcp_client(client)
            return client
        except CIMDFetchError:
            raise MCPClientMetadataUnavailable() from None
        except CIMDValidationError as error:
            cause = error.__cause__
            if (
                isinstance(cause, SSRFError)
                and isinstance(cause.__cause__, socket.gaierror)
                and cause.__cause__.errno in {socket.EAI_AGAIN, socket.EAI_FAIL}
            ):
                raise MCPClientMetadataUnavailable() from error
            return None
        except ValueError:
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        try:
            validate_public_mcp_client(client_info)
            await run_in_threadpool(register_mcp_oauth_client, client_info)
        except ValueError as error:
            raise RegistrationError("invalid_client_metadata", str(error)) from error

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        try:
            resource = canonical_mcp_resource(params.resource or "", self.settings)
        except ValueError as error:
            raise AuthorizeError("invalid_request", "Invalid MCP resource") from error
        scopes = params.scopes or [Permission.READ_SEARCH.value]
        if set(scopes) != {Permission.READ_SEARCH.value}:
            raise AuthorizeError(
                "invalid_scope", "Only read:search access is supported"
            )
        if _PKCE_CHALLENGE.fullmatch(params.code_challenge) is None:
            raise AuthorizeError(
                "invalid_request", "A valid S256 PKCE challenge is required"
            )
        if not client.client_id:
            raise AuthorizeError("invalid_request", "Client identifier is required")
        normalized = params.model_copy(
            update={"resource": resource, "scopes": [Permission.READ_SEARCH.value]}
        )
        request_id = await store_authorization_request(
            PendingMCPOAuthAuthorization(
                client_id=client.client_id,
                client_name=client.client_name or "MCP client",
                params=normalized,
            )
        )
        return f"{self.settings.web_url}/oauth/mcp/authorize?{urlencode({'request': request_id})}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> MCPOAuthAuthorizationCode | None:
        record = await get_authorization_code(authorization_code)
        if (
            record is None
            or record.authorization.client_id != client.client_id
            or record.tenant_id != get_current_tenant_id()
        ):
            return None
        params = record.authorization.params
        return MCPOAuthAuthorizationCode(
            code=authorization_code,
            client_id=record.authorization.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            scopes=params.scopes or [],
            resource=params.resource,
            expires_at=record.expires_at,
            subject=str(record.user_id),
            user_id=record.user_id,
            tenant_id=record.tenant_id,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        if not isinstance(authorization_code, MCPOAuthAuthorizationCode):
            raise TokenError("invalid_grant", "Invalid authorization code")
        record = await consume_authorization_code(authorization_code.code)
        if (
            record is None
            or record.authorization.client_id != client.client_id
            or record.user_id != authorization_code.user_id
            or record.tenant_id != get_current_tenant_id()
            or record.authorization.params.resource != self.settings.resource_url
        ):
            raise TokenError("invalid_grant", "Invalid or expired authorization code")
        pair = await run_in_threadpool(
            _create_grant, record, issue_refresh="refresh_token" in client.grant_types
        )
        if pair is None:
            raise TokenError("invalid_grant", "Authorization is no longer available")
        return _token_response(pair)

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        if not client.client_id:
            return None
        info = await run_in_threadpool(
            _load_refresh,
            refresh_token,
            client_id=client.client_id,
            resource=self.settings.resource_url,
        )
        if info is None:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=info.grant.client_id,
            scopes=list(info.grant.scopes),
            expires_at=int(info.expires_at.timestamp()),
            subject=str(info.grant.user_id),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        if not client.client_id or set(scopes) != {Permission.READ_SEARCH.value}:
            raise TokenError("invalid_scope", "Only read:search access is supported")
        pair = await run_in_threadpool(
            _rotate_refresh,
            refresh_token.token,
            client_id=client.client_id,
            resource=self.settings.resource_url,
        )
        if pair is None:
            raise TokenError("invalid_grant", "Invalid or expired refresh token")
        return _token_response(pair)

    async def load_access_token(self, token: str) -> AccessToken | None:
        async with get_async_session_context_manager() as session:
            result = await resolve_mcp_oauth_access_token(
                session, token, resource=self.settings.resource_url
            )
        if result is None:
            return None
        user, info = result
        owner = mcp_oauth_owner_snapshot(user)
        if not await run_in_threadpool(
            mcp_oauth_owner_is_member,
            get_current_tenant_id(),
            owner.email,
            owner.oauth_identities,
        ):
            return None
        return AccessToken(
            token=token,
            client_id=info.grant.client_id,
            scopes=list(info.grant.scopes),
            expires_at=int(info.expires_at.timestamp()),
            resource=info.grant.resource,
            subject=str(user.id),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        await run_in_threadpool(
            _revoke_token,
            token.token,
            client_id=token.client_id,
            resource=self.settings.resource_url,
        )
