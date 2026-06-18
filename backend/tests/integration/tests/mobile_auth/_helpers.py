"""Shared helpers for the mobile-auth integration tests."""

import httpx

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.http_client import client


def mobile_login(email: str, password: str) -> httpx.Response:
    # Form-encoded credentials, exactly like the web /auth/login.
    headers = GENERAL_HEADERS.copy()
    headers.pop("Content-Type", None)
    return client.post(
        url=f"{API_SERVER_URL}/auth/mobile/login",
        data={"username": email, "password": password},
        headers=headers,
    )


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
