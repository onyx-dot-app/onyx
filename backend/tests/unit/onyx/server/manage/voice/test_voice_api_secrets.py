from typing import Any
from unittest.mock import MagicMock

import pytest

from onyx.db.models import VoiceProvider
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.voice.api import (
    STORED_API_SECRET_PLACEHOLDER,
    _provider_to_view,
    upsert_voice_provider_endpoint,
)
from onyx.server.manage.voice.api import (
    test_voice_provider as voice_provider_test_endpoint,
)
from onyx.server.manage.voice.models import (
    VoiceProviderTestRequest,
    VoiceProviderUpsertRequest,
)


def _make_provider() -> VoiceProvider:
    provider = VoiceProvider()
    provider.id = 1
    provider.name = "Test"
    provider.provider_type = "openai"
    provider.is_default_stt = False
    provider.is_default_tts = False
    provider.stt_model = None
    provider.tts_model = None
    provider.default_voice = None
    provider.api_base = None
    provider.custom_config = {}
    provider.api_key = None
    provider.api_secret = None
    return provider


class MockVoiceProvider:
    async def validate_credentials(self) -> None:
        return None


def test_provider_to_view_returns_fixed_secret_placeholder() -> None:
    provider = _make_provider()
    provider.api_key = "provider-key"  # ty: ignore[invalid-assignment]
    provider.api_secret = "actual-secret-value"  # ty: ignore[invalid-assignment]

    view = _provider_to_view(provider)

    assert view.api_key is not None
    assert view.api_key != "provider-key"
    assert view.api_secret == STORED_API_SECRET_PLACEHOLDER
    assert "actual" not in view.api_secret


def test_provider_to_view_strips_legacy_custom_config_credentials() -> None:
    provider = _make_provider()
    provider.custom_config = {
        "speech_region": "us-east",
        "nested": {
            "API_SECRET": "legacy-secret",
            "allowed": [{"api_key": "legacy-key"}, {"voice": "alloy"}],
        },
    }

    view = _provider_to_view(provider)

    assert view.custom_config == {
        "speech_region": "us-east",
        "nested": {
            "allowed": [{}, {"voice": "alloy"}],
        },
    }


@pytest.mark.asyncio
async def test_upsert_rejects_custom_config_credentials() -> None:
    with pytest.raises(OnyxError, match="custom_config cannot contain"):
        await upsert_voice_provider_endpoint(
            VoiceProviderUpsertRequest(
                name="Test",
                provider_type="openai",
                api_key="key",
                api_key_changed=True,
                custom_config={"nested": [{"api_secret": "secret"}]},
            ),
            MagicMock(),
            MagicMock(),
        )


@pytest.mark.asyncio
async def test_upsert_forwards_api_secret_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_kwargs: dict[str, Any] = {}
    provider = _make_provider()
    provider.api_key = "key"  # ty: ignore[invalid-assignment]
    provider.api_secret = "secret"  # ty: ignore[invalid-assignment]

    def mock_upsert_voice_provider(**kwargs: Any) -> VoiceProvider:
        captured_kwargs.update(kwargs)
        return provider

    monkeypatch.setattr(
        "onyx.server.manage.voice.api.upsert_voice_provider",
        mock_upsert_voice_provider,
    )
    monkeypatch.setattr(
        "onyx.server.manage.voice.api.get_voice_provider",
        lambda _: MockVoiceProvider(),
    )
    db_session = MagicMock()

    await upsert_voice_provider_endpoint(
        VoiceProviderUpsertRequest(
            name="Test",
            provider_type="openai",
            api_key="key",
            api_key_changed=True,
            api_secret="secret",
            api_secret_changed=True,
        ),
        MagicMock(),
        db_session,
    )

    assert captured_kwargs["api_secret"] == "secret"
    assert captured_kwargs["api_secret_changed"] is True
    db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_voice_provider_test_uses_stored_secret_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored_provider = _make_provider()
    stored_provider.api_secret = "stored-secret"  # ty: ignore[invalid-assignment]

    db_session = MagicMock()
    db_session.scalar.return_value = stored_provider
    captured_provider: VoiceProvider | None = None

    def mock_get_voice_provider(provider: VoiceProvider) -> MockVoiceProvider:
        nonlocal captured_provider
        captured_provider = provider
        return MockVoiceProvider()

    monkeypatch.setattr(
        "onyx.server.manage.voice.api.get_voice_provider", mock_get_voice_provider
    )

    await voice_provider_test_endpoint(
        VoiceProviderTestRequest(
            provider_type="openai",
            api_key="provided-key",
            use_stored_secret=True,
        ),
        MagicMock(),
        db_session,
    )

    assert captured_provider is not None
    assert captured_provider.api_key is not None
    assert captured_provider.api_secret is not None
    assert captured_provider.api_key.get_value(apply_mask=False) == "provided-key"
    assert captured_provider.api_secret.get_value(apply_mask=False) == "stored-secret"
