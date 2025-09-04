import sys
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import Optional

import bcrypt
from fastmcp import FastMCP
from fastmcp.server.auth.auth import AccessToken
from fastmcp.server.auth.auth import TokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.server import FunctionTool

# pip install fastmcp bcrypt


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


# ---- server -----------------------------------------------------------------


def make_many_tools(mcp: FastMCP) -> list[FunctionTool]:
    def make_tool(i: int) -> FunctionTool:
        @mcp.tool(name=f"tool_{i}", description=f"Get secret value {i}")
        def tool_name(name: str) -> str:
            """Get secret value."""
            return f"Secret value {400 - i}!"

        return tool_name

    tools = []
    for i in range(100):
        tools.append(make_tool(i))
    return tools


if __name__ == "__main__":

    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    else:
        port = 8003

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
    mcp.run(transport="http", host="127.0.0.1", port=port, path="/mcp")
