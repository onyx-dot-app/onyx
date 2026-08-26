from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from onyx.db.models import VoiceProvider
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.voice.api import (
    _validate_voice_api_base,
    upsert_voice_provider_endpoint,
)
from onyx.server.manage.voice.api import test_voice_provider as run_voice_provider_test
from onyx.server.manage.voice.models import (
    VoiceProviderTestRequest,
    VoiceProviderUpsertRequest,
)
from onyx.server.manage.voice.user_api import get_voice_status
from onyx.server.security.models import (
    SSRFProtectionLevel,
    outbound_ssrf_params,
)
from onyx.voice.types import VoiceProviderType


@pytest.mark.parametrize(
    ("level", "allowed"),
    [
        (SSRFProtectionLevel.VALIDATE_ALL, False),
        (SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK, False),
        (SSRFProtectionLevel.DISABLED, True),
    ],
)
def test_validate_voice_api_base_uses_shared_ssrf_level(
    level: SSRFProtectionLevel, allowed: bool
) -> None:
    settings = SimpleNamespace(ssrf_protection_level=level)
    with patch(
        "onyx.server.manage.voice.api.get_security_settings",
        return_value=settings,
    ):
        if allowed:
            assert (
                _validate_voice_api_base(
                    VoiceProviderType.OPENAI_COMPATIBLE,
                    "http://127.0.0.1:11434",
                )
                == "http://127.0.0.1:11434/v1"
            )
            return

        with pytest.raises(OnyxError, match="Invalid target URI"):
            _validate_voice_api_base(
                VoiceProviderType.OPENAI_COMPATIBLE,
                "http://127.0.0.1:11434",
            )


def test_validate_voice_api_base_passes_all_shared_ssrf_parameters() -> None:
    level = SSRFProtectionLevel.ALLOW_PRIVATE_NETWORK
    settings = SimpleNamespace(ssrf_protection_level=level)
    with (
        patch(
            "onyx.server.manage.voice.api.get_security_settings",
            return_value=settings,
        ),
        patch(
            "onyx.server.manage.voice.api.validate_outbound_http_url",
            return_value="https://stt.example",
        ) as validate,
    ):
        _validate_voice_api_base(
            VoiceProviderType.OPENAI_COMPATIBLE, "https://stt.example"
        )

    params = outbound_ssrf_params(level)
    assert validate.call_args.kwargs == {
        "allow_private_network": params.allow_private_network,
        "block_loopback_and_link_local": params.block_loopback_and_link_local,
        "block_link_local_only": params.block_link_local_only,
    }


def test_validate_voice_api_base_returns_none_for_none() -> None:
    assert _validate_voice_api_base("openai", None) is None


@pytest.mark.parametrize(
    "request_type",
    [VoiceProviderTestRequest, VoiceProviderUpsertRequest],
)
def test_openai_compatible_request_requires_api_base_and_model(
    request_type: type[VoiceProviderTestRequest] | type[VoiceProviderUpsertRequest],
) -> None:
    request_data: dict[str, object] = {
        "provider_type": VoiceProviderType.OPENAI_COMPATIBLE
    }
    if request_type is VoiceProviderUpsertRequest:
        request_data["name"] = "Compatible"

    with pytest.raises(ValidationError, match="API base is required"):
        request_type.model_validate(request_data)

    request_data["api_base"] = "https://stt.example"
    with pytest.raises(ValidationError, match="STT model is required"):
        request_type.model_validate(request_data)


def test_openai_compatible_test_request_allows_missing_api_key() -> None:
    request = VoiceProviderTestRequest(
        provider_type=VoiceProviderType.OPENAI_COMPATIBLE,
        api_base="https://stt.example",
        stt_model="whisper",
    )
    assert request.api_key is None


def test_voice_status_enables_keyless_openai_compatible_stt() -> None:
    stt_provider = SimpleNamespace(
        provider_type=VoiceProviderType.OPENAI_COMPATIBLE.value,
        api_key=None,
    )
    with (
        patch(
            "onyx.server.manage.voice.user_api.fetch_default_stt_provider",
            return_value=stt_provider,
        ),
        patch(
            "onyx.server.manage.voice.user_api.fetch_default_tts_provider",
            return_value=None,
        ),
    ):
        status = get_voice_status(
            cast(Any, SimpleNamespace()), cast(Any, SimpleNamespace())
        )

    assert status.stt_enabled is True
    assert status.tts_enabled is False


@pytest.mark.asyncio
async def test_connection_test_allows_keyless_stored_configuration() -> None:
    request = VoiceProviderTestRequest(
        provider_type=VoiceProviderType.OPENAI_COMPATIBLE,
        api_base="https://stt.example",
        stt_model="whisper",
        use_stored_key=True,
    )
    provider = SimpleNamespace(validate_credentials=AsyncMock())
    with (
        patch(
            "onyx.server.manage.voice.api.fetch_voice_provider_by_type",
            return_value=SimpleNamespace(api_key=None),
        ),
        patch(
            "onyx.server.manage.voice.api._validate_voice_api_base",
            return_value="https://stt.example/v1",
        ),
        patch(
            "onyx.server.manage.voice.api.get_voice_provider",
            return_value=provider,
        ) as factory,
    ):
        await run_voice_provider_test(
            request,
            cast(Any, SimpleNamespace()),
            cast(Any, SimpleNamespace()),
        )

    tested_provider = factory.call_args.args[0]
    assert tested_provider.api_key is None
    assert tested_provider.stt_model == "whisper"
    provider.validate_credentials.assert_awaited_once()


@pytest.mark.asyncio
async def test_upsert_openai_compatible_clears_existing_tts_default() -> None:
    request = VoiceProviderUpsertRequest(
        id=1,
        name="Compatible",
        provider_type=VoiceProviderType.OPENAI_COMPATIBLE,
        api_base="https://stt.example",
        stt_model="whisper",
    )
    stored_provider = VoiceProvider(
        id=1,
        name="Compatible",
        provider_type=VoiceProviderType.OPENAI_COMPATIBLE.value,
        api_base="https://stt.example/v1",
        stt_model="whisper",
        is_default_stt=True,
        is_default_tts=True,
    )
    provider = SimpleNamespace(validate_credentials=AsyncMock())

    def deactivate_tts(**_: Any) -> VoiceProvider:
        stored_provider.is_default_tts = False
        return stored_provider

    db_session = MagicMock()
    with (
        patch(
            "onyx.server.manage.voice.api._validate_voice_api_base",
            return_value="https://stt.example/v1",
        ),
        patch(
            "onyx.server.manage.voice.api.upsert_voice_provider",
            return_value=stored_provider,
        ),
        patch(
            "onyx.server.manage.voice.api.deactivate_tts_provider",
            side_effect=deactivate_tts,
        ) as deactivate,
        patch(
            "onyx.server.manage.voice.api.get_voice_provider",
            return_value=provider,
        ),
    ):
        result = await upsert_voice_provider_endpoint(
            request, cast(Any, SimpleNamespace()), cast(Any, db_session)
        )

    deactivate.assert_called_once_with(db_session=db_session, provider_id=1)
    assert result.is_default_tts is False
    db_session.commit.assert_called_once()
