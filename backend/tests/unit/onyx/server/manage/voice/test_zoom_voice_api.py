from unittest.mock import MagicMock

import pytest

from onyx.db.models import VoiceProvider
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.voice.api import (
    activate_tts_provider_endpoint,
    upsert_voice_provider_endpoint,
)
from onyx.server.manage.voice.models import VoiceProviderUpsertRequest


def _make_provider(provider_type: str = "zoom") -> VoiceProvider:
    provider = VoiceProvider()
    provider.id = 1
    provider.name = "Voice Provider"
    provider.provider_type = provider_type
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
    existing_provider = _make_provider(provider_type="openai")
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
