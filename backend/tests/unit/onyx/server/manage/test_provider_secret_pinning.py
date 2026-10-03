from typing import Literal
from unittest.mock import AsyncMock, MagicMock

import pytest

from onyx.db.models import InternetContentProvider, LLMProvider, VoiceProvider
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.multi_llm import LitellmLLM
from onyx.server.manage.llm import api as llm_api
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import TestLLMRequest as LLMTestRequest
from onyx.server.manage.voice import api as voice_api
from onyx.server.manage.voice.models import (
    VoiceProviderTestRequest,
    VoiceProviderUpsertRequest,
)
from onyx.server.manage.web_search import api as content_api
from onyx.server.manage.web_search.models import WebContentProviderUpsertRequest
from onyx.tools.tool_implementations.web_search.models import WebContentProviderConfig
from onyx.voice.providers.elevenlabs import ElevenLabsVoiceProvider
from shared_configs.enums import WebContentProviderType


@pytest.mark.parametrize("operation", ["save", "test"])
@pytest.mark.parametrize("config_changed", [False, True])
def test_llm_retained_config_cannot_follow_changed_key_flag(
    monkeypatch: pytest.MonkeyPatch,
    operation: Literal["save", "test"],
    config_changed: bool,
) -> None:
    stored = LLMProvider(
        id=1, name="Example", provider="openai", api_base="https://stored.example"
    )
    stored.api_key = "synthetic-old"  # ty: ignore[invalid-assignment]
    stored.custom_config = {"OPENAI_API_KEY": "synthetic-config"}
    monkeypatch.setattr(llm_api, "MULTI_TENANT", True)
    monkeypatch.setattr(
        llm_api, "fetch_existing_llm_provider_by_id", lambda **_: stored
    )
    outbound = MagicMock()
    monkeypatch.setattr(llm_api, "get_llm", outbound)
    monkeypatch.setattr(llm_api, "test_llm", lambda _: None)
    monkeypatch.setattr(llm_api, "invalidate_provider_listing_cache", lambda: None)
    monkeypatch.setattr(llm_api, "upsert_llm_provider", outbound)
    config = {"OPENAI_API_KEY": "****"} if config_changed else None
    with pytest.raises(OnyxError):
        if operation == "save":
            llm_api.put_llm_provider(
                LLMProviderUpsertRequest(
                    id=1,
                    name="Example",
                    provider="openai",
                    api_base="https://other.example",
                    api_key="synthetic-new",
                    api_key_changed=True,
                    custom_config_changed=config_changed,
                    custom_config=config,
                ),
                False,
                MagicMock(),
                MagicMock(),
            )
        else:
            llm_api.test_llm_configuration(
                LLMTestRequest(
                    id=1,
                    provider="openai",
                    model="example",
                    api_base="https://other.example",
                    api_key="synthetic-new",
                    api_key_changed=True,
                    custom_config_changed=config_changed,
                    custom_config=config,
                ),
                MagicMock(),
                MagicMock(),
            )
    outbound.assert_not_called()


@pytest.mark.parametrize("operation", ["save", "test"])
def test_llm_cannot_clear_destination_config_with_stored_key(
    monkeypatch: pytest.MonkeyPatch, operation: Literal["save", "test"]
) -> None:
    stored = LLMProvider(id=1, name="Example", provider="openai", api_base=None)
    stored.api_key = "synthetic-old"  # ty: ignore[invalid-assignment]
    stored.custom_config = {"OPENAI_API_BASE": "https://stored.example"}
    monkeypatch.setattr(llm_api, "MULTI_TENANT", True)
    monkeypatch.setattr(
        llm_api, "fetch_existing_llm_provider_by_id", lambda **_: stored
    )
    outbound = MagicMock()
    monkeypatch.setattr(llm_api, "get_llm", outbound)
    monkeypatch.setattr(llm_api, "test_llm", lambda _: None)
    monkeypatch.setattr(llm_api, "invalidate_provider_listing_cache", lambda: None)
    monkeypatch.setattr(llm_api, "upsert_llm_provider", outbound)
    with pytest.raises(OnyxError):
        if operation == "save":
            llm_api.put_llm_provider(
                LLMProviderUpsertRequest(
                    id=1,
                    name="Example",
                    provider="openai",
                    api_key_changed=False,
                    custom_config_changed=True,
                    custom_config={},
                ),
                False,
                MagicMock(),
                MagicMock(),
            )
        else:
            llm_api.test_llm_configuration(
                LLMTestRequest(
                    id=1,
                    provider="openai",
                    model="example",
                    api_key_changed=False,
                    custom_config_changed=True,
                    custom_config={},
                ),
                MagicMock(),
                MagicMock(),
            )
    outbound.assert_not_called()


@pytest.mark.parametrize("changed", [False, True])
def test_content_save_pins_retained_key(
    monkeypatch: pytest.MonkeyPatch, changed: bool
) -> None:
    stored = InternetContentProvider(
        id=1, name="Example", provider_type=WebContentProviderType.FIRECRAWL.value
    )
    stored.is_active = False
    stored.api_key = "synthetic-content"  # ty: ignore[invalid-assignment]
    stored.config = WebContentProviderConfig(base_url="https://stored.example")
    monkeypatch.setattr(content_api, "MULTI_TENANT", True)
    monkeypatch.setattr(
        content_api, "fetch_web_content_provider_by_name", lambda *_: stored
    )
    monkeypatch.setattr(
        content_api, "fetch_web_content_provider_by_id", lambda *_: stored
    )
    save = MagicMock(return_value=stored)
    monkeypatch.setattr(content_api, "upsert_web_content_provider", save)
    with pytest.raises(OnyxError):
        content_api.upsert_content_provider_endpoint(
            WebContentProviderUpsertRequest(
                id=1,
                name="Example",
                provider_type=WebContentProviderType.FIRECRAWL,
                api_key="synthetic-content",
                api_key_changed=changed,
                config=WebContentProviderConfig(base_url="https://other.example"),
            ),
            MagicMock(),
            MagicMock(),
        )
    save.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["save", "test"])
@pytest.mark.parametrize("target", [None, "https://other.example"])
@pytest.mark.parametrize("secret", [False, True])
async def test_voice_retained_key_pins_destination(
    monkeypatch: pytest.MonkeyPatch,
    operation: Literal["save", "test"],
    target: str | None,
    secret: bool,
) -> None:
    stored = VoiceProvider(
        id=1,
        name="Example",
        provider_type="openai",
        api_base="https://stored.example",
        custom_config={},
    )
    stored.api_key = "synthetic-voice"  # ty: ignore[invalid-assignment]
    stored.api_secret = "synthetic-secret" if secret else None  # ty: ignore[invalid-assignment]
    monkeypatch.setattr(
        voice_api, "fetch_voice_provider_by_id", lambda *_, **__: stored
    )
    monkeypatch.setattr(voice_api, "fetch_voice_provider_by_type", lambda *_: stored)
    monkeypatch.setattr(voice_api, "_validate_voice_api_base", lambda _, base: base)
    outbound = MagicMock()
    monkeypatch.setattr(voice_api, "upsert_voice_provider", outbound)
    monkeypatch.setattr(voice_api, "get_voice_provider", outbound)
    outbound.return_value.validate_credentials = AsyncMock(return_value=None)
    monkeypatch.setattr(voice_api, "_provider_to_view", MagicMock())
    with pytest.raises(OnyxError, match="destination"):
        if operation == "save":
            await voice_api.upsert_voice_provider_endpoint(
                VoiceProviderUpsertRequest(
                    id=1,
                    name="Example",
                    provider_type="openai",
                    api_base=target,
                    api_key="synthetic-new" if secret else None,
                    api_key_changed=secret,
                ),
                MagicMock(),
                MagicMock(),
            )
        else:
            await voice_api.test_voice_provider(
                VoiceProviderTestRequest(
                    id=1,
                    provider_type="openai",
                    use_stored_key=not secret,
                    use_stored_secret=secret,
                    api_key="synthetic-new" if secret else None,
                    api_base=target,
                ),
                MagicMock(),
                MagicMock(),
            )
    outbound.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", [None, "https://other.example"])
@pytest.mark.parametrize("config_endpoint", [False, True])
async def test_voice_copied_llm_key_pins_destination(
    monkeypatch: pytest.MonkeyPatch, target: str | None, config_endpoint: bool
) -> None:
    stored = LLMProvider(
        id=1, name="Example", provider="openai", api_base="https://stored.example"
    )
    stored.api_key = "synthetic-llm"  # ty: ignore[invalid-assignment]
    if config_endpoint:
        stored.api_base = None
        stored.custom_config = {"OPENAI_API_BASE": "https://stored.example"}
    db = MagicMock()
    db.get.return_value = stored
    outbound = MagicMock()
    monkeypatch.setattr(voice_api, "upsert_voice_provider", outbound)
    monkeypatch.setattr(voice_api, "get_voice_provider", outbound)
    monkeypatch.setattr(voice_api, "_validate_voice_api_base", lambda _, base: base)
    outbound.return_value.validate_credentials = AsyncMock(return_value=None)
    monkeypatch.setattr(voice_api, "_provider_to_view", MagicMock())
    with pytest.raises(OnyxError, match="must match"):
        await voice_api.upsert_voice_provider_endpoint(
            VoiceProviderUpsertRequest(
                name="Example",
                provider_type="openai",
                llm_provider_id=1,
                api_base=target,
            ),
            MagicMock(),
            db,
        )
    outbound.assert_not_called()


@pytest.mark.parametrize(
    "key",
    [
        "http_proxy",
        "HTTPS_PROXY",
        "LD_PRELOAD",
        "SSL_CERT_FILE",
        "AWS_SHARED_CREDENTIALS_FILE",
    ],
)
def test_llm_rejects_process_environment_keys(key: str) -> None:
    with pytest.raises(ValueError, match="Process environment key"):
        LitellmLLM(
            api_key="synthetic-key",
            model_provider="openai",
            model_name="example",
            temperature=0,
            custom_config={key: "synthetic-value"},
            max_input_tokens=100,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["http", "websocket"])
@pytest.mark.parametrize("voice", ["../other", "voice?key=value", "voice\n"])
async def test_elevenlabs_rejects_voice_path_input(
    operation: Literal["http", "websocket"], voice: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    outbound = MagicMock(side_effect=AssertionError("outbound request attempted"))
    monkeypatch.setattr(
        "onyx.voice.providers.elevenlabs.aiohttp.ClientSession", outbound
    )
    monkeypatch.setattr(
        "onyx.voice.providers.elevenlabs.ElevenLabsStreamingSynthesizer.connect",
        outbound,
    )
    provider = ElevenLabsVoiceProvider(api_key="synthetic-voice")
    with pytest.raises(ValueError, match="Invalid ElevenLabs voice id"):
        if operation == "http":
            await anext(provider.synthesize_stream("text", voice=voice))
        else:
            await provider.create_streaming_synthesizer(voice=voice)
