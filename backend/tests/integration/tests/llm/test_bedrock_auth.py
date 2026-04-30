"""Integration coverage for `/admin/llm/test` against AWS Bedrock.

The Onyx admin UI calls this endpoint when a user clicks "Test" on the
Bedrock provider page; if the credentials are wrong the UI surfaces the
response body verbatim. This test pins the contract:

- HTTP 400 when Bedrock rejects the credentials, AND
- the body contains "Authentication failed" so the UI's existing string
  match keeps working.
"""

import requests

from onyx.llm.constants import LlmProviderNames
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.user import UserManager

_BEDROCK_MODEL = "us.amazon.nova-2-lite-v1:0"


def test_bedrock_test_endpoint_rejects_invalid_credentials(
    reset: None,  # noqa: ARG001
) -> None:
    admin_user = UserManager.create(name="admin_user")

    response = requests.post(
        f"{API_SERVER_URL}/admin/llm/test",
        headers=admin_user.headers,
        json={
            "provider": LlmProviderNames.BEDROCK,
            "model": _BEDROCK_MODEL,
            "api_key": None,
            "api_base": None,
            "api_version": None,
            "custom_config": {
                "AWS_REGION_NAME": "us-east-1",
                "AWS_ACCESS_KEY_ID": "invalid_access_key_id",
                "AWS_SECRET_ACCESS_KEY": "invalid_secret_access_key",
            },
            "model_configurations": [{"name": _BEDROCK_MODEL, "is_visible": True}],
            "api_key_changed": True,
            "custom_config_changed": True,
        },
    )

    assert response.status_code == 400, (
        f"Expected status code 400, but got {response.status_code}. "
        f"Response: {response.text}"
    )
    assert "Authentication failed" in response.text, (
        f"Expected error message about invalid credentials, but got: "
        f"{response.text}"
    )
