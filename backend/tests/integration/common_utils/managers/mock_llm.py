from uuid import uuid4

import httpx

from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.models import (
    DefaultModel,
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestLLMProvider, DATestUser

# Must not contain a name Onyx special-cases (claude, qwen, glm, gpt-5.x, or
# any catalog model), which would change tool_choice and reasoning handling.
MOCK_LLM_MODEL_NAME = "mock-model"
# Deep Research needs at least 50000. Must differ from the catalog lookup,
# which the server does not store.
MOCK_LLM_MAX_INPUT_TOKENS = 200000
_MOCK_LLM_API_KEY = "sk-mock-llm-server"


class MockLLMManager:
    """LLM providers that point at the scripted mock LLM server."""

    @staticmethod
    def create(
        api_base: str,
        user_performing_action: DATestUser,
        model_name: str = MOCK_LLM_MODEL_NAME,
        name: str | None = None,
        max_input_tokens: int = MOCK_LLM_MAX_INPUT_TOKENS,
        set_as_default: bool = True,
    ) -> DATestLLMProvider:
        upsert_request = LLMProviderUpsertRequest(
            name=name or f"mock-llm-{uuid4()}",
            provider=LlmProviderNames.OPENAI_COMPATIBLE,
            api_key=_MOCK_LLM_API_KEY,
            api_base=api_base,
            api_version=None,
            custom_config=None,
            is_public=True,
            groups=[],
            personas=[],
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=model_name,
                    is_visible=True,
                    max_input_tokens=max_input_tokens,
                    display_name=model_name,
                    supports_image_input=False,
                )
            ],
            api_key_changed=True,
        )
        response = client.put(
            f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
            json=upsert_request.model_dump(),
            headers=user_performing_action.headers,
        )
        response.raise_for_status()
        data = response.json()

        if set_as_default:
            MockLLMManager.set_default(
                DefaultModel(provider_id=data["id"], model_name=model_name),
                user_performing_action,
            )

        return DATestLLMProvider(
            id=data["id"],
            name=data["name"],
            provider=data["provider"],
            api_key=data["api_key"],
            default_model_name=model_name,
            is_public=data["is_public"],
            is_auto_mode=data.get("is_auto_mode", False),
            groups=data["groups"],
            personas=data.get("personas", []),
            api_base=data["api_base"],
            api_version=data["api_version"],
            model_configuration_ids=[
                mc["id"]
                for mc in data.get("model_configurations", [])
                if mc.get("id") is not None
            ],
        )

    @staticmethod
    def set_default(default: DefaultModel, user_performing_action: DATestUser) -> None:
        response = client.post(
            f"{API_SERVER_URL}/admin/llm/default",
            json=default.model_dump(),
            headers=user_performing_action.headers,
        )
        response.raise_for_status()

    @staticmethod
    def delete(
        provider: DATestLLMProvider,
        previous_default: DefaultModel | None,
        user_performing_action: DATestUser,
    ) -> None:
        """Point the chat default back at `previous_default`, then delete the
        mock provider. When that is not possible (no previous default, or its
        provider is gone) the delete is forced, since the mock provider still
        holds the default."""
        restored = False
        if previous_default is not None:
            try:
                MockLLMManager.set_default(previous_default, user_performing_action)
                restored = True
            except httpx.HTTPStatusError:
                restored = False
        LLMProviderManager.delete(
            provider,
            user_performing_action=user_performing_action,
            force=not restored,
        )
