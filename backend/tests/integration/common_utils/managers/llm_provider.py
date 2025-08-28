import os
from uuid import uuid4

import requests

from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import LLMProviderView
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.constants import GENERAL_HEADERS
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser


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
        user_performing_action: DATestUser | None = None,
    ) -> DATestLLMProvider:
        email = "Unknown"
        if user_performing_action:
            email = user_performing_action.email

        print(f"Seeding LLM Providers for {email}...")

        llm_provider = LLMProviderUpsertRequest(
            name=name or f"test-provider-{uuid4()}",
            provider=provider or "openai",
            default_model_name=default_model_name or "gpt-4o",
            api_key=api_key or os.environ["OPENAI_API_KEY"],
            api_base=api_base,
            api_version=api_version,
            custom_config=None,
            fast_default_model_name=default_model_name or "gpt-4o-mini",
            is_public=is_public or True,
            groups=groups or [],
            model_configurations=[],
            api_key_changed=True,
        )

        llm_response = requests.put(
            f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
            json=llm_provider.model_dump(),
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        llm_response.raise_for_status()
        response_data = llm_response.json()

        result_llm = DATestLLMProvider(
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
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        set_default_response.raise_for_status()

        return result_llm

    @staticmethod
    def delete(
        llm_provider: DATestLLMProvider,
        user_performing_action: DATestUser | None = None,
    ) -> bool:
        response = requests.delete(
            f"{API_SERVER_URL}/admin/llm/provider/{llm_provider.id}",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return True

    @staticmethod
    def get_all(
        user_performing_action: DATestUser | None = None,
    ) -> list[LLMProviderView]:
        response = requests.get(
            f"{API_SERVER_URL}/admin/llm/provider",
            headers=(
                user_performing_action.headers
                if user_performing_action
                else GENERAL_HEADERS
            ),
        )
        response.raise_for_status()
        return [LLMProviderView(**ug) for ug in response.json()]

    @staticmethod
    def verify(
        llm_provider: DATestLLMProvider,
        verify_deleted: bool = False,
        user_performing_action: DATestUser | None = None,
    ) -> None:
        all_llm_providers = LLMProviderManager.get_all(user_performing_action)
        for fetched_llm_provider in all_llm_providers:
            if llm_provider.id == fetched_llm_provider.id:
                if verify_deleted:
                    raise ValueError(
                        f"LLM Provider {llm_provider.id} found but should be deleted"
                    )
                fetched_llm_groups = set(fetched_llm_provider.groups)
                llm_provider_groups = set(llm_provider.groups)

                # NOTE: returned api keys are sanitized and should not match
                if (
                    fetched_llm_groups == llm_provider_groups
                    and llm_provider.provider == fetched_llm_provider.provider
                    and llm_provider.default_model_name
                    == fetched_llm_provider.default_model_name
                    and llm_provider.is_public == fetched_llm_provider.is_public
                ):
                    return
        if not verify_deleted:
            raise ValueError(f"LLM Provider {llm_provider.id} not found")
