import argparse
import sys
import urllib.parse
from typing import Tuple

import requests


def _parse_state_from_redirect(redirect_url: str) -> str | None:
    try:
        parsed = urllib.parse.urlparse(redirect_url)
        query = urllib.parse.parse_qs(parsed.query)
        state_values = query.get("state")
        return state_values[0] if state_values else None
    except Exception:
        return None


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def set_linear_app_credentials(
    base_url: str,
    cookie: str,
    client_id: str,
    client_secret: str,
) -> None:
    url = f"{base_url}/api/manage/admin/connector/linear/app-credential"
    headers = {
        "Content-Type": "application/json",
        "Cookie": cookie,
    }
    resp = requests.put(
        url,
        headers=headers,
        json={"client_id": client_id, "client_secret": client_secret},
        timeout=10,
    )
    _assert(resp.ok, f"PUT {url} failed: {resp.status_code} {resp.text}")


def get_linear_app_credentials(base_url: str, cookie: str) -> dict:
    url = f"{base_url}/api/manage/admin/connector/linear/app-credential"
    headers = {"Cookie": cookie}
    resp = requests.get(url, headers=headers, timeout=10)
    _assert(resp.ok, f"GET {url} failed: {resp.status_code} {resp.text}")
    return resp.json()


def get_oauth_authorize_url(base_url: str, cookie: str) -> str:
    url = f"{base_url}/api/connector/oauth/authorize/linear"
    headers = {"Cookie": cookie}
    resp = requests.get(url, headers=headers, timeout=10)
    _assert(resp.ok, f"GET {url} failed: {resp.status_code} {resp.text}")
    data = resp.json()
    _assert("url" in data, "Missing url in response")
    return data["url"]


def run_flow(base_url: str, cookie: str, client_id: str, client_secret: str) -> None:
    # 1) Upsert credentials
    set_linear_app_credentials(base_url, cookie, client_id, client_secret)

    # 2) Verify they are readable (only client_id exposed)
    creds = get_linear_app_credentials(base_url, cookie)
    _assert(creds.get("client_id") == client_id, "client_id mismatch from GET")

    # 3) Request OAuth authorize URL
    redirect_url = get_oauth_authorize_url(base_url, cookie)

    # 4) Validate authorize URL contains client_id but not client_secret
    _assert("linear.app/oauth/authorize" in redirect_url, "Not a Linear authorize URL")
    _assert(
        f"client_id={urllib.parse.quote(client_id)}" in redirect_url,
        "client_id not present in authorize URL",
    )
    _assert(
        "client_secret" not in redirect_url, "client_secret leaked into authorize URL"
    )

    # 5) Print an URL with redacted state to avoid leaking sensitive data
    try:
        parsed = urllib.parse.urlparse(redirect_url)
        q = urllib.parse.parse_qs(parsed.query)
        if "state" in q:
            q["state"] = ["<redacted>"]
        safe_url = urllib.parse.urlunparse(
            parsed._replace(query=urllib.parse.urlencode(q, doseq=True))
        )
    except Exception:
        safe_url = "<redacted>"

    print("Authorize URL:", safe_url)


def parse_args() -> Tuple[str, str, str, str]:
    parser = argparse.ArgumentParser(
        description="Runtime E2E check for Linear OAuth configuration"
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080",
        help="Base URL of the running backend (e.g., http://127.0.0.1:8080)",
    )
    parser.add_argument(
        "--cookie",
        required=True,
        help="Session cookie string, e.g. 'session=....' of a logged-in admin user",
    )
    parser.add_argument("--client-id", required=True, help="Linear OAuth client_id")
    parser.add_argument(
        "--client-secret", required=True, help="Linear OAuth client_secret"
    )
    args = parser.parse_args()
    return args.base_url.rstrip("/"), args.cookie, args.client_id, args.client_secret


if __name__ == "__main__":
    try:
        base_url, cookie, client_id, client_secret = parse_args()
        run_flow(base_url, cookie, client_id, client_secret)
        print("SUCCESS: Runtime OAuth checks passed.")
    except Exception as e:
        print(f"FAILURE: {e}")
        sys.exit(1)
