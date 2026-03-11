import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS


class ScimClient:
    """HTTP client for making authenticated SCIM v2 requests."""

    @staticmethod
    def _headers(raw_token: str) -> dict[str, str]:
        return {
            **GENERAL_HEADERS,
            "Authorization": f"Bearer {raw_token}",
        }

    @staticmethod
    def get(path: str, raw_token: str) -> requests.Response:
        return requests.get(
            f"{API_SERVER_URL}/scim/v2{path}",
            headers=ScimClient._headers(raw_token),
            timeout=60,
        )

    @staticmethod
    def post(path: str, raw_token: str, json: dict) -> requests.Response:
        return requests.post(
            f"{API_SERVER_URL}/scim/v2{path}",
            json=json,
            headers=ScimClient._headers(raw_token),
            timeout=60,
        )

    @staticmethod
    def put(path: str, raw_token: str, json: dict) -> requests.Response:
        return requests.put(
            f"{API_SERVER_URL}/scim/v2{path}",
            json=json,
            headers=ScimClient._headers(raw_token),
            timeout=60,
        )

    @staticmethod
    def patch(path: str, raw_token: str, json: dict) -> requests.Response:
        return requests.patch(
            f"{API_SERVER_URL}/scim/v2{path}",
            json=json,
            headers=ScimClient._headers(raw_token),
            timeout=60,
        )

    @staticmethod
    def delete(path: str, raw_token: str) -> requests.Response:
        return requests.delete(
            f"{API_SERVER_URL}/scim/v2{path}",
            headers=ScimClient._headers(raw_token),
            timeout=60,
        )

    @staticmethod
    def get_no_auth(path: str) -> requests.Response:
        return requests.get(
            f"{API_SERVER_URL}/scim/v2{path}",
            headers=GENERAL_HEADERS,
            timeout=60,
        )
