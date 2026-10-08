from collections.abc import Mapping
from functools import partial
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from litellm.types.utils import ModelResponse as LiteLLMModelResponse
from pydantic import JsonValue

from onyx.chat.incognito import (
    BIFROST_DISABLE_CONTENT_LOGGING_HEADER,
    incognito_llm_extra_headers,
    incognito_llm_request_policy,
)
from onyx.db.enums import IncognitoRecordMode
from onyx.llm.constants import LlmProviderNames
from onyx.llm.factory import (
    _build_provider_extra_headers,
    get_default_llm,
    get_llm,
    get_llm_for_persona,
    llm_from_provider,
)
from onyx.llm.interfaces import LLMConfig, LlmRequestPolicy
from onyx.llm.models import GenerationRequest, UserMessage
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.well_known_providers.constants import (
    BIFROST_PROVIDER_NAME,
    LM_STUDIO_API_KEY_CONFIG_KEY,
)
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView


def test_build_provider_extra_headers_adds_bearer_for_lm_studio_api_key() -> None:
    headers = _build_provider_extra_headers(
        LlmProviderNames.LM_STUDIO,
        {LM_STUDIO_API_KEY_CONFIG_KEY: "  test-key  "},
    )

    assert headers == {"Authorization": "Bearer test-key"}


def test_build_provider_extra_headers_keeps_existing_bearer_prefix() -> None:
    headers = _build_provider_extra_headers(
        LlmProviderNames.LM_STUDIO,
        {LM_STUDIO_API_KEY_CONFIG_KEY: "bearer test-key"},
    )

    assert headers == {"Authorization": "bearer test-key"}


def test_build_provider_extra_headers_ignores_empty_lm_studio_api_key() -> None:
    headers = _build_provider_extra_headers(
        LlmProviderNames.LM_STUDIO,
        {LM_STUDIO_API_KEY_CONFIG_KEY: "   "},
    )

    assert headers == {}


def test_build_provider_extra_headers_ignores_legacy_ollama_custom_config() -> None:
    # Ollama now carries its key in the standard api_key field, which LiteLLM
    # turns into a Bearer header itself; custom_config must not add one.
    headers = _build_provider_extra_headers(
        LlmProviderNames.OLLAMA_CHAT,
        {"OLLAMA_API_KEY": "test-key"},
    )

    assert headers == {}


def _build_provider_view(
    provider: str,
    max_input_tokens: int | None,
) -> LLMProviderView:
    return LLMProviderView(
        id=1,
        name="test-provider",
        provider=provider,
        model_configurations=[
            ModelConfigurationView(
                name="test-model",
                is_visible=True,
                max_input_tokens=max_input_tokens,
                supports_image_input=False,
            )
        ],
        api_key=None,
        api_base="http://localhost:11434",
        api_version=None,
        custom_config=None,
        is_public=True,
        is_auto_mode=False,
        groups=[],
        personas=[],
        deployment_name=None,
    )


def test_get_llm_sets_ollama_num_ctx_model_kwarg() -> None:
    with patch("onyx.llm.factory.LitellmLLM") as mock_litellm_llm:
        model = get_llm(
            provider=LlmProviderNames.OLLAMA_CHAT,
            model="test-model",
            deployment_name=None,
            max_input_tokens=4096,
            model_kwargs={"num_ctx": 8192},
        )

        assert model is mock_litellm_llm.return_value
        kwargs = mock_litellm_llm.call_args.kwargs
        assert kwargs["model_kwargs"] == {"num_ctx": 8192}


def test_get_llm_does_not_set_ollama_num_ctx_for_non_ollama_provider() -> None:
    with patch("onyx.llm.factory.LitellmLLM") as mock_litellm_llm:
        get_llm(
            provider=LlmProviderNames.OPENAI,
            model="gpt-4o-mini",
            deployment_name=None,
            max_input_tokens=4096,
        )

        kwargs = mock_litellm_llm.call_args.kwargs
        assert kwargs["model_kwargs"] == {}


def test_llm_from_provider_passes_configured_ollama_num_ctx() -> None:
    provider = _build_provider_view(
        provider=LlmProviderNames.OLLAMA_CHAT,
        max_input_tokens=16384,
    )

    with patch("onyx.llm.factory.get_llm") as mock_get_llm:
        llm_from_provider(
            model_name="test-model",
            llm_provider=provider,
        )

        kwargs = mock_get_llm.call_args.kwargs
        assert kwargs["max_input_tokens"] == 16384
        assert kwargs["model_kwargs"] == {"num_ctx": 16384}


def test_llm_from_provider_omits_ollama_num_ctx_when_model_context_unknown() -> None:
    provider = _build_provider_view(
        provider=LlmProviderNames.OLLAMA_CHAT,
        max_input_tokens=None,
    )

    with (
        patch(
            "onyx.llm.factory.get_max_input_tokens_from_llm_provider",
            return_value=32000,
        ),
        patch("onyx.llm.factory.get_llm") as mock_get_llm,
    ):
        llm_from_provider(
            model_name="test-model",
            llm_provider=provider,
        )

        kwargs = mock_get_llm.call_args.kwargs
        assert kwargs["max_input_tokens"] == 32000
        assert kwargs["model_kwargs"] == {}


def test_llm_from_provider_never_sets_ollama_num_ctx_for_non_ollama_provider() -> None:
    provider = _build_provider_view(
        provider=LlmProviderNames.OPENAI,
        max_input_tokens=16384,
    )

    with patch("onyx.llm.factory.get_llm") as mock_get_llm:
        llm_from_provider(
            model_name="test-model",
            llm_provider=provider,
        )

        kwargs = mock_get_llm.call_args.kwargs
        assert kwargs["max_input_tokens"] == 16384
        assert kwargs["model_kwargs"] == {}


def test_get_llm_policy_headers_win_over_every_other_source() -> None:
    """Policy headers must be the final merge. The request and deployment-env
    sources set the same header to false here."""
    policy = incognito_llm_extra_headers(
        IncognitoRecordMode.USAGE_ONLY, BIFROST_PROVIDER_NAME
    )
    header = BIFROST_DISABLE_CONTENT_LOGGING_HEADER
    with (
        patch("onyx.llm.factory.LitellmLLM") as mock_litellm_llm,
        patch("onyx.utils.headers.LITELLM_EXTRA_HEADERS", {header: "false"}),
    ):
        get_llm(
            provider=BIFROST_PROVIDER_NAME,
            model="gpt-4o",
            deployment_name=None,
            max_input_tokens=4096,
            additional_headers={header: "false"},
            policy_headers=policy,
        )

        kwargs = mock_litellm_llm.call_args.kwargs
        assert kwargs["extra_headers"][header] == "true"


def test_get_llm_without_policy_headers_keeps_the_existing_merge() -> None:
    with patch("onyx.llm.factory.LitellmLLM") as mock_litellm_llm:
        get_llm(
            provider="openai",
            model="gpt-4o",
            deployment_name=None,
            max_input_tokens=4096,
            additional_headers={"x-request-scoped": "a"},
        )

        kwargs = mock_litellm_llm.call_args.kwargs
        assert kwargs["extra_headers"] == {"x-request-scoped": "a"}


def test_llm_from_provider_resolves_policy_headers_for_the_winning_provider() -> None:
    """The caller hands policy as a provider-keyed function because persona
    resolution decides the provider inside the factory."""
    provider = _build_provider_view(
        provider=BIFROST_PROVIDER_NAME,
        max_input_tokens=4096,
    )

    with patch("onyx.llm.factory.get_llm") as mock_get_llm:
        llm_from_provider(
            model_name="gpt-4o",
            llm_provider=provider,
            policy_fn=partial(
                incognito_llm_request_policy, IncognitoRecordMode.USAGE_ONLY
            ),
        )

        kwargs = mock_get_llm.call_args.kwargs
        assert kwargs["policy_headers"] == {
            BIFROST_DISABLE_CONTENT_LOGGING_HEADER: "true"
        }


def test_llm_from_provider_without_policy_fn_passes_none() -> None:
    provider = _build_provider_view(
        provider=BIFROST_PROVIDER_NAME,
        max_input_tokens=4096,
    )

    with patch("onyx.llm.factory.get_llm") as mock_get_llm:
        llm_from_provider(model_name="gpt-4o", llm_provider=provider)

        assert mock_get_llm.call_args.kwargs["policy_headers"] is None


def _sentinel_policy_fn(_provider: str) -> LlmRequestPolicy:
    return LlmRequestPolicy()


def _mock_user() -> MagicMock:
    """get_llm_for_persona reads the user's chat-default attributes, which
    must be concrete values for UserChatDefaults validation."""
    user = MagicMock()
    user.temperature_default = None
    user.reasoning_effort_default = None
    return user


class TestPolicyFnForwarding:
    """Every exit of the persona chain must forward the policy function.

    A dropped forward is a silent policy loss on a fallback path, invisible to
    the precedence test, which only guards the final merge inside get_llm.
    """

    def test_no_persona_exit_forwards(self) -> None:
        with patch("onyx.llm.factory.get_default_llm") as mock_default:
            get_llm_for_persona(
                persona=None,
                user=_mock_user(),
                policy_fn=_sentinel_policy_fn,
            )
            assert mock_default.call_args.kwargs["policy_fn"] is _sentinel_policy_fn

    def test_unconfigured_persona_exit_forwards(self) -> None:
        persona = MagicMock()
        persona.default_model_configuration_id = None
        with patch("onyx.llm.factory.get_default_llm") as mock_default:
            get_llm_for_persona(
                persona=persona,
                user=_mock_user(),
                policy_fn=_sentinel_policy_fn,
            )
            assert mock_default.call_args.kwargs["policy_fn"] is _sentinel_policy_fn

    def test_failed_resolution_exit_forwards(self) -> None:
        persona = MagicMock()
        persona.default_model_configuration_id = 123
        with (
            patch("onyx.llm.factory.get_session_with_current_tenant"),
            patch("onyx.llm.factory._resolve_provider_and_model", return_value=None),
            patch("onyx.llm.factory.get_default_llm") as mock_default,
        ):
            get_llm_for_persona(
                persona=persona,
                user=_mock_user(),
                policy_fn=_sentinel_policy_fn,
            )
            assert mock_default.call_args.kwargs["policy_fn"] is _sentinel_policy_fn

    def test_access_denied_exit_forwards(self) -> None:
        persona = MagicMock()
        persona.default_model_configuration_id = 123
        with (
            patch("onyx.llm.factory.get_session_with_current_tenant"),
            patch(
                "onyx.llm.factory._resolve_provider_and_model",
                return_value=(MagicMock(), "some-model"),
            ),
            patch("onyx.llm.factory.fetch_user_group_ids", return_value=[]),
            patch("onyx.llm.factory.can_user_access_llm_provider", return_value=False),
            patch("onyx.llm.factory.get_default_llm") as mock_default,
        ):
            get_llm_for_persona(
                persona=persona,
                user=_mock_user(),
                policy_fn=_sentinel_policy_fn,
            )
            assert mock_default.call_args.kwargs["policy_fn"] is _sentinel_policy_fn

    def test_resolved_provider_exit_forwards(self) -> None:
        persona = MagicMock()
        persona.default_model_configuration_id = 123
        with (
            patch("onyx.llm.factory.get_session_with_current_tenant"),
            patch(
                "onyx.llm.factory._resolve_provider_and_model",
                return_value=(MagicMock(), "some-model"),
            ),
            patch("onyx.llm.factory.fetch_user_group_ids", return_value=[]),
            patch("onyx.llm.factory.can_user_access_llm_provider", return_value=True),
            patch("onyx.llm.factory.LLMProviderView"),
            patch("onyx.llm.factory.llm_from_provider") as mock_from_provider,
        ):
            get_llm_for_persona(
                persona=persona,
                user=_mock_user(),
                policy_fn=_sentinel_policy_fn,
            )
            assert (
                mock_from_provider.call_args.kwargs["policy_fn"] is _sentinel_policy_fn
            )

    def test_get_default_llm_forwards(self) -> None:
        with (
            patch("onyx.llm.factory.get_session_with_current_tenant"),
            patch("onyx.llm.factory.fetch_default_llm_model", return_value=MagicMock()),
            patch("onyx.llm.factory.LLMProviderView"),
            patch("onyx.llm.factory.llm_from_provider") as mock_from_provider,
        ):
            get_default_llm(policy_fn=_sentinel_policy_fn)
            assert (
                mock_from_provider.call_args.kwargs["policy_fn"] is _sentinel_policy_fn
            )


def test_client_config_resolves_capabilities() -> None:
    from onyx.llm.multi_llm import LitellmLLM

    with patch(
        "onyx.llm.multi_llm.get_model_map",
        return_value={"custom-model": {"supports_vision": True}},
    ):
        client: LitellmLLM = LitellmLLM(
            api_key="secret-key",
            model_provider="openai",
            model_name="custom-model",
            max_input_tokens=1000,
        )
    metadata: LLMConfig = client.config
    assert client.config == metadata
    assert client.config is not metadata
    assert metadata.supports_images is True
    assert metadata.api_key == "secret-key"


def test_factory_carries_configured_vision_support_to_client() -> None:
    provider: LLMProviderView = _build_provider_view("openai", 4096)
    provider.model_configurations[0].supports_image_input = True
    with patch("onyx.llm.factory.LitellmLLM") as create_client:
        llm_from_provider("test-model", provider)
    assert create_client.call_args.kwargs["supports_images"] is True


def test_factory_falls_back_to_catalog_without_configured_vision() -> None:
    provider: LLMProviderView = _build_provider_view("openai", 4096)
    provider.model_configurations[0].supports_image_input = False
    with patch(
        "onyx.llm.multi_llm.get_model_map",
        return_value={"test-model": {"supports_vision": True}},
    ):
        client: LitellmLLM = llm_from_provider("test-model", provider)
    assert client.config.supports_images is True


def test_client_config_is_a_defensive_snapshot() -> None:
    from onyx.llm.multi_llm import LitellmLLM

    settings: dict[str, str] = {"custom_api_key": "original-key"}
    client: LitellmLLM = LitellmLLM(
        api_key="secret-key",
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=1000,
        custom_config=settings,
    )
    settings["custom_api_key"] = "changed-input"
    snapshot: LLMConfig = client.config
    assert snapshot.custom_config == {"custom_api_key": "original-key"}
    snapshot.custom_config["custom_api_key"] = "changed-snapshot"
    assert client.config.custom_config == {"custom_api_key": "original-key"}


@pytest.mark.parametrize(
    "catalog, override, expected",
    [
        ({}, None, None),
        ({"supports_vision": None}, None, None),
        ({"supports_vision": False}, None, False),
        ({"supports_vision": True}, False, False),
        ({"supports_vision": False}, True, True),
    ],
)
def test_client_image_capability_fallback(
    catalog: dict[str, bool | None], override: bool | None, expected: bool | None
) -> None:
    with patch(
        "onyx.llm.multi_llm.get_model_map", return_value={"test-model": catalog}
    ) as model_map:
        client: LitellmLLM = get_llm(
            provider="openai",
            model="test-model",
            deployment_name=None,
            max_input_tokens=4096,
            supports_images=override,
        )
    assert client.config.supports_images is expected
    if override is not None:
        model_map.assert_not_called()
    else:
        model_map.assert_called_once()


def test_client_resolves_image_capability_from_deployment_name() -> None:
    with patch(
        "onyx.llm.multi_llm.get_model_map",
        return_value={"known-model": {"supports_vision": True}},
    ):
        client: LitellmLLM = get_llm(
            provider="openai",
            model="deployment-alias",
            deployment_name="known-model",
            max_input_tokens=4096,
        )
    assert client.config.supports_images is True


def test_factory_captures_nested_request_and_policy_settings() -> None:
    metadata: dict[str, JsonValue] = {"source": "caller"}
    kwargs: dict[str, JsonValue] = {"metadata": metadata}
    policy_body: dict[str, JsonValue] = {"store": False}
    policy_kwargs: dict[str, JsonValue] = {"extra_body": policy_body}
    client: LitellmLLM = get_llm(
        provider="openai",
        model="gpt-5-mini",
        deployment_name=None,
        max_input_tokens=4096,
        model_kwargs=kwargs,
        policy_model_kwargs=policy_kwargs,
    )
    metadata["source"] = "changed"
    policy_body["store"] = True
    response: LiteLLMModelResponse = LiteLLMModelResponse(
        id="captured-settings",
        created=1,
        choices=[
            {
                "message": {"role": "assistant", "content": "done"},
                "finish_reason": "stop",
            }
        ],
    )
    with (
        patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False),
        patch("litellm.completion", return_value=response) as completion,
    ):
        assert (
            client.invoke(
                GenerationRequest(messages=[UserMessage(content="test")])
            ).text
            == "done"
        )
    sent: Mapping[str, object] = completion.call_args.kwargs
    assert sent["metadata"] == {"source": "caller"}
    body: Mapping[str, object] = cast(Mapping[str, object], sent["extra_body"])
    assert body["store"] is False


def test_client_does_not_modify_caller_model_kwargs() -> None:
    metadata: dict[str, JsonValue] = {"source": "caller"}
    kwargs: dict[str, JsonValue] = {"metadata": metadata}
    LitellmLLM(
        api_key=None,
        model_provider="ollama_chat",
        model_name="unknown-model",
        max_input_tokens=4096,
        model_kwargs=kwargs,
    )
    assert kwargs == {"metadata": {"source": "caller"}}


def test_client_captures_nested_deployment_settings_after_merging() -> None:
    deployment: list[JsonValue] = ["original"]
    defaults: dict[str, JsonValue] = {"enabled": True}
    deployment_body: dict[str, JsonValue] = {
        "metadata": {"deployment": deployment, "source": "deployment"},
        "default_only": defaults,
    }
    request_metadata: dict[str, JsonValue] = {"source": "request"}
    kwargs: dict[str, JsonValue] = {
        "extra_body": {"metadata": request_metadata},
    }
    client: LitellmLLM = LitellmLLM(
        api_key="secret-key",
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=4096,
        extra_body=deployment_body,
        model_kwargs=kwargs,
    )
    assert deployment_body == {
        "metadata": {"deployment": ["original"], "source": "deployment"},
        "default_only": {"enabled": True},
    }
    assert kwargs == {"extra_body": {"metadata": {"source": "request"}}}
    deployment.append("changed")
    defaults["enabled"] = False
    request_metadata["source"] = "changed"
    response: LiteLLMModelResponse = LiteLLMModelResponse(
        choices=[{"message": {"role": "assistant", "content": "done"}}],
    )
    with (
        patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False),
        patch("litellm.completion", return_value=response) as completion,
    ):
        assert (
            client.invoke(
                GenerationRequest(messages=[UserMessage(content="test")])
            ).text
            == "done"
        )
    sent: Mapping[str, object] = completion.call_args.kwargs
    assert sent["extra_body"] == {
        "metadata": {"deployment": ["original"], "source": "request"},
        "default_only": {"enabled": True},
    }
