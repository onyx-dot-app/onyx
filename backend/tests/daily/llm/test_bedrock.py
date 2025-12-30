import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from onyx.llm.constants import LlmProviderNames


_DEFAULT_BEDROCK_MODEL = "anthropic.claude-3-5-sonnet-20241022-v2:0"


@pytest.mark.xfail(
    reason="Credentials not yet available due to compliance work needed",
)
def test_bedrock_llm_configuration(client: TestClient) -> None:
    # Prepare the test request payload
    test_request: dict[str, Any] = {
        "provider": LlmProviderNames.BEDROCK,
        "default_model_name": _DEFAULT_BEDROCK_MODEL,
        "api_key": None,
        "api_base": None,
        "api_version": None,
        "custom_config": {
            "AWS_REGION_NAME": os.environ.get("AWS_REGION_NAME", "us-east-1"),
            "AWS_ACCESS_KEY_ID": os.environ.get("AWS_ACCESS_KEY_ID"),
            "AWS_SECRET_ACCESS_KEY": os.environ.get("AWS_SECRET_ACCESS_KEY"),
        },
    }

    # Send the test request
    response = client.post("/admin/llm/test", json=test_request)

    # Assert the response
    assert (
        response.status_code == 200
    ), f"Expected status code 200, but got {response.status_code}. Response: {response.text}"


def test_bedrock_llm_configuration_invalid_key(client: TestClient) -> None:
    # Prepare the test request payload with invalid credentials
    test_request: dict[str, Any] = {
        "provider": LlmProviderNames.BEDROCK,
        "default_model_name": _DEFAULT_BEDROCK_MODEL,
        "api_key": None,
        "api_base": None,
        "api_version": None,
        "custom_config": {
            "AWS_REGION_NAME": "us-east-1",
            "AWS_ACCESS_KEY_ID": "invalid_access_key_id",
            "AWS_SECRET_ACCESS_KEY": "invalid_secret_access_key",
        },
    }

    # Send the test request
    response = client.post("/admin/llm/test", json=test_request)

    # Assert the response
    assert (
        response.status_code == 400
    ), f"Expected status code 400, but got {response.status_code}. Response: {response.text}"
    assert (
        "Invalid credentials" in response.text
        or "Invalid Authentication" in response.text
    ), f"Expected error message about invalid credentials, but got: {response.text}"
