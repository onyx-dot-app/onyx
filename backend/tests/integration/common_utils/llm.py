import os
from uuid import uuid4

import requests

from danswer.server.manage.llm.models import LLMProviderUpsertRequest
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import TestLLMProvider
from tests.integration.common_utils.test_models import TestUser


class LLMProviderManager:
    @staticmethod
    def create(
        name: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        default_model_name: str | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
        groups: list[int] | None = None,
        is_public: bool | None = None,
        user_performing_action: TestUser | None = None,
    ) -> TestLLMProvider:
        print("Seeding LLM Providers...")

        llm_provider = LLMProviderUpsertRequest(
            name=name or f"test-provider-{uuid4()}",
            provider=provider or "openai",
            default_model_name=default_model_name or "gpt-4o-mini",
            api_key=api_key or os.environ["OPENAI_API_KEY"],
            api_base=api_base,
            api_version=api_version,
            custom_config=None,
            fast_default_model_name=default_model_name or "gpt-4o-mini",
            is_public=is_public or True,
            groups=groups or [],
            display_model_names=None,
            model_names=None,
        )

        llm_response = requests.put(
            f"{API_SERVER_URL}/admin/llm/provider",
            json=llm_provider.model_dump(),
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        llm_response.raise_for_status()
        response_data = llm_response.json()
        result_llm = TestLLMProvider(
            id=response_data["id"],
            name=response_data["name"],
            provider=response_data["provider"],
            api_key=response_data["api_key"],
            default_model_name=response_data["default_model_name"],
            is_public=response_data["is_public"],
            groups=response_data["groups"],
            api_base=response_data["api_base"],
            api_version=response_data["api_version"],
        )

        set_default_response = requests.post(
            f"{API_SERVER_URL}/admin/llm/provider/{llm_response.json()['id']}/default",
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        set_default_response.raise_for_status()

        return result_llm

    @staticmethod
    def delete(
        llm_provider: TestLLMProvider,
        user_performing_action: TestUser | None = None,
    ) -> bool:
        if not llm_provider.id:
            raise ValueError("LLM Provider ID is required to delete a provider")
        response = requests.delete(
            f"{API_SERVER_URL}/admin/llm/provider/{llm_provider.id}",
            headers=user_performing_action.headers
            if user_performing_action
            else GENERAL_HEADERS,
        )
        response.raise_for_status()
        return True
