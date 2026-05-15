import argparse
import sys
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import Optional

import bcrypt
import uvicorn
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastmcp import FastMCP
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.auth import TokenVerifier
from fastmcp.server.dependencies import get_access_token
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.responses import Response

# pip install fastmcp bcrypt fastapi uvicorn

DEFAULT_PORT = 8003
MCP_PATH_PREFIX = "/mcp"


# ---- pretend database --------------------------------------------------------
# Keys look like: "mcp_live_<key_id>_<secret>"
def _hash(secret: str) -> bytes:
    return bcrypt.hashpw(secret.encode(), bcrypt.gensalt(rounds=12))


API_KEY_RECORDS: Dict[str, Dict[str, Any]] = {
    # key_id -> record
    "kid_alice_001": {
        "user_id": "alice",
        "hashed_secret": _hash("S3cr3tAlice"),
        "scopes": ["mcp:use"],
        "revoked": False,
        "expires_at": None,  # or datetime(...)
        "metadata": {"plan": "pro"},
    },
    "kid_bob_001": {
        "user_id": "bob",
        "hashed_secret": _hash("S3cr3tBob"),
        "scopes": ["mcp:use"],
        "revoked": False,
        "expires_at": None,
        "metadata": {"plan": "free"},
    },
}

# These are inferrable from the file anyways, no need to obfuscate.
# use them to test your auth with this server
#
# mcp_live-kid_alice_001-S3cr3tAlice
# mcp_live-kid_bob_001-S3cr3tBob


# ---- verifier ---------------------------------------------------------------
class ApiKeyVerifier(TokenVerifier):
    """
    Accepts API keys in Authorization: Bearer mcp_live_<key_id>_<secret>
    Looks up <key_id> in storage, bcrypt-verifies <secret>, returns AccessToken.
    """

    def __init__(self, api_key_dict: dict[str, Any]):
        super().__init__()
        self.api_key_dict = api_key_dict

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        # print(f"Verifying token: {token}")
        try:
            prefix, key_id, secret = token.split("-")
            # print(f"Prefix: {prefix}, Key ID: {key_id}, Secret: {secret}")
            if prefix not in ("mcp_live", "mcp_test"):
                return None
        except ValueError:
            return None

        rec = self.api_key_dict.get(key_id)
        if not rec or rec.get("revoked"):
            return None
        if rec.get("expires_at") and rec["expires_at"] < datetime.now(timezone.utc):
            return None

        # constant-time bcrypt verification
        if not bcrypt.checkpw(secret.encode(), rec["hashed_secret"]):
            return None

        # Build an AccessToken with claims FastMCP can pass to your tools
        return AccessToken(
            token=token,
            client_id=rec["user_id"],
            scopes=rec.get("scopes", []),
            expires_at=rec.get("expires_at"),
            resource=None,
            claims={"key_id": key_id, **rec.get("metadata", {})},
        )


# ---- middleware -------------------------------------------------------------


class RequireHeadersMiddleware(BaseHTTPMiddleware):
    """Reject requests under ``MCP_PATH_PREFIX`` that omit any required header.

    Useful for testing the per-user MCP API-key flow in onyx where the admin
    templates extra headers (e.g. ``X-Username: {username}``) so each user is
    prompted for additional fields alongside their API key.

    The bearer token is still validated by ``ApiKeyVerifier`` after this
    middleware passes.
    """

    def __init__(self, app: Any, required_headers: list[str]) -> None:
        super().__init__(app)
        self.required_headers = required_headers

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if not request.url.path.startswith(MCP_PATH_PREFIX):
            return await call_next(request)

        for header in self.required_headers:
            if not request.headers.get(header):
                return JSONResponse(
                    {"error": f"Missing required header '{header}'"},
                    status_code=401,
                )
        return await call_next(request)


# ---- server -----------------------------------------------------------------


def make_many_tools(mcp: FastMCP) -> None:
    def make_tool(i: int) -> None:
        @mcp.tool(name=f"tool_{i}", description=f"Get secret value {i}")
        def tool_name(name: str) -> str:  # noqa: ARG001
            """Get secret value."""
            return f"Secret value {400 - i}!"

    for i in range(100):
        make_tool(i)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a local MCP server with per-user API key auth.",
    )
    parser.add_argument(
        "port",
        nargs="?",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on (default: {DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--require-header",
        action="append",
        default=None,
        metavar="NAME",
        help=(
            "Header name (e.g. X-Username) that must be present and non-empty "
            "on every /mcp request. Repeat the flag to require multiple "
            "headers. When unset, only the bearer token is required."
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = parse_args(sys.argv[1:])
    required_headers: list[str] = args.require_header or []

    mcp = FastMCP("My HTTP MCP", auth=ApiKeyVerifier(API_KEY_RECORDS))

    @mcp.tool
    def whoami() -> dict:
        """Return authenticated identity info (for demo)."""
        # FastMCP exposes the verified AccessToken to tools; see docs for helpers
        tok = get_access_token()
        return {
            "user": tok.client_id if tok else None,
            "scopes": tok.scopes if tok else [],
        }

    make_many_tools(mcp)

    mcp_app = mcp.http_app()
    app = FastAPI(
        title="MCP Per-User API Key Test Server",
        lifespan=mcp_app.lifespan,
    )

    @app.get("/healthz")
    def health() -> PlainTextResponse:
        return PlainTextResponse("ok")

    if required_headers:
        app.add_middleware(
            RequireHeadersMiddleware,
            required_headers=required_headers,
        )
        print(f"Requiring headers on {MCP_PATH_PREFIX}: {required_headers}")

    app.mount("/", mcp_app)
    # Bind on 0.0.0.0 so the server is reachable both via 127.0.0.1 for local
    # manual testing and from sibling containers via host.docker.internal in
    # the playwright CI compose stack. Matches run_mcp_server_api_key.py.
    uvicorn.run(app, host="0.0.0.0", port=args.port)
