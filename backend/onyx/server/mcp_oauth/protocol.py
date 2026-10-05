import ipaddress
import json
import re
import secrets
import time
from http import HTTPStatus
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Request
from fastmcp.server.auth.auth import TokenHandler
from mcp.server.auth.handlers.authorize import (
    AuthorizationHandler,
    AuthorizationRequest,
)
from mcp.server.auth.handlers.revoke import RevocationHandler
from mcp.server.auth.handlers.token import TokenErrorResponse
from mcp.server.auth.middleware.client_auth import ClientAuthenticator
from mcp.server.auth.provider import RegistrationError, construct_redirect_uri
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata
from pydantic import ValidationError
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, Response
from starlette.types import Message

from onyx.auth.oauth_provider import OAuthProviderTokenKind, parse_oauth_provider_token
from onyx.db.enums import Permission
from onyx.db.mcp_oauth import MCP_OAUTH_STORAGE_ERRORS, mcp_oauth_tenant_has_members
from onyx.mcp_oauth.attempts import allow_mcp_oauth_request, get_authorization_code
from onyx.mcp_oauth.config import MCPOAuthSettings, canonical_mcp_resource
from onyx.server.mcp_oauth.provider import (
    AuthorizationClientSnapshot,
    MCPClientMetadataUnavailable,
    OnyxMCPOAuthProvider,
)
from onyx.utils.client_ip import get_client_ip
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

_MAX_BODY_BYTES = 16 * 1024
_MAX_FORM_FIELDS = 16
_PKCE_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, MCP-Protocol-Version",
}


def _oauth_error(
    error: str, description: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST
) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers={**_NO_STORE, **_CORS},
    )


async def _read_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_BODY_BYTES:
            raise ValueError("OAuth request is too large")
        body.extend(chunk)
    return bytes(body)


def _request_with_form(request: Request, values: dict[str, str]) -> Request:
    body = urlencode(values).encode("utf-8")
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = dict(request.scope)
    scope["headers"] = [
        (key, value)
        for key, value in request.headers.raw
        if key.lower() != b"content-length"
    ] + [(b"content-length", str(len(body)).encode("ascii"))]
    return Request(scope, receive=receive)


async def _form(request: Request) -> dict[str, str]:
    if request.query_params:
        raise ValueError("OAuth POST parameters must be in the request body")
    if (
        request.headers.get("content-type", "").split(";", 1)[0].lower()
        != "application/x-www-form-urlencoded"
    ):
        raise ValueError("Expected an URL-encoded OAuth request")
    pairs = parse_qsl(
        (await _read_body(request)).decode("utf-8"),
        keep_blank_values=True,
        strict_parsing=True,
        max_num_fields=_MAX_FORM_FIELDS,
    )
    values = dict(pairs)
    if len(values) != len(pairs):
        raise ValueError("Duplicate OAuth parameters are not allowed")
    return values


async def _rate_limit(request: Request, operation: str) -> Response | None:
    if request.method == "OPTIONS":
        return Response(status_code=HTTPStatus.NO_CONTENT, headers=_CORS)
    peer = request.client.host if request.client is not None else "unknown"
    address = get_client_ip(request)
    if address is None:
        try:
            private_peer = ipaddress.ip_address(peer).is_private
        except ValueError:
            private_peer = False
        if private_peer:
            for hop in reversed(request.headers.get("x-forwarded-for", "").split(",")):
                try:
                    address = str(ipaddress.ip_address(hop.strip()))
                except ValueError:
                    continue
                break
    address = address or peer
    per_minute = 300 if operation == "register" else 3000
    try:
        allowed = await allow_mcp_oauth_request(
            f"{operation}:ip:{address}", limit=per_minute, window_seconds=60
        ) and await allow_mcp_oauth_request(
            f"{operation}:global", limit=per_minute * 10, window_seconds=60
        )
    except RedisError:
        return _oauth_error(
            "server_error",
            "Authorization service unavailable",
            HTTPStatus.SERVICE_UNAVAILABLE,
        )
    if not allowed:
        response = _oauth_error(
            "temporarily_unavailable",
            "Too many OAuth requests",
            HTTPStatus.TOO_MANY_REQUESTS,
        )
        response.headers["Retry-After"] = "60"
        return response
    return None


def _no_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate client metadata fields are not allowed")
        result[key] = value
    return result


class MCPOAuthProtocol:
    def __init__(self, settings: MCPOAuthSettings) -> None:
        self.settings = settings
        self.provider = OnyxMCPOAuthProvider(settings)
        authenticator = ClientAuthenticator(self.provider)
        self.token_handler = TokenHandler(self.provider, authenticator)
        self.revoke_handler = RevocationHandler(self.provider, authenticator)
        self.authorize_handler = AuthorizationHandler(self.provider)

    async def metadata(self, request: Request) -> Response:
        if request.method == "OPTIONS":
            return Response(status_code=HTTPStatus.NO_CONTENT, headers=_CORS)
        issuer = self.settings.issuer_url
        return JSONResponse(
            {
                "issuer": issuer,
                "authorization_endpoint": f"{issuer}/authorize",
                "token_endpoint": f"{issuer}/token",
                "registration_endpoint": f"{issuer}/register",
                "revocation_endpoint": f"{issuer}/revoke",
                "scopes_supported": [Permission.READ_SEARCH.value],
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "token_endpoint_auth_methods_supported": ["none"],
                "revocation_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "client_id_metadata_document_supported": True,
                "authorization_response_iss_parameter_supported": True,
            },
            headers={**_CORS, "Cache-Control": "public, max-age=300"},
        )

    async def register(self, request: Request) -> Response:
        if limited := await _rate_limit(request, "register"):
            return limited
        try:
            if (
                request.headers.get("content-type", "").split(";", 1)[0].lower()
                != "application/json"
            ):
                raise ValueError("Expected JSON client metadata")
            payload = json.loads(
                await _read_body(request), object_pairs_hook=_no_duplicate_json_keys
            )
            if not isinstance(payload, dict):
                raise ValueError("Expected a client metadata object")
            if "token_endpoint_auth_method" not in payload:
                payload["token_endpoint_auth_method"] = "none"
            if "scope" not in payload:
                payload["scope"] = Permission.READ_SEARCH.value
            client_metadata = OAuthClientMetadata.model_validate(payload)
            client = OAuthClientInformationFull(
                **client_metadata.model_dump(),
                client_id=secrets.token_urlsafe(32),
                client_id_issued_at=int(time.time()),
            )
            await self.provider.register_client(client)
        except RegistrationError as error:
            return _oauth_error(
                error.error, error.error_description or "Invalid client metadata"
            )
        except (ValueError, ValidationError):
            return _oauth_error("invalid_client_metadata", "Invalid client metadata")
        except (*MCP_OAUTH_STORAGE_ERRORS, RedisError, MCPClientMetadataUnavailable):
            return _oauth_error(
                "server_error",
                "Authorization service unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        return JSONResponse(
            client.model_dump(mode="json", exclude_none=True),
            status_code=HTTPStatus.CREATED,
            headers={**_NO_STORE, **_CORS},
        )

    async def authorize(self, request: Request) -> Response:
        if limited := await _rate_limit(request, "authorize"):
            return limited
        try:
            if request.method == "GET":
                if len(request.url.query.encode("utf-8")) > _MAX_BODY_BYTES:
                    raise ValueError("OAuth request is too large")
                values = dict(request.query_params)
                if (
                    len(values) != len(request.query_params.multi_items())
                    or len(values) > _MAX_FORM_FIELDS
                ):
                    raise ValueError("Duplicate or excessive OAuth parameters")
            else:
                values = await _form(request)
            values.setdefault("code_challenge_method", "plain")
            if request.method == "GET":
                scope = dict(request.scope)
                scope["query_string"] = urlencode(values).encode("utf-8")
                prepared = Request(scope)
            else:
                prepared = _request_with_form(request, values)
            try:
                authorization = AuthorizationRequest.model_validate(values)
            except ValidationError:
                response = await self.authorize_handler.handle(prepared)
            else:
                client = await self.provider.get_client(authorization.client_id)
                provider = OnyxMCPOAuthProvider(
                    self.settings,
                    authorization_client=AuthorizationClientSnapshot(
                        client_id=authorization.client_id, client=client
                    ),
                )
                response = await AuthorizationHandler(provider).handle(prepared)
        except ValueError:
            return _oauth_error("invalid_request", "Invalid authorization parameters")
        except (*MCP_OAUTH_STORAGE_ERRORS, RedisError, MCPClientMetadataUnavailable):
            return _oauth_error(
                "server_error",
                "Authorization service unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        location = response.headers.get("location")
        if location and not location.startswith(
            f"{self.settings.web_url}/oauth/mcp/authorize?"
        ):
            response.headers["location"] = construct_redirect_uri(
                location, iss=self.settings.issuer_url
            )
        response.headers.update(_NO_STORE)
        return response

    async def token(self, request: Request) -> Response:
        if limited := await _rate_limit(request, "token"):
            return limited
        try:
            values = await _form(request)
            canonical_mcp_resource(values.get("resource", ""), self.settings)
            grant_type = values.get("grant_type")
            if grant_type == "authorization_code":
                if _PKCE_VERIFIER.fullmatch(values.get("code_verifier", "")) is None:
                    return _oauth_error("invalid_request", "Invalid PKCE verifier")
                code = await get_authorization_code(values.get("code", ""))
                tenant_id = code.tenant_id if code is not None else None
            elif grant_type == "refresh_token":
                parsed = parse_oauth_provider_token(values.get("refresh_token", ""))
                tenant_id = (
                    parsed.tenant_id
                    if parsed is not None
                    and parsed.kind == OAuthProviderTokenKind.REFRESH
                    else None
                )
            else:
                return _oauth_error("unsupported_grant_type", "Unsupported grant type")
            if tenant_id is None or not await run_in_threadpool(
                mcp_oauth_tenant_has_members, tenant_id
            ):
                return _oauth_error("invalid_grant", "Invalid or expired grant")
            context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
            try:
                response = await self.token_handler.handle(
                    _request_with_form(request, values)
                )
                if response.status_code == HTTPStatus.UNAUTHORIZED:
                    error = TokenErrorResponse.model_validate_json(response.body)
                    if error.error == "invalid_grant":
                        response.status_code = HTTPStatus.BAD_REQUEST
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)
        except (ValueError, UnicodeError):
            return _oauth_error("invalid_request", "Invalid token parameters")
        except (*MCP_OAUTH_STORAGE_ERRORS, RedisError, MCPClientMetadataUnavailable):
            logger.warning("MCP OAuth token storage is unavailable")
            return _oauth_error(
                "server_error",
                "Authorization service unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        response.headers.update({**_NO_STORE, **_CORS})
        return response

    async def revoke(self, request: Request) -> Response:
        if limited := await _rate_limit(request, "revoke"):
            return limited
        try:
            values = await _form(request)
            if "resource" in values:
                canonical_mcp_resource(values["resource"], self.settings)
            parsed = parse_oauth_provider_token(values.get("token", ""))
            known = parsed is not None and await run_in_threadpool(
                mcp_oauth_tenant_has_members, parsed.tenant_id
            )
            tenant_id = (
                parsed.tenant_id
                if parsed is not None and known
                else POSTGRES_DEFAULT_SCHEMA
            )
            if not known:
                values["token"] = ""
            values.setdefault("client_secret", "")
            context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
            try:
                response = await self.revoke_handler.handle(
                    _request_with_form(request, values)
                )
            finally:
                CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)
        except (ValueError, UnicodeError):
            return _oauth_error("invalid_request", "Invalid revocation parameters")
        except (*MCP_OAUTH_STORAGE_ERRORS, RedisError, MCPClientMetadataUnavailable):
            logger.warning("MCP OAuth revocation storage is unavailable")
            return _oauth_error(
                "server_error",
                "Authorization service unavailable",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        response.headers.update({**_NO_STORE, **_CORS})
        return response


def create_mcp_oauth_protocol_router(settings: MCPOAuthSettings) -> APIRouter:
    router = APIRouter(prefix="/mcp-oauth")
    if not settings.enabled:
        return router
    endpoints = MCPOAuthProtocol(settings)
    router.add_api_route("/metadata", endpoints.metadata, methods=["GET", "OPTIONS"])
    router.add_api_route("/register", endpoints.register, methods=["POST", "OPTIONS"])
    router.add_api_route("/authorize", endpoints.authorize, methods=["GET", "POST"])
    router.add_api_route("/token", endpoints.token, methods=["POST", "OPTIONS"])
    router.add_api_route("/revoke", endpoints.revoke, methods=["POST", "OPTIONS"])
    return router
