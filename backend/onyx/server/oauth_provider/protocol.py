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

from onyx.auth.oauth_provider import (
    OAuthProviderTokenKind,
    parse_oauth_provider_code_tenant,
    parse_oauth_provider_token,
)
from onyx.db.enums import Permission
from onyx.db.oauth_provider import (
    OAUTH_PROVIDER_STORAGE_ERRORS,
    oauth_provider_tenant_has_members,
)
from onyx.oauth_provider.config import (
    canonical_mcp_resource,
    get_oauth_provider_settings,
)
from onyx.server.oauth_provider.provider import (
    AuthorizationClientSnapshot,
    OAuthClientMetadataUnavailable,
    OnyxOAuthProvider,
)
from onyx.utils.logger import setup_logger
from shared_configs.configs import POSTGRES_DEFAULT_SCHEMA
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

logger = setup_logger()

_MAX_BODY_BYTES = 16 * 1024
_MAX_FORM_FIELDS = 16
_PKCE_VERIFIER = re.compile(r"[A-Za-z0-9._~-]{43,128}")
NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, MCP-Protocol-Version",
}
_UNAVAILABLE_ERRORS = (
    *OAUTH_PROVIDER_STORAGE_ERRORS,
    RedisError,
    OAuthClientMetadataUnavailable,
)


def _oauth_error(
    error: str, description: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST
) -> JSONResponse:
    return JSONResponse(
        {"error": error, "error_description": description},
        status_code=status,
        headers={**NO_STORE_HEADERS, **_CORS},
    )


def _service_unavailable() -> JSONResponse:
    return _oauth_error(
        "server_error",
        "Authorization service unavailable",
        HTTPStatus.SERVICE_UNAVAILABLE,
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


def _no_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate client metadata fields are not allowed")
        result[key] = value
    return result


router = APIRouter(prefix="/oauth-provider")


@router.api_route("/metadata", methods=["GET", "OPTIONS"])
async def metadata(request: Request) -> Response:
    settings = get_oauth_provider_settings()
    if request.method == "OPTIONS":
        return Response(status_code=HTTPStatus.NO_CONTENT, headers=_CORS)
    issuer = settings.issuer_url
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


@router.api_route("/register", methods=["POST", "OPTIONS"])
async def register(request: Request) -> Response:
    settings = get_oauth_provider_settings()
    if request.method == "OPTIONS":
        return Response(status_code=HTTPStatus.NO_CONTENT, headers=_CORS)
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
        await OnyxOAuthProvider(settings).register_client(client)
    except RegistrationError as error:
        return _oauth_error(
            error.error, error.error_description or "Invalid client metadata"
        )
    except (ValueError, ValidationError):
        return _oauth_error("invalid_client_metadata", "Invalid client metadata")
    except _UNAVAILABLE_ERRORS:
        return _service_unavailable()
    return JSONResponse(
        client.model_dump(mode="json", exclude_none=True),
        status_code=HTTPStatus.CREATED,
        headers={**NO_STORE_HEADERS, **_CORS},
    )


@router.api_route("/authorize", methods=["GET", "POST"])
async def authorize(request: Request) -> Response:
    settings = get_oauth_provider_settings()
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
            response = await AuthorizationHandler(OnyxOAuthProvider(settings)).handle(
                prepared
            )
        else:
            client = await OnyxOAuthProvider(settings).get_client(
                authorization.client_id
            )
            provider = OnyxOAuthProvider(
                settings,
                authorization_client=AuthorizationClientSnapshot(
                    client_id=authorization.client_id, client=client
                ),
            )
            response = await AuthorizationHandler(provider).handle(prepared)
    except ValueError:
        return _oauth_error("invalid_request", "Invalid authorization parameters")
    except _UNAVAILABLE_ERRORS:
        return _service_unavailable()
    location = response.headers.get("location")
    if location and not location.startswith(
        f"{settings.web_url}/oauth-provider/authorize?"
    ):
        response.headers["location"] = construct_redirect_uri(
            location, iss=settings.issuer_url
        )
    response.headers.update(NO_STORE_HEADERS)
    return response


@router.api_route("/token", methods=["POST", "OPTIONS"])
async def token(request: Request) -> Response:
    settings = get_oauth_provider_settings()
    if request.method == "OPTIONS":
        return Response(status_code=HTTPStatus.NO_CONTENT, headers=_CORS)
    try:
        values = await _form(request)
        canonical_mcp_resource(values.get("resource", ""), settings)
        grant_type = values.get("grant_type")
        if grant_type == "authorization_code":
            if _PKCE_VERIFIER.fullmatch(values.get("code_verifier", "")) is None:
                return _oauth_error("invalid_request", "Invalid PKCE verifier")
            tenant_id = parse_oauth_provider_code_tenant(values.get("code", ""))
        elif grant_type == "refresh_token":
            parsed = parse_oauth_provider_token(values.get("refresh_token", ""))
            tenant_id = (
                parsed.tenant_id
                if parsed is not None and parsed.kind == OAuthProviderTokenKind.REFRESH
                else None
            )
        else:
            return _oauth_error("unsupported_grant_type", "Unsupported grant type")
        if tenant_id is None or not await run_in_threadpool(
            oauth_provider_tenant_has_members, tenant_id
        ):
            return _oauth_error("invalid_grant", "Invalid or expired grant")
        context_token = CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
        try:
            provider = OnyxOAuthProvider(settings)
            response = await TokenHandler(
                provider, ClientAuthenticator(provider)
            ).handle(_request_with_form(request, values))
            if response.status_code == HTTPStatus.UNAUTHORIZED:
                error = TokenErrorResponse.model_validate_json(response.body)
                if error.error == "invalid_grant":
                    response.status_code = HTTPStatus.BAD_REQUEST
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)
    except (ValueError, UnicodeError):
        return _oauth_error("invalid_request", "Invalid token parameters")
    except _UNAVAILABLE_ERRORS:
        logger.warning("OAuth provider token storage is unavailable")
        return _service_unavailable()
    response.headers.update({**NO_STORE_HEADERS, **_CORS})
    return response


@router.api_route("/revoke", methods=["POST", "OPTIONS"])
async def revoke(request: Request) -> Response:
    settings = get_oauth_provider_settings()
    if request.method == "OPTIONS":
        return Response(status_code=HTTPStatus.NO_CONTENT, headers=_CORS)
    try:
        values = await _form(request)
        if "resource" in values:
            canonical_mcp_resource(values["resource"], settings)
        parsed = parse_oauth_provider_token(values.get("token", ""))
        known = parsed is not None and await run_in_threadpool(
            oauth_provider_tenant_has_members, parsed.tenant_id
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
            provider = OnyxOAuthProvider(settings)
            response = await RevocationHandler(
                provider, ClientAuthenticator(provider)
            ).handle(_request_with_form(request, values))
        finally:
            CURRENT_TENANT_ID_CONTEXTVAR.reset(context_token)
    except (ValueError, UnicodeError):
        return _oauth_error("invalid_request", "Invalid revocation parameters")
    except _UNAVAILABLE_ERRORS:
        logger.warning("OAuth provider revocation storage is unavailable")
        return _service_unavailable()
    response.headers.update({**NO_STORE_HEADERS, **_CORS})
    return response
