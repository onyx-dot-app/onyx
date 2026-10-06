import re
import socket
import time
from collections.abc import Callable
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
from onyx.db.oauth_provider import (
    create_oauth_provider_grant__no_commit,
    get_oauth_provider_client,
    get_oauth_provider_owner,
    get_oauth_provider_token_owner,
    load_oauth_provider_refresh__no_commit,
    oauth_provider_owner_is_member,
    oauth_provider_owner_snapshot,
    register_oauth_provider_client,
    resolve_oauth_provider_access_token,
    revoke_oauth_provider_token__no_commit,
    rotate_oauth_provider_refresh__no_commit,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.oauth_provider.attempts import (
    consume_authorization_code,
    get_authorization_code,
    store_authorization_request,
)
from onyx.oauth_provider.config import (
    canonical_mcp_resource,
    validate_oauth_url,
)
from onyx.oauth_provider.models import (
    OAuthProviderAuthorizationCode,
    OAuthProviderSettings,
    OAuthProviderTokenPair,
    PendingOAuthProviderAuthorization,
    StoredOAuthProviderCode,
)
from shared_configs.contextvars import get_current_tenant_id

_PKCE_CHALLENGE = re.compile(r"[A-Za-z0-9_-]{43}")


class OAuthClientMetadataUnavailable(OnyxError):
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


def validate_public_oauth_client(client: OAuthClientInformationFull) -> None:
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
        validate_oauth_url(str(redirect_uri), allow_query=True)
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
    record: StoredOAuthProviderCode, *, issue_refresh: bool
) -> OAuthProviderTokenPair | None:
    with get_session_with_current_tenant() as session:
        owner = get_oauth_provider_owner(session, record.user_id)
    if owner is None or not oauth_provider_owner_is_member(
        get_current_tenant_id(), owner.email, owner.oauth_identities
    ):
        return None
    with get_session_with_current_tenant() as session:
        pair = create_oauth_provider_grant__no_commit(
            session,
            user_id=record.user_id,
            client_id=record.authorization.client_id,
            client_name=record.authorization.client_name,
            resource=record.authorization.params.resource or "",
            issue_refresh=issue_refresh,
        )
        session.commit()
        return pair


def _with_authorized_refresh[T](
    operation: Callable[..., T | None], token: str, *, client_id: str, resource: str
) -> T | None:
    with get_session_with_current_tenant() as session:
        owner = get_oauth_provider_token_owner(
            session, token, client_id=client_id, resource=resource
        )
    if owner is None:
        return None
    if not oauth_provider_owner_is_member(
        get_current_tenant_id(), owner.email, owner.oauth_identities
    ):
        _revoke_token(token, client_id=client_id, resource=resource)
        return None
    with get_session_with_current_tenant() as session:
        result = operation(session, token, client_id=client_id, resource=resource)
        session.commit()
        return result


def _revoke_token(token: str, *, client_id: str, resource: str) -> None:
    with get_session_with_current_tenant() as session:
        revoke_oauth_provider_token__no_commit(
            session, token, client_id=client_id, resource=resource
        )
        session.commit()


def _token_response(pair: OAuthProviderTokenPair) -> OAuthToken:
    return OAuthToken(
        access_token=pair.access_token,
        token_type="Bearer",
        expires_in=max(0, int(pair.expires_at.timestamp() - time.time())),
        refresh_token=pair.refresh_token,
        scope=" ".join(pair.scopes),
    )


class OnyxOAuthProvider(OAuthProvider):
    def __init__(
        self,
        settings: OAuthProviderSettings,
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
            return await run_in_threadpool(get_oauth_provider_client, client_id)
        try:
            validate_oauth_url(client_id, allow_query=True)
            document = await _cimd_fetcher(client_id).fetch(client_id)
            if str(document.client_id) != client_id:
                return None
            client = OAuthClientInformationFull(
                client_id=client_id,
                client_name=document.client_name or urlsplit(client_id).netloc,
                redirect_uris=[
                    AnyUrl(validate_oauth_url(uri, allow_query=True))
                    for uri in document.redirect_uris
                ],
                grant_types=document.grant_types,
                response_types=document.response_types,
                scope=document.scope or Permission.READ_SEARCH.value,
                token_endpoint_auth_method=document.token_endpoint_auth_method,
            )
            validate_public_oauth_client(client)
            return client
        except CIMDFetchError:
            raise OAuthClientMetadataUnavailable() from None
        except CIMDValidationError as error:
            cause = error.__cause__
            if (
                isinstance(cause, SSRFError)
                and isinstance(cause.__cause__, socket.gaierror)
                and cause.__cause__.errno in {socket.EAI_AGAIN, socket.EAI_FAIL}
            ):
                raise OAuthClientMetadataUnavailable() from error
            return None
        except ValueError:
            return None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        try:
            validate_public_oauth_client(client_info)
            await run_in_threadpool(register_oauth_provider_client, client_info)
        except ValueError as error:
            raise RegistrationError("invalid_client_metadata", str(error)) from error

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        try:
            resource = canonical_mcp_resource(params.resource or "", self.settings)
        except ValueError as error:
            raise AuthorizeError("invalid_request", "Invalid resource") from error
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
        request_id = await run_in_threadpool(
            store_authorization_request,
            PendingOAuthProviderAuthorization(
                client_id=client.client_id,
                client_name=client.client_name or "OAuth client",
                params=normalized,
            ),
        )
        return f"{self.settings.web_url}/oauth-provider/authorize?{urlencode({'request': request_id})}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> OAuthProviderAuthorizationCode | None:
        record = await run_in_threadpool(get_authorization_code, authorization_code)
        if (
            record is None
            or record.authorization.client_id != client.client_id
            or record.tenant_id != get_current_tenant_id()
        ):
            return None
        params = record.authorization.params
        return OAuthProviderAuthorizationCode(
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
        if not isinstance(authorization_code, OAuthProviderAuthorizationCode):
            raise TokenError("invalid_grant", "Invalid authorization code")
        record = await run_in_threadpool(
            consume_authorization_code, authorization_code.code
        )
        if (
            record is None
            or record.authorization.client_id != client.client_id
            or record.user_id != authorization_code.user_id
            or record.tenant_id != get_current_tenant_id()
            or record.authorization.params.resource != self.settings.mcp_resource_url
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
        client_id = client.client_id
        if not client_id:
            return None
        info = await run_in_threadpool(
            lambda: _with_authorized_refresh(
                load_oauth_provider_refresh__no_commit,
                refresh_token,
                client_id=client_id,
                resource=self.settings.mcp_resource_url,
            )
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
        client_id = client.client_id
        if not client_id or set(scopes) != {Permission.READ_SEARCH.value}:
            raise TokenError("invalid_scope", "Only read:search access is supported")
        pair = await run_in_threadpool(
            lambda: _with_authorized_refresh(
                rotate_oauth_provider_refresh__no_commit,
                refresh_token.token,
                client_id=client_id,
                resource=self.settings.mcp_resource_url,
            )
        )
        if pair is None:
            raise TokenError("invalid_grant", "Invalid or expired refresh token")
        return _token_response(pair)

    async def load_access_token(self, token: str) -> AccessToken | None:
        async with get_async_session_context_manager() as session:
            result = await resolve_oauth_provider_access_token(
                session, token, resource=self.settings.mcp_resource_url
            )
        if result is None:
            return None
        user, info = result
        owner = oauth_provider_owner_snapshot(user)
        if not await run_in_threadpool(
            oauth_provider_owner_is_member,
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
            resource=self.settings.mcp_resource_url,
        )
