from functools import partial
from unittest.mock import MagicMock, patch

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
from onyx.llm.interfaces import LlmRequestPolicy
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
        get_llm(
            provider=LlmProviderNames.OLLAMA_CHAT,
            model="test-model",
            deployment_name=None,
            max_input_tokens=4096,
            model_kwargs={"num_ctx": 8192},
        )

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


class TestPolicyFnForwarding:
    """Every exit of the persona chain must forward the policy function.

    A dropped forward is a silent policy loss on a fallback path, invisible to
    the precedence test, which only guards the final merge inside get_llm.
    """

    def test_no_persona_exit_forwards(self) -> None:
        with patch("onyx.llm.factory.get_default_llm") as mock_default:
            get_llm_for_persona(
                persona=None,
                user=MagicMock(),
                policy_fn=_sentinel_policy_fn,
            )
            assert mock_default.call_args.kwargs["policy_fn"] is _sentinel_policy_fn

    def test_unconfigured_persona_exit_forwards(self) -> None:
        persona = MagicMock()
        persona.default_model_configuration_id = None
        with patch("onyx.llm.factory.get_default_llm") as mock_default:
            get_llm_for_persona(
                persona=persona,
                user=MagicMock(),
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
                user=MagicMock(),
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
                user=MagicMock(),
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
                user=MagicMock(),
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
