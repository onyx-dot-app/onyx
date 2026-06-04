# /// script
# requires-python = ">=3.13"
# dependencies = [
#   "fastapi>=0.110",
#   "uvicorn>=0.29",
#   "pyjwt[crypto]>=2.8",
#   "cryptography>=42",
#   "python-multipart>=0.0.9",
# ]
# ///
"""Self-contained mock OIDC / OAuth2 authorization server for MCP e2e tests.

Run it with no external setup::

    uv run run_mock_oidc_idp.py 8090

It implements just enough of OAuth2 + OIDC discovery for the MCP SDK's
``OAuthClientProvider`` to complete an authorization-code + PKCE flow against a
fake identity, and issues RS256 JWT access tokens that the mock MCP server's
``JWTVerifier`` accepts (``iss`` / ``aud`` / ``scp`` with ``mcp:use``).

Why this exists: the real flow used a corporate Okta org, which meant secrets in
CI and a brittle hosted-login page in the browser tests. This server has **no
login page** — ``/authorize`` immediately redirects back with a code — so the
browser test just follows the redirect chain (no credentials to type, nothing
to mock). Tokens are signed by an in-memory RSA key whose public half is served
at ``/jwks``, so the whole loop is self-validating.

Env (all optional):
  MOCK_OIDC_PORT            bind/advertise port (default: argv[1] or 8090)
  MOCK_OIDC_BIND_HOST       bind host (default: 0.0.0.0)
  MOCK_OIDC_ISSUER          public issuer URL clients see
                            (default: http://<public_host>:<port>)
  MOCK_OIDC_PUBLIC_HOST     host used to build the default issuer
                            (default: host.docker.internal)
  MOCK_OIDC_AUDIENCE        token audience (default: api://mcp)
  MOCK_OIDC_SCOPE           scope granted into the token (default: mcp:use)
  MOCK_OIDC_SUBJECT         sub claim for the fake user (default: mock-user@example.com)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
import uuid
from typing import Any

import jwt
import uvicorn
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi import Form
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import RedirectResponse

KEY_ID = "mock-oidc-key-1"


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class MockOidc:
    """Holds signing key + in-flight authorization codes."""

    def __init__(self, *, issuer: str, audience: str, scope: str, subject: str) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.scope = scope
        self.subject = subject
        self._private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        self._private_pem = self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        # code -> {code_challenge, redirect_uri, scope}
        self._codes: dict[str, dict[str, str]] = {}

    # -- JWKS -----------------------------------------------------------------
    def jwks(self) -> dict[str, Any]:
        numbers = self._private_key.public_key().public_numbers()
        return {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": KEY_ID,
                    "n": _b64url_uint(numbers.n),
                    "e": _b64url_uint(numbers.e),
                }
            ]
        }

    # -- authorization codes --------------------------------------------------
    def issue_code(self, *, code_challenge: str, redirect_uri: str, scope: str) -> str:
        code = _b64url(os.urandom(24))
        self._codes[code] = {
            "code_challenge": code_challenge,
            "redirect_uri": redirect_uri,
            "scope": scope or self.scope,
        }
        return code

    def redeem_code(
        self, code: str, code_verifier: str, redirect_uri: str
    ) -> dict[str, str]:
        record = self._codes.pop(code, None)
        if record is None:
            raise ValueError("invalid_grant: unknown code")
        if record["redirect_uri"] != redirect_uri:
            raise ValueError("invalid_grant: redirect_uri mismatch")
        challenge = record["code_challenge"]
        if challenge:
            expected = _b64url(hashlib.sha256(code_verifier.encode("ascii")).digest())
            if expected != challenge:
                raise ValueError("invalid_grant: PKCE verification failed")
        return record

    # -- tokens ---------------------------------------------------------------
    def mint_access_token(self, *, scope: str, client_id: str) -> str:
        now = int(time.time())
        scopes = [s for s in scope.split(" ") if s] or [self.scope]
        claims = {
            "iss": self.issuer,
            "sub": self.subject,
            "aud": self.audience,
            "iat": now,
            "exp": now + 3600,
            "client_id": client_id,
            # Okta-style array scopes; JWTVerifier checks `scp`.
            "scp": scopes,
            # Space-delimited form too, for verifiers that read `scope`.
            "scope": " ".join(scopes),
        }
        return jwt.encode(
            claims,
            self._private_pem,
            algorithm="RS256",
            headers={"kid": KEY_ID},
        )


def build_app(oidc: MockOidc) -> FastAPI:
    app = FastAPI(title="Mock OIDC IdP for MCP tests")

    metadata = {
        "issuer": oidc.issuer,
        "authorization_endpoint": f"{oidc.issuer}/authorize",
        "token_endpoint": f"{oidc.issuer}/token",
        "jwks_uri": f"{oidc.issuer}/jwks",
        "registration_endpoint": f"{oidc.issuer}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": [
            "client_secret_post",
            "client_secret_basic",
            "none",
        ],
        "scopes_supported": [s for s in oidc.scope.split(" ") if s],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
    }

    @app.get("/.well-known/oauth-authorization-server")
    @app.get("/.well-known/openid-configuration")
    def discovery() -> JSONResponse:
        return JSONResponse(metadata)

    @app.get("/jwks")
    def jwks() -> JSONResponse:
        return JSONResponse(oidc.jwks())

    @app.get("/healthz")
    def healthz() -> PlainTextResponse:
        return PlainTextResponse("ok")

    @app.post("/register")
    async def register(request: Request) -> JSONResponse:
        """RFC 7591 dynamic client registration — accept anything, echo back."""
        body = await request.json()
        client_id = f"mock-client-{uuid.uuid4().hex[:12]}"
        return JSONResponse(
            {
                "client_id": client_id,
                "client_secret": _b64url(os.urandom(24)),
                "client_id_issued_at": int(time.time()),
                "client_secret_expires_at": 0,
                "redirect_uris": body.get("redirect_uris", []),
                "grant_types": body.get(
                    "grant_types", ["authorization_code", "refresh_token"]
                ),
                "response_types": body.get("response_types", ["code"]),
                "token_endpoint_auth_method": body.get(
                    "token_endpoint_auth_method", "client_secret_post"
                ),
            },
            status_code=201,
        )

    @app.get("/authorize")
    def authorize(
        redirect_uri: str,
        state: str = "",
        response_type: str = "code",  # noqa: ARG001 (accepted; only "code" supported)
        code_challenge: str = "",
        code_challenge_method: str = "S256",  # noqa: ARG001 (accepted; only S256)
        scope: str = "",
        client_id: str = "",  # noqa: ARG001 (accepted; mock issues to any client)
    ) -> RedirectResponse:
        """No login page: immediately issue a code and redirect back."""
        code = oidc.issue_code(
            code_challenge=code_challenge, redirect_uri=redirect_uri, scope=scope
        )
        sep = "&" if "?" in redirect_uri else "?"
        location = f"{redirect_uri}{sep}code={code}"
        if state:
            location += f"&state={state}"
        return RedirectResponse(location, status_code=302)

    @app.post("/token")
    def token(
        grant_type: str = Form(...),
        code: str = Form(""),
        redirect_uri: str = Form(""),
        code_verifier: str = Form(""),
        refresh_token: str = Form(""),  # noqa: ARG001 (accepted; mock doesn't track)
        client_id: str = Form(""),
        client_secret: str = Form(""),  # noqa: ARG001 (accepted; mock ignores secret)
        scope: str = Form(""),
    ) -> JSONResponse:
        try:
            if grant_type == "authorization_code":
                record = oidc.redeem_code(code, code_verifier, redirect_uri)
                granted_scope = record["scope"]
            elif grant_type == "refresh_token":
                granted_scope = scope or oidc.scope
            else:
                return JSONResponse(
                    {"error": "unsupported_grant_type"}, status_code=400
                )
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        access_token = oidc.mint_access_token(
            scope=granted_scope, client_id=client_id or "mock-client"
        )
        return JSONResponse(
            {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": 3600,
                "refresh_token": _b64url(os.urandom(24)),
                "scope": granted_scope,
            }
        )

    return app


def main() -> None:
    port = int(
        os.getenv("MOCK_OIDC_PORT", sys.argv[1] if len(sys.argv) > 1 else "8090")
    )
    bind_host = os.getenv("MOCK_OIDC_BIND_HOST", "0.0.0.0")
    public_host = os.getenv("MOCK_OIDC_PUBLIC_HOST", "host.docker.internal")
    issuer = os.getenv("MOCK_OIDC_ISSUER", f"http://{public_host}:{port}")
    audience = os.getenv("MOCK_OIDC_AUDIENCE", "api://mcp")
    scope = os.getenv("MOCK_OIDC_SCOPE", "mcp:use")
    subject = os.getenv("MOCK_OIDC_SUBJECT", "mock-user@example.com")

    oidc = MockOidc(issuer=issuer, audience=audience, scope=scope, subject=subject)
    app = build_app(oidc)

    print(f"[mock-oidc] issuer={issuer} audience={audience} scope={scope}")
    print(f"[mock-oidc] discovery: {issuer}/.well-known/oauth-authorization-server")
    print(f"[mock-oidc] jwks: {issuer}/jwks")
    print(json.dumps(oidc.jwks()))
    uvicorn.run(app, host=bind_host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
