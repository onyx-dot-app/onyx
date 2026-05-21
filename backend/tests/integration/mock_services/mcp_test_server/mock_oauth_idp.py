#!/usr/bin/env python3
"""Minimal local OAuth2 authorization server for MCP dev testing.

No Okta/Google required. Issues JWT access tokens validated by run_mcp_server_oauth.py
and supports PKCE (S256) for Onyx proactive OAuth connect.

Usage:
  python mock_oauth_idp.py [port]

Defaults: 127.0.0.1:8765

Onyx Admin (OAuth MCP servers using this IdP):
  Client ID:     onyx-mcp-dev
  Client secret: onyx-mcp-dev-secret
  Redirect URI must include: http://localhost:3000/mcp/oauth/callback
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from urllib.parse import urlencode

import jwt
import uvicorn
from cryptography.hazmat.primitives.asymmetric import rsa
from dev_oauth_constants import DEV_OAUTH_AUDIENCE
from dev_oauth_constants import DEV_OAUTH_CLIENT_ID
from dev_oauth_constants import DEV_OAUTH_CLIENT_SECRET
from dev_oauth_constants import DEV_OAUTH_REDIRECT_URI
from dev_oauth_constants import DEV_OAUTH_SCOPE
from fastapi import FastAPI
from fastapi import Form
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse

_CODE_TTL_SECONDS = 300


@dataclass
class _PendingCode:
    client_id: str
    redirect_uri: str
    code_challenge: str
    code_challenge_method: str
    scope: str
    expires_at: float


def _generate_rsa_keypair() -> tuple[Any, Any]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    return private_key, public_key


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, byteorder="big")
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _public_jwks(public_key: Any) -> dict[str, object]:
    numbers = public_key.public_numbers()
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "onyx-mcp-dev",
                "n": _b64url_uint(numbers.n),
                "e": _b64url_uint(numbers.e),
            }
        ]
    }


def _issuer_base(request: Request) -> str:
    configured = request.app.state.issuer
    if configured:
        return str(configured).rstrip("/")
    return str(request.base_url).rstrip("/")


def create_app(*, issuer: str | None = None) -> FastAPI:
    private_key, public_key = _generate_rsa_keypair()
    pending_codes: dict[str, _PendingCode] = {}

    app = FastAPI(title="Onyx MCP Dev OAuth IdP")
    app.state.issuer = issuer
    app.state.private_key = private_key
    app.state.public_key = public_key
    app.state.pending_codes = pending_codes

    def _discovery(issuer_url: str) -> dict[str, object]:
        return {
            "issuer": issuer_url,
            "authorization_endpoint": f"{issuer_url}/authorize",
            "token_endpoint": f"{issuer_url}/token",
            "jwks_uri": f"{issuer_url}/jwks",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": [DEV_OAUTH_SCOPE],
        }

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/.well-known/oauth-authorization-server")
    @app.get("/.well-known/openid-configuration")
    def authorization_server_metadata(request: Request) -> JSONResponse:
        return JSONResponse(_discovery(_issuer_base(request)))

    @app.get("/jwks")
    def jwks() -> JSONResponse:
        return JSONResponse(_public_jwks(app.state.public_key))

    @app.get("/authorize", response_model=None)
    def authorize(
        response_type: str,
        client_id: str,
        redirect_uri: str,
        state: str,
        code_challenge: str,
        code_challenge_method: str = "S256",
        scope: str = DEV_OAUTH_SCOPE,
    ) -> RedirectResponse | HTMLResponse:
        if response_type != "code":
            return HTMLResponse("Unsupported response_type", status_code=400)
        if client_id != DEV_OAUTH_CLIENT_ID:
            return HTMLResponse("Unknown client_id", status_code=400)
        if redirect_uri != DEV_OAUTH_REDIRECT_URI:
            return HTMLResponse(
                f"redirect_uri must be {DEV_OAUTH_REDIRECT_URI}",
                status_code=400,
            )
        if code_challenge_method != "S256":
            return HTMLResponse("Only S256 PKCE is supported", status_code=400)

        code = secrets.token_urlsafe(32)
        app.state.pending_codes[code] = _PendingCode(
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scope=scope,
            expires_at=time.time() + _CODE_TTL_SECONDS,
        )

        # Dev UX: auto-approve (no login UI).
        params = {"code": code, "state": state}
        return RedirectResponse(f"{redirect_uri}?{urlencode(params)}", status_code=302)

    @app.post("/token")
    async def token(
        request: Request,
        grant_type: str = Form(...),
        code: str | None = Form(None),
        redirect_uri: str | None = Form(None),
        client_id: str | None = Form(None),
        client_secret: str | None = Form(None),
        code_verifier: str | None = Form(None),
        refresh_token: str | None = Form(None),  # noqa: ARG001
    ) -> JSONResponse:
        if grant_type == "refresh_token":
            return JSONResponse(
                {"error": "unsupported_grant_type", "error_description": "refresh not implemented"},
                status_code=400,
            )

        if grant_type != "authorization_code":
            return JSONResponse(
                {"error": "unsupported_grant_type"},
                status_code=400,
            )

        if client_id != DEV_OAUTH_CLIENT_ID or client_secret != DEV_OAUTH_CLIENT_SECRET:
            return JSONResponse({"error": "invalid_client"}, status_code=401)

        pending = app.state.pending_codes.pop(code or "", None)
        if pending is None or pending.expires_at < time.time():
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        if redirect_uri != pending.redirect_uri:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        if not code_verifier:
            return JSONResponse({"error": "invalid_request"}, status_code=400)

        digest = hashlib.sha256(code_verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        if challenge != pending.code_challenge:
            return JSONResponse({"error": "invalid_grant"}, status_code=400)

        now = datetime.now(timezone.utc)
        issuer_url = _issuer_base(request)
        access_token = jwt.encode(
            {
                "iss": issuer_url,
                "aud": DEV_OAUTH_AUDIENCE,
                "sub": "onyx-mcp-dev-user",
                "client_id": DEV_OAUTH_CLIENT_ID,
                "scp": pending.scope,
                "scope": pending.scope,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(hours=1)).timestamp()),
            },
            app.state.private_key,
            algorithm="RS256",
            headers={"kid": "onyx-mcp-dev"},
        )

        return JSONResponse(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": pending.scope,
            }
        )

    return app


def main() -> None:
    port = int(sys.argv[1] if len(sys.argv) > 1 else "8765")
    host = "127.0.0.1"
    issuer = f"http://{host}:{port}"
    app = create_app(issuer=issuer)
    print(f"Dev OAuth IdP listening on {issuer}")
    print(f"  client_id={DEV_OAUTH_CLIENT_ID}")
    print(f"  client_secret={DEV_OAUTH_CLIENT_SECRET}")
    print(f"  redirect_uri={DEV_OAUTH_REDIRECT_URI}")
    print(f"  audience={DEV_OAUTH_AUDIENCE}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
