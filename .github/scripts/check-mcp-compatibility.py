"""Check public MCP discovery and routing without creating users or grants."""

import argparse
import json
import re
import sys
from http.client import HTTPConnection, HTTPException, HTTPSConnection
from typing import cast
from urllib.parse import urlsplit


def request(url: str, data: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    split = urlsplit(url)
    if split.scheme not in {"http", "https"} or split.hostname is None:
        raise ValueError("Only HTTP(S) probe requests are supported")
    connection: HTTPConnection = (
        HTTPSConnection(split.hostname, split.port, timeout=15)
        if split.scheme == "https"
        else HTTPConnection(split.hostname, split.port, timeout=15)
    )
    headers: dict[str, str] = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    try:
        path: str = split.path or "/"
        if split.query:
            path += "?" + split.query
        connection.request(
            "POST" if data is not None else "GET", path, body=data, headers=headers
        )
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read(1_000_000)
    finally:
        connection.close()


def metadata(url: str) -> dict[str, object]:
    status, _, body = request(url)
    if status != 200:
        raise ValueError(f"{url}: expected metadata HTTP 200, got {status}")
    payload: object = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError(f"{url}: metadata is not a JSON object")
    return cast(dict[str, object], payload)


def check(base_url: str) -> None:
    origin: str = base_url.rstrip("/")
    split = urlsplit(origin)
    if (
        split.scheme not in {"http", "https"}
        or not split.hostname
        or split.path
        or split.username
        or split.password
        or split.query
        or split.fragment
    ):
        raise ValueError(
            "base-url must be an HTTP(S) origin without credentials or a path"
        )
    issuer: str = origin + "/api/oauth-provider"
    for suffix in ("", "/mcp", "/api/oauth-provider"):
        url: str = origin + "/.well-known/oauth-authorization-server" + suffix
        document = metadata(url)
        if document.get("issuer") != issuer:
            raise ValueError(f"{url}: unexpected issuer")
        for field, endpoint in (
            ("authorization_endpoint", "/authorize"),
            ("token_endpoint", "/token"),
            ("registration_endpoint", "/register"),
        ):
            if document.get(field) != issuer + endpoint:
                raise ValueError(f"{url}: unexpected {field}")
        for field, value in (
            ("token_endpoint_auth_methods_supported", "none"),
            ("code_challenge_methods_supported", "S256"),
        ):
            supported = document.get(field)
            if not isinstance(supported, list) or value not in supported:
                raise ValueError(f"{url}: missing {field}={value}")
        print(f"PASS authorization discovery {suffix or '/'}")
    for suffix in ("/mcp", "/mcp/"):
        url = origin + "/.well-known/oauth-protected-resource" + suffix
        document = metadata(url)
        if document.get("resource") != origin + "/mcp" or document.get(
            "authorization_servers"
        ) != [issuer]:
            raise ValueError(f"{url}: resource or authorization server mismatch")
        print(f"PASS protected-resource discovery {suffix}")
    initialize = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "onyx-compatibility-check", "version": "1"},
            },
        }
    ).encode()
    for suffix in ("/mcp", "/mcp/"):
        status, headers, _ = request(origin + suffix, initialize)
        challenge: str = next(
            (
                value
                for key, value in headers.items()
                if key.lower() == "www-authenticate"
            ),
            "",
        )
        match = re.search(r'resource_metadata="([^"]+)"', challenge)
        if (
            status != 401
            or match is None
            or match.group(1) != origin + "/.well-known/oauth-protected-resource/mcp"
            or not any(
                key.lower() == "content-type" and value.startswith("application/json")
                for key, value in headers.items()
            )
        ):
            raise ValueError(
                f"MCP initialize {suffix}: expected JSON HTTP 401 with resource discovery, got {status}"
            )
        discovered = metadata(match.group(1))
        if discovered.get("resource") != origin + "/mcp":
            raise ValueError(
                f"MCP initialize {suffix}: incompatible protected resource"
            )
        print(f"PASS unauthenticated MCP challenge {suffix}")
    for endpoint in ("register", "token"):
        status, _, _ = request(issuer + "/" + endpoint)
        if status != 405:
            raise ValueError(f"OAuth {endpoint}: expected GET HTTP 405, got {status}")
        print(f"PASS OAuth {endpoint} routing")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    try:
        check(args.base_url)
    except (ValueError, OSError, HTTPException) as error:
        print(f"MCP compatibility failure: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
