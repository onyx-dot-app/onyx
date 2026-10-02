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
from tests.integration.mock_services.mock_llm_server.models import (
    Conversation,
    RecordedRequest,
    Reply,
    RequestConditions,
    Script,
    ScriptState,
)

# Onyx special-cases some model names (claude, qwen, gpt-5.x, catalog models).
MOCK_LLM_MODEL_NAME = "mock-model"
# Deep Research needs at least 50000.
MOCK_LLM_MAX_INPUT_TOKENS = 200000


class MockLLMScript:
    """A test's view of one script on the mock LLM server."""

    def __init__(
        self, base_url: str, script_id: str, script: Script | None = None
    ) -> None:
        self._url = f"{base_url}/scripts/{script_id}"
        self.api_base = f"{self._url}/v1"
        self._client = httpx.Client()
        script_json = (script or Script()).model_dump(mode="json")
        self._client.put(self._url, json=script_json).raise_for_status()

    def conversation(
        self, name: str, *replies: Reply, conditions: RequestConditions | None = None
    ) -> None:
        conversation = Conversation(
            name=name,
            conditions=conditions or RequestConditions(),
            replies=list(replies),
        )
        response = self._client.post(
            f"{self._url}/conversations",
            json=conversation.model_dump(mode="json"),
        )
        response.raise_for_status()

    def _state(self) -> ScriptState:
        response = self._client.get(self._url)
        response.raise_for_status()
        return ScriptState.model_validate(response.json())

    @property
    def requests(self) -> list[RecordedRequest]:
        return self._state().requests

    def requests_in(self, name: str) -> list[RecordedRequest]:
        return [r for r in self.requests if r.conversation == name]

    def verify(self) -> None:
        """Fail on unmatched requests or unused required replies."""
        state = self._state()
        problems = [
            f"request {index} ({request.error}): tools={request.tools} "
            f"tool_choice={request.tool_choice} "
            f"tool_results={request.tool_result_ids()} "
            f"prompt_start={request.prompt_text[:300]!r}"
            for index, request in enumerate(state.requests)
            if request.error is not None
        ]
        problems.extend(f"unused {reply}" for reply in state.pending_required)
        if not problems:
            return
        default_replies = [
            f"request {index}: tools={request.tools} "
            f"prompt_start={request.prompt_text[:120]!r}"
            for index, request in enumerate(state.requests)
            if request.used_default_reply
        ]
        message = "mock LLM script was not followed:\n  " + "\n  ".join(problems)
        if default_replies:
            message += "\nserved by the default reply:\n  "
            message += "\n  ".join(default_replies)
        raise AssertionError(message)

    def close(self) -> None:
        try:
            self._client.delete(self._url)
        finally:
            self._client.close()


class MockLLMManager:
    """LLM providers that point at the mock LLM server."""

    @staticmethod
    def create(api_base: str, user_performing_action: DATestUser) -> DATestLLMProvider:
        upsert_request = LLMProviderUpsertRequest(
            name=f"mock-llm-{uuid4()}",
            provider=LlmProviderNames.OPENAI_COMPATIBLE,
            api_key="sk-mock-llm-server",
            api_base=api_base,
            api_version=None,
            custom_config=None,
            is_public=True,
            groups=[],
            personas=[],
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=MOCK_LLM_MODEL_NAME,
                    is_visible=True,
                    max_input_tokens=MOCK_LLM_MAX_INPUT_TOKENS,
                    display_name=MOCK_LLM_MODEL_NAME,
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
        provider = DATestLLMProvider(
            id=data["id"],
            name=data["name"],
            provider=data["provider"],
            api_key=data["api_key"],
            default_model_name=MOCK_LLM_MODEL_NAME,
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
        try:
            _set_default(
                DefaultModel(provider_id=provider.id, model_name=MOCK_LLM_MODEL_NAME),
                user_performing_action,
            )
        except Exception:
            LLMProviderManager.delete(
                provider, user_performing_action=user_performing_action
            )
            raise
        return provider

    @staticmethod
    def delete(
        provider: DATestLLMProvider,
        previous_default: DefaultModel | None,
        user_performing_action: DATestUser,
    ) -> None:
        """Restore `previous_default`, then delete the provider. With no previous
        default, the mock provider is the default, so the delete is forced."""
        if previous_default is not None:
            _set_default(previous_default, user_performing_action)
        LLMProviderManager.delete(
            provider,
            user_performing_action=user_performing_action,
            force=previous_default is None,
        )


def _set_default(default: DefaultModel, user_performing_action: DATestUser) -> None:
    response = client.post(
        f"{API_SERVER_URL}/admin/llm/default",
        json=default.model_dump(),
        headers=user_performing_action.headers,
    )
    response.raise_for_status()
