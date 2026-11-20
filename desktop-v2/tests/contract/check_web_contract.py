"""Contract check: the desktop shell and the Onyx server/web app agree.

The desktop app hard-codes routes, a cookie name and a deep link that the
backend and web app own. This check fails when one side changes them alone.

    # Source only (fast, no server): constants and routes in this checkout.
    python3 desktop-v2/tests/contract/check_web_contract.py
    # Also the live HTTP shapes the shell parses, against a running server.
    python3 desktop-v2/tests/contract/check_web_contract.py --server http://localhost:3000

The live part registers its own user unless --email and --password are given.
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SHELL = REPO / "desktop-v2" / "src-tauri" / "src"
Json = None | bool | int | float | str | list["Json"] | dict[str, "Json"]

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{'' if ok else f': {detail}'}")
    if not ok:
        failures.append(name)


def read(relative: str) -> str:
    return (REPO / relative).read_text()


def first(pattern: str, text: str) -> str | None:
    found = re.search(pattern, text)
    return found.group(1) if found else None


def shell_routes() -> set[str]:
    """Every `{server}/api/...` path the Rust shell requests."""
    routes: set[str] = set()
    for source in SHELL.glob("*.rs"):
        for path in re.findall(
            r'\{server\}(/api/[A-Za-z0-9_/\-{}]+)"', source.read_text()
        ):
            routes.add(re.sub(r"\{[a-z_]+\}", "{id}", path))
    return routes


def check_source() -> None:
    api = (SHELL / "api.rs").read_text()
    constants = read("backend/onyx/configs/constants.py")
    shell_cookie = first(r'DEFAULT_SESSION_COOKIE: &str = "([^"]+)"', api)
    backend_cookie = first(r'AUTH_COOKIE_NAME"\) or "([^"]+)"', constants)
    check(
        "default session cookie name",
        shell_cookie is not None and shell_cookie == backend_cookie,
        f"shell {shell_cookie!r}, backend {backend_cookie!r}",
    )
    check(
        "/api/auth/type reports auth_cookie_name",
        "auth_cookie_name" in read("backend/onyx/server/manage/models.py")
        and "auth_cookie_name" in api,
    )

    callback = first(r'CALLBACK: &str = "([^"]+)"', (SHELL / "sso.rs").read_text())
    web_callback = first(
        r'APP_SIGN_IN_CALLBACK = "([^"]+)"', read("web/src/lib/auth/appHandoff.ts")
    )
    backend_callbacks = first(
        r"_DEFAULT_MOBILE_REDIRECT_URIS = frozenset\(\{([^}]*)\}\)",
        read("backend/onyx/configs/app_configs.py"),
    )
    check(
        "sign-in deep link matches web and backend allowlist",
        callback is not None
        and callback == web_callback
        and backend_callbacks is not None
        and f'"{callback}"' in backend_callbacks,
        f"shell {callback!r}, web {web_callback!r}, backend {backend_callbacks!r}",
    )
    handoff = first(
        r'APP_SIGN_IN_HANDOFF_PATH = "([^"]+)"', read("web/src/lib/auth/appHandoff.ts")
    )
    check(
        "sign-in hand-off page exists",
        handoff is not None
        and (REPO / "web/src/app" / handoff.lstrip("/") / "page.tsx").exists(),
        f"path {handoff!r}",
    )

    # The backend mounts routers under these prefixes; the web proxy adds /api.
    main = read("backend/onyx/main.py")
    check("backend mounts /auth/mobile", 'prefix="/auth/mobile"' in main)
    expected = {
        "/api/version": (
            "backend/onyx/server/manage/get_state.py",
            '@router.get("/version"',
        ),
        "/api/me": ("backend/onyx/server/manage/users.py", '@router.get("/me"'),
        "/api/auth/mobile/sso/exchange": (
            "backend/onyx/server/auth/mobile.py",
            '"/sso/exchange"',
        ),
    }
    for route, (file, marker) in expected.items():
        check(
            f"backend serves {route}", marker in read(file), f"{marker} not in {file}"
        )
    used = shell_routes()
    for route in (
        "/api/version",
        "/api/me",
        "/api/auth/mobile/login",
        "/api/auth/type",
    ):
        check(
            f"shell still calls {route}", route in used, f"shell routes: {sorted(used)}"
        )


def request(
    server: str,
    method: str,
    path: str,
    *,
    form: dict[str, str] | None = None,
    body: Json = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    data: bytes | None = None
    all_headers = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        all_headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        all_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(  # noqa: S310 - the server under test
        f"{server}{path}", data=data, method=method, headers=all_headers
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:  # noqa: S310
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def parse(raw: bytes) -> dict[str, Json]:
    try:
        value = json.loads(raw)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def check_live(server: str, email: str | None, password: str | None) -> None:
    status, _, raw = request(server, "GET", "/api/version")
    version = parse(raw).get("backend_version")
    check(
        "GET /api/version has backend_version",
        status == 200 and isinstance(version, str),
        f"{status} {raw[:200]!r}",
    )

    status, _, raw = request(server, "GET", "/api/auth/type")
    auth = parse(raw)
    cookie = auth.get("auth_cookie_name") or "fastapiusersauth"
    check(
        "GET /api/auth/type has the fields the shell reads",
        status == 200
        and isinstance(auth.get("password_auth_enabled", True), bool)
        and isinstance(cookie, str),
        f"{status} {raw[:200]!r}",
    )

    status, _, raw = request(server, "GET", "/")
    check("GET / (web UI) answers", status < 500, f"{status}")
    status, _, raw = request(server, "GET", "/auth/app-handoff")
    check(
        "GET /auth/app-handoff serves the hand-off page",
        status == 200 and b"<html" in raw.lower(),
        f"{status}",
    )

    status, _, raw = request(
        server,
        "POST",
        "/api/auth/mobile/login",
        form={"username": "nobody@example.com", "password": "wrong"},
    )
    check(
        "a bad mobile login is a 4xx with a detail",
        400 <= status < 500 and status != 404 and "detail" in parse(raw),
        f"{status} {raw[:200]!r}",
    )

    if email is None or password is None:
        email = f"desktop-contract-{secrets.token_hex(4)}@example.com"
        password = f"Contract-{secrets.token_urlsafe(12)}!"
        status, _, raw = request(
            server,
            "POST",
            "/api/auth/register",
            body={"email": email, "password": password},
        )
        if status >= 300:
            check(
                "register a contract-test user",
                False,
                f"{status} {raw[:200]!r}; pass --email/--password",
            )
            return
    status, _, raw = request(
        server,
        "POST",
        "/api/auth/mobile/login",
        form={"username": email, "password": password},
    )
    token = parse(raw).get("access_token")
    check(
        "POST /api/auth/mobile/login returns access_token",
        status == 200 and isinstance(token, str),
        f"{status} {raw[:200]!r}",
    )
    if not isinstance(token, str):
        return

    def me(headers: dict[str, str]) -> Callable[[], tuple[int, Json]]:
        def call() -> tuple[int, Json]:
            code, _, body = request(server, "GET", "/api/me", headers=headers)
            return code, parse(body).get("email")

        return call

    # The shell checks the token as a bearer and hands it to the web UI as a cookie.
    for how, headers in (
        ("bearer", {"Authorization": f"Bearer {token}"}),
        (f"cookie {cookie}", {"Cookie": f"{cookie}={token}"}),
    ):
        code, who = me(headers)()
        check(
            f"GET /api/me with the token as {how}",
            code == 200 and who == email,
            f"{code} {who!r}",
        )

    status, _, raw = request(
        server,
        "POST",
        "/api/auth/mobile/refresh",
        headers={"Authorization": f"Bearer {token}"},
    )
    fresh = parse(raw).get("access_token")
    check(
        "POST /api/auth/mobile/refresh returns access_token",
        status == 200 and isinstance(fresh, str),
        f"{status} {raw[:200]!r}",
    )
    if isinstance(fresh, str):
        token = fresh
    status, _, _ = request(
        server,
        "POST",
        "/api/auth/mobile/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    check("POST /api/auth/mobile/logout succeeds", status < 300, f"{status}")
    code, _ = me({"Authorization": f"Bearer {token}"})()
    check("the token is revoked after logout", code == 401 or code == 403, f"{code}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--server", help="also check a live server, e.g. http://localhost:3000"
    )
    parser.add_argument("--email")
    parser.add_argument("--password")
    args = parser.parse_args()
    check_source()
    if args.server:
        check_live(args.server.rstrip("/"), args.email, args.password)
    print(f"{len(failures)} failed" if failures else "contract holds")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
