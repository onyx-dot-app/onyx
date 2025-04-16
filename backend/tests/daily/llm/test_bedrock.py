import os
from typing import Any

import pytest
from fastapi.testclient import TestClient

from onyx.llm.llm_provider_options import BEDROCK_PROVIDER_NAME
from onyx.llm.llm_provider_options import fetch_available_well_known_llms
from onyx.llm.llm_provider_options import WellKnownLLMProviderDescriptor


@pytest.fixture
def bedrock_provider() -> WellKnownLLMProviderDescriptor:
    provider = next(
        (
            provider
            for provider in fetch_available_well_known_llms()
            if provider.name == BEDROCK_PROVIDER_NAME
        ),
        None,
    )
    assert provider is not None, "Bedrock provider not found"
    return provider


@pytest.mark.xfail(
    reason="Credentials not yet available due to compliance work needed",
)
def test_bedrock_llm_configuration(
    client: TestClient, bedrock_provider: WellKnownLLMProviderDescriptor
) -> None:
    # Prepare the test request payload
    test_request: dict[str, Any] = {
        "provider": BEDROCK_PROVIDER_NAME,
        "default_model_name": bedrock_provider.default_model,
        "fast_default_model_name": bedrock_provider.default_fast_model,
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


@pytest.mark.xfail(
    reason=(
        "Now broken due to db_session dependency injection on the route and "
        "a change that requires manual sql engine init."
    ),
)
def test_bedrock_llm_configuration_invalid_key(
    client: TestClient, bedrock_provider: WellKnownLLMProviderDescriptor
) -> None:
    # Prepare the test request payload with invalid credentials
    test_request: dict[str, Any] = {
        "provider": BEDROCK_PROVIDER_NAME,
        "default_model_name": bedrock_provider.default_model,
        "fast_default_model_name": bedrock_provider.default_fast_model,
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
