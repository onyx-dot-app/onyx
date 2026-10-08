import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

PROBE = (
    Path(__file__).resolve().parents[2] / ".github/scripts/check-mcp-compatibility.py"
)


@pytest.mark.parametrize("root_status,expected_exit", [(200, 0), (500, 1)])
@pytest.mark.parametrize("resource_suffix", ["", "/"])
@pytest.mark.parametrize("bare_status", [401, 200])
def test_deployed_probe_fails_on_legacy_discovery_regression(
    root_status: int, expected_exit: int, resource_suffix: str, bare_status: int
) -> None:
    class Backend(BaseHTTPRequestHandler):
        def respond(self, status: int, payload: dict[str, object]) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def do_GET(self) -> None:
            origin: str = f"http://127.0.0.1:{self.server.server_address[1]}"
            issuer: str = origin + "/api/oauth-provider"
            if self.path.startswith("/.well-known/oauth-authorization-server"):
                status: int = (
                    root_status
                    if self.path == "/.well-known/oauth-authorization-server"
                    else 200
                )
                self.respond(
                    status,
                    {
                        "issuer": issuer,
                        "authorization_endpoint": issuer + "/authorize",
                        "token_endpoint": issuer + "/token",
                        "registration_endpoint": issuer + "/register",
                        "token_endpoint_auth_methods_supported": ["none"],
                        "code_challenge_methods_supported": ["S256"],
                    },
                )
            elif self.path.startswith("/.well-known/oauth-protected-resource"):
                self.respond(
                    200,
                    {
                        "resource": origin + "/mcp" + resource_suffix,
                        "authorization_servers": [issuer],
                    },
                )
            else:
                self.respond(405, {})

        def do_POST(self) -> None:
            self.send_response(bare_status if self.path == "/mcp" else 401)
            self.send_header("Content-Type", "application/json")
            origin: str = f"http://127.0.0.1:{self.server.server_address[1]}"
            self.send_header(
                "WWW-Authenticate",
                f'Bearer resource_metadata="{origin}/.well-known/oauth-protected-resource/mcp"',
            )
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Backend)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(PROBE),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == (
            1 if resource_suffix or bare_status != 401 else expected_exit
        ), result.stderr
        if expected_exit:
            assert "expected metadata HTTP 200, got 500" in result.stderr
        elif resource_suffix:
            assert "resource or authorization server mismatch" in result.stderr
        elif bare_status != 401:
            assert "MCP initialize /mcp: expected JSON HTTP 401" in result.stderr
        else:
            assert "PASS unauthenticated MCP challenge" in result.stdout
            assert "PASS unauthenticated MCP challenge /mcp/" in result.stdout
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
