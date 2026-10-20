from unittest.mock import MagicMock, patch

import httpx
import jwt
import pytest

from onyx.db.models import LLMProvider, VoiceProvider
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.decisions import factory
from onyx.llm.decisions.client import DecisionClient
from onyx.llm.decisions.models import (
    DecisionProvider,
    DecisionRequest,
    PredicateQuestion,
)
from onyx.llm.well_known_providers import llm_provider_options
from onyx.server.manage.llm import api
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import TestLLMRequest as LLMTestRequest
from onyx.tracing.flows import LLMFlow
from onyx.utils.sensitive import SensitiveValue


def _secret(value: str) -> SensitiveValue[str]:
    return SensitiveValue(
        encrypted_bytes=value.encode(), decrypt_fn=lambda raw: raw.decode()
    )


def _voice(key: str = "scribe-key", secret: str = "scribe-secret" * 4) -> VoiceProvider:
    return VoiceProvider(
        id=4,
        name="Zoom",
        provider_type="zoom",
        api_key=_secret(key),
        api_secret=_secret(secret),
    )


def test_zoom_setup_options_include_both_decision_models() -> None:
    with patch.object(
        llm_provider_options,
        "get_recommendations",
        return_value=llm_provider_options._load_bundled_recommendations(),
    ):
        options = api.fetch_llm_provider_options("zoom_ai", MagicMock())
    assert options.name == "zoom_ai"
    assert [model.name for model in options.known_models] == [
        "zoom-decisions",
        "zoom-decisions-pro",
    ]
    assert all(model.supports_decisions for model in options.known_models)
    assert all(not model.supports_chat for model in options.known_models)


def test_linked_zoom_reads_rotated_credentials_for_each_request() -> None:
    voice = _voice()
    tokens: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.zoom.us/v2/aiservices/decisions/decide"
        tokens.append(request.headers["Authorization"].removeprefix("Bearer "))
        return httpx.Response(
            200,
            json={
                "model": "zoom-decisions",
                "answers": [{"type": "predicate", "name": "check", "probability": 0.9}],
            },
        )

    original_client = httpx.Client
    with (
        patch.object(factory, "get_session_with_current_tenant"),
        patch.object(
            factory, "fetch_voice_provider_by_id", side_effect=lambda *_, **__: voice
        ),
        patch(
            "onyx.llm.decisions.client.httpx.Client",
            side_effect=lambda **kwargs: original_client(
                transport=httpx.MockTransport(handle), **kwargs
            ),
        ),
    ):
        client = factory.build_decision_client(
            provider="zoom_ai",
            model="zoom-decisions",
            api_key=None,
            zoom_voice_provider_id=4,
        )
        request = DecisionRequest(
            input="The sky is blue",
            questions=[
                PredicateQuestion(name="check", instructions="Is the sky blue?")
            ],
        )
        client.decide(request, flow=LLMFlow.MODEL_VALIDATION)
        voice = _voice("rotated-key", "rotated-secret" * 4)
        client.decide(request, flow=LLMFlow.MODEL_VALIDATION)

    assert (
        jwt.decode(tokens[0], "scribe-secret" * 4, algorithms=["HS256"])["iss"]
        == "scribe-key"
    )
    assert (
        jwt.decode(tokens[1], "rotated-secret" * 4, algorithms=["HS256"])["iss"]
        == "rotated-key"
    )
    assert tokens[0] != tokens[1]


@pytest.mark.parametrize(
    "voice",
    [
        None,
        VoiceProvider(provider_type="openai"),
        VoiceProvider(provider_type="zoom"),
        VoiceProvider(provider_type="zoom", api_key=_secret("key")),
    ],
)
def test_link_requires_zoom_key_and_secret(voice: VoiceProvider | None) -> None:
    with patch.object(factory, "fetch_voice_provider_by_id", return_value=voice):
        with pytest.raises(ValueError):
            factory.validate_zoom_voice_provider(MagicMock(), 4)


@pytest.mark.parametrize(
    "provider,source,api_base,custom_config,api_key",
    [
        ("openai", 4, None, None, None),
        ("zoom_ai", 4, "https://example.com", None, None),
        ("zoom_ai", 4, None, {"api_secret": "secret"}, None),
        ("zoom_ai", 4, None, None, "copied-key"),
    ],
)
@pytest.mark.parametrize("operation", ["test", "update"])
def test_generic_routes_reject_invalid_zoom_link(
    provider: str,
    source: int,
    api_base: str | None,
    custom_config: dict[str, str] | None,
    api_key: str | None,
    operation: str,
) -> None:
    with (
        patch.object(api, "has_global_permission", return_value=True),
        patch.object(api, "build_decision_client") as build,
    ):
        with pytest.raises(OnyxError):
            if operation == "test":
                api.test_llm_configuration(
                    LLMTestRequest(
                        provider=provider,
                        model="zoom-decisions",
                        zoom_voice_provider_id=source,
                        api_key=api_key,
                        api_base=api_base,
                        custom_config=custom_config,
                        api_key_changed=True,
                        custom_config_changed=True,
                    ),
                    MagicMock(),
                    MagicMock(),
                )
            else:
                api.put_llm_provider(
                    LLMProviderUpsertRequest(
                        provider=provider,
                        zoom_voice_provider_id=source,
                        api_key=api_key,
                        api_base=api_base,
                        custom_config=custom_config,
                    ),
                    True,
                    MagicMock(),
                    MagicMock(),
                )
    build.assert_not_called()


@pytest.mark.parametrize("operation", ["test", "update"])
def test_llm_manager_cannot_test_or_update_linked_voice_credentials(
    operation: str,
) -> None:
    saved = LLMProvider(id=7, provider="zoom_ai", zoom_voice_provider_id=4)
    with (
        patch.object(api, "fetch_existing_llm_provider_by_id", return_value=saved),
        patch.object(api, "has_global_permission", return_value=False),
    ):
        with pytest.raises(OnyxError) as error:
            if operation == "test":
                api.test_llm_configuration(
                    LLMTestRequest(
                        id=7,
                        provider="zoom_ai",
                        model="zoom-decisions",
                        api_key_changed=True,
                        custom_config_changed=True,
                    ),
                    MagicMock(),
                    MagicMock(),
                )
            else:
                api.put_llm_provider(
                    LLMProviderUpsertRequest(
                        id=7, provider="zoom_ai", api_key_changed=True
                    ),
                    False,
                    MagicMock(),
                    MagicMock(),
                )
    assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_zoom_client_rejects_custom_destination() -> None:
    with pytest.raises(ValueError, match="fixed hosted endpoint"):
        DecisionClient(
            DecisionProvider.ZOOM_AI,
            "zoom-decisions",
            "secret",
            api_base="https://example.com",
        )


def test_other_provider_cannot_resolve_voice_credentials() -> None:
    with pytest.raises(ValueError, match="Only Zoom"):
        factory.build_decision_client(
            provider="openai",
            model="gpt-6-luna",
            api_key=None,
            zoom_voice_provider_id=4,
        )


def test_decision_scope_tests_dual_capability_openai_model_with_decision_protocol() -> (
    None
):
    with (
        patch.object(api, "build_decision_client") as build,
        patch.object(api, "get_llm") as chat,
    ):
        api.test_llm_configuration(
            LLMTestRequest(
                provider="openai",
                model="gpt-6-luna",
                model_configuration_scope="decision",
                api_key="test-key",
                api_key_changed=True,
                custom_config_changed=True,
            ),
            MagicMock(),
            MagicMock(),
        )
    build.assert_called_once_with(
        provider="openai",
        model="gpt-6-luna",
        api_key="test-key",
        api_base=None,
        zoom_voice_provider_id=None,
    )
    build.return_value.decide.assert_called_once()
    chat.assert_not_called()


def test_decision_scope_test_rejects_chat_model_even_with_client_decision_flag() -> (
    None
):
    with (
        patch.object(api, "build_decision_client") as build,
        patch.object(api, "get_llm") as chat,
    ):
        with pytest.raises(OnyxError, match="does not support decisions"):
            api.test_llm_configuration(
                LLMTestRequest(
                    provider="openai",
                    model="gpt-4o",
                    supports_decisions=True,
                    model_configuration_scope="decision",
                    api_key="test-key",
                    api_key_changed=True,
                    custom_config_changed=True,
                ),
                MagicMock(),
                MagicMock(),
            )
    build.assert_not_called()
    chat.assert_not_called()


def test_decision_page_catalog_contains_supported_providers_without_selecting_a_model() -> (
    None
):
    with (
        patch.object(api, "fetch_existing_models", return_value=[]),
        patch.object(api, "fetch_default_model", return_value=None),
    ):
        response = api.get_decision_model_configuration(MagicMock(), MagicMock())
    assert response.model is None
    assert response.providers == []
    assert set(response.supported_providers) == {
        "typesafe",
        "zoom_ai",
        "openai",
        "openrouter",
        "vercel_ai_gateway",
    }
