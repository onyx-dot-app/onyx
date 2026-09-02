from unittest.mock import MagicMock

import pytest

from onyx.db.models import VoiceProvider
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.voice.api import (
    STORED_API_SECRET_PLACEHOLDER,
    _provider_to_view,
    activate_tts_provider_endpoint,
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
    provider.name = "Zoom"
    provider.provider_type = "zoom"
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
    def __init__(self, tts_models: list[dict[str, str]]) -> None:
        self.tts_models = tts_models
        self.validate_credentials_called = False

    def get_available_tts_models(self) -> list[dict[str, str]]:
        return self.tts_models

    async def validate_credentials(self) -> None:
        self.validate_credentials_called = True


def test_provider_to_view_returns_fixed_secret_placeholder() -> None:
    provider = _make_provider()
    provider.api_key = "zoom-key"  # ty: ignore[invalid-assignment]
    provider.api_secret = "actual-secret-value"  # ty: ignore[invalid-assignment]

    view = _provider_to_view(provider)

    assert view.api_key is not None
    assert view.api_key != "zoom-key"
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
                name="Zoom",
                provider_type="zoom",
                api_key="key",
                api_key_changed=True,
                custom_config={"nested": [{"api_secret": "secret"}]},
            ),
            MagicMock(),
            MagicMock(),
        )


@pytest.mark.asyncio
async def test_upsert_rejects_tts_activation_without_tts_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_provider = _make_provider()
    existing_provider.api_key = "key"  # ty: ignore[invalid-assignment]
    db_session = MagicMock()
    db_session.scalar.return_value = existing_provider
    mock_voice_provider = MockVoiceProvider(tts_models=[])

    monkeypatch.setattr(
        "onyx.server.manage.voice.api.get_voice_provider",
        lambda _: mock_voice_provider,
    )

    with pytest.raises(OnyxError, match="does not support text-to-speech"):
        await upsert_voice_provider_endpoint(
            VoiceProviderUpsertRequest(
                id=1,
                name="Zoom",
                provider_type="zoom",
                api_key="key",
                api_key_changed=True,
                activate_tts=True,
            ),
            MagicMock(),
            db_session,
        )

    assert mock_voice_provider.validate_credentials_called is False
    db_session.rollback.assert_called_once()
    db_session.commit.assert_not_called()


def test_activate_tts_rejects_provider_without_tts_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_provider = _make_provider()
    db_session = MagicMock()
    db_session.scalar.return_value = existing_provider

    monkeypatch.setattr(
        "onyx.server.manage.voice.api.get_voice_provider",
        lambda _: MockVoiceProvider(tts_models=[]),
    )

    with pytest.raises(OnyxError, match="does not support text-to-speech"):
        activate_tts_provider_endpoint(1, None, MagicMock(), db_session)

    assert existing_provider.is_default_tts is False
    db_session.execute.assert_not_called()
    db_session.commit.assert_not_called()


def test_activate_tts_allows_provider_with_tts_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_provider = _make_provider()
    existing_provider.provider_type = "openai"
    db_session = MagicMock()
    db_session.scalar.return_value = existing_provider

    monkeypatch.setattr(
        "onyx.server.manage.voice.api.get_voice_provider",
        lambda _: MockVoiceProvider(tts_models=[{"id": "tts-1", "name": "TTS 1"}]),
    )

    view = activate_tts_provider_endpoint(1, None, MagicMock(), db_session)

    assert existing_provider.is_default_tts is True
    assert view.is_default_tts is True
    db_session.execute.assert_called_once()
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

    class MockTestVoiceProvider:
        async def validate_credentials(self) -> None:
            return None

    def mock_get_voice_provider(provider: VoiceProvider) -> MockTestVoiceProvider:
        nonlocal captured_provider
        captured_provider = provider
        return MockTestVoiceProvider()

    monkeypatch.setattr(
        "onyx.server.manage.voice.api.get_voice_provider", mock_get_voice_provider
    )

    await voice_provider_test_endpoint(
        VoiceProviderTestRequest(
            provider_type="zoom",
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
