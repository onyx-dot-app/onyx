from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from onyx.db.models import VoiceProvider
from onyx.db.voice import fetch_voice_provider_by_id
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.voice.api import (
    _fetch_provider_for_stored_secret,
    activate_tts_provider_endpoint,
    upsert_voice_provider_endpoint,
)
from onyx.server.manage.voice.models import (
    VoiceProviderTestRequest,
    VoiceProviderUpsertRequest,
)
from onyx.tracing.flows import LLMFlow
from onyx.voice.factory import get_voice_provider
from onyx.voice.providers.openai import OpenAIVoiceProvider


def _make_provider(provider_type: str = "openai") -> VoiceProvider:
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
    def __init__(
        self, tts_models: list[dict[str, str]], target_uri: bool = True
    ) -> None:
        self.tts_models = tts_models
        self.target_uri = target_uri
        self.validate_credentials_called = False

    def supports_target_uri(self) -> bool:
        return self.target_uri

    def get_available_tts_models(self) -> list[dict[str, str]]:
        return self.tts_models

    async def validate_credentials(self) -> None:
        self.validate_credentials_called = True


def test_request_models_canonicalize_provider_type() -> None:
    upsert = VoiceProviderUpsertRequest(name="Speech", provider_type=" OpenAI ")
    test = VoiceProviderTestRequest(provider_type="ELEVENLABS")

    assert upsert.provider_type == "openai"
    assert test.provider_type == "elevenlabs"


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
                name="Speech",
                provider_type="openai",
                api_key="key",
                api_key_changed=True,
                activate_tts=True,
            ),
            MagicMock(),
            db_session,
        )

    assert mock_voice_provider.validate_credentials_called is False
    db_session.rollback.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["voice", "decision"])
async def test_zoom_save_validates_requested_service(mode: str) -> None:
    from onyx.server.manage.voice.api import upsert_voice_provider_endpoint

    provider = _make_provider("zoom")
    db_session = MagicMock()
    voice = MockVoiceProvider(tts_models=[])
    with (
        patch(
            "onyx.server.manage.voice.api.upsert_voice_provider", return_value=provider
        ) as save,
        patch("onyx.server.manage.voice.api.get_voice_provider", return_value=voice),
        patch(
            "onyx.server.manage.voice.api._validate_decision_credentials",
            new_callable=AsyncMock,
        ) as decide,
        patch("onyx.server.manage.voice.api.invalidate_provider_listing_cache"),
    ):
        request = VoiceProviderUpsertRequest.model_validate(
            {
                "name": "Zoom",
                "provider_type": "zoom",
                "validation_mode": mode,
                "api_key": "key",
                "api_secret": "secret",
            }
        )
        result = await upsert_voice_provider_endpoint(request, MagicMock(), db_session)
    assert result.id == provider.id
    assert voice.validate_credentials_called is (mode == "voice")
    assert decide.await_count == int(mode == "decision")
    assert save.call_args.kwargs["activate_stt"] is False
    assert save.call_args.kwargs["activate_tts"] is False
    db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_zoom_decision_validation_rolls_back_save() -> None:
    provider = _make_provider("zoom")
    db_session = MagicMock()
    with (
        patch(
            "onyx.server.manage.voice.api.upsert_voice_provider", return_value=provider
        ),
        patch(
            "onyx.server.manage.voice.api.get_voice_provider",
            return_value=MockVoiceProvider([]),
        ),
        patch(
            "onyx.server.manage.voice.api._validate_decision_credentials",
            new_callable=AsyncMock,
            side_effect=RuntimeError("credential must not leak"),
        ),
    ):
        with pytest.raises(OnyxError, match="Connection test failed"):
            await upsert_voice_provider_endpoint(
                VoiceProviderUpsertRequest(
                    name="Zoom",
                    provider_type="zoom",
                    validation_mode="decision",
                ),
                MagicMock(),
                db_session,
            )
    db_session.rollback.assert_called_once()
    db_session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_zoom_decision_validation_uses_signed_fixed_endpoint() -> None:
    from onyx.server.manage.voice.api import _validate_decision_credentials

    provider = _make_provider("zoom")
    provider.api_key = "key"  # ty: ignore[invalid-assignment]
    provider.api_secret = "secret"  # ty: ignore[invalid-assignment]
    with (
        patch(
            "onyx.server.manage.voice.api.build_zoom_scribe_jwt",
            return_value="signed-token",
        ) as signer,
        patch("onyx.server.manage.voice.api.DecisionClient") as client,
    ):
        await _validate_decision_credentials(provider)
    signer.assert_called_once_with("key", "secret")
    assert client.call_args.kwargs["api_key"] == "signed-token"
    assert "api_base" not in client.call_args.kwargs
    assert (
        client.return_value.decide.call_args.kwargs["flow"] == LLMFlow.MODEL_VALIDATION
    )


@pytest.mark.asyncio
async def test_upsert_rejects_default_tts_row_changed_to_stt_only_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_provider = _make_provider(provider_type="openai")
    existing_provider.api_key = "key"  # ty: ignore[invalid-assignment]
    existing_provider.is_default_tts = True
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
                name="Speech",
                provider_type="ELEVENLABS",
                api_key="key",
                api_key_changed=True,
                activate_tts=False,
            ),
            MagicMock(),
            db_session,
        )

    assert existing_provider.provider_type == "elevenlabs"
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


@pytest.mark.parametrize("provider_type", ["OpenAI", " OpenAI ", "\tOpenAI\n"])
def test_stored_secret_lookup_normalizes_legacy_provider_type(
    provider_type: str,
) -> None:
    existing_provider = _make_provider(provider_type=provider_type)
    db_session = MagicMock()
    db_session.get.return_value = existing_provider
    db_session.scalar.return_value = existing_provider

    provider = _fetch_provider_for_stored_secret(db_session, 1, "openai")

    assert provider is existing_provider


@pytest.mark.parametrize("provider_type", ["OpenAI", " openai ", "\tOpenAI\n"])
def test_factory_normalizes_legacy_provider_type(provider_type: str) -> None:
    provider = get_voice_provider(_make_provider(provider_type=provider_type))

    assert isinstance(provider, OpenAIVoiceProvider)


def test_activate_tts_locks_provider_row(monkeypatch: pytest.MonkeyPatch) -> None:
    existing_provider = _make_provider(provider_type="openai")
    db_session = MagicMock()
    db_session.scalar.return_value = existing_provider
    monkeypatch.setattr(
        "onyx.server.manage.voice.api.get_voice_provider",
        lambda _: MockVoiceProvider(tts_models=[{"id": "tts-1", "name": "TTS 1"}]),
    )

    activate_tts_provider_endpoint(1, None, MagicMock(), db_session)

    first_select = db_session.scalar.call_args_list[0].args[0]
    assert first_select._for_update_arg is not None


def test_fetch_voice_provider_by_id_locks_only_when_asked() -> None:
    db_session = MagicMock()

    fetch_voice_provider_by_id(db_session, 1)
    fetch_voice_provider_by_id(db_session, 1, for_update=True)

    plain, locked = (c.args[0] for c in db_session.scalar.call_args_list)
    assert plain._for_update_arg is None
    assert locked._for_update_arg is not None


@pytest.mark.asyncio
async def test_upsert_rejects_target_uri_for_provider_without_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_provider = _make_provider()
    existing_provider.api_key = "key"  # ty: ignore[invalid-assignment]
    db_session = MagicMock()
    db_session.scalar.return_value = existing_provider
    mock_voice_provider = MockVoiceProvider(tts_models=[], target_uri=False)
    monkeypatch.setattr(
        "onyx.server.manage.voice.api.get_voice_provider",
        lambda _: mock_voice_provider,
    )
    monkeypatch.setattr(
        "onyx.server.manage.voice.api.validate_outbound_http_url",
        lambda url, **_kwargs: url,
    )

    with pytest.raises(OnyxError, match="does not support a target URI"):
        await upsert_voice_provider_endpoint(
            VoiceProviderUpsertRequest(
                id=1,
                name="Speech",
                provider_type="openai",
                api_key="key",
                api_key_changed=True,
                api_base="https://api.example.com",
            ),
            MagicMock(),
            db_session,
        )

    assert mock_voice_provider.validate_credentials_called is False
    db_session.rollback.assert_called_once()
