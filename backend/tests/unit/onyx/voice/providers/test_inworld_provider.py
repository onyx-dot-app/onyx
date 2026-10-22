import asyncio
import base64
import io
import wave
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from onyx.db.models import VoiceProvider
from onyx.error_handling.exceptions import OnyxError
from onyx.server.manage.voice.user_api import get_voice_status
from onyx.voice.factory import get_voice_provider
from onyx.voice.providers.inworld import (
    MAX_AUDIO_BYTES,
    InworldVoiceProvider,
    split_inworld_text,
)


def mock_session(body: bytes, status: int = 200) -> tuple[MagicMock, MagicMock]:
    response = MagicMock(spec=aiohttp.ClientResponse)
    response.status = status
    response.read = AsyncMock(return_value=body)
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    response.content = aiohttp.StreamReader(MagicMock(), limit=1024 * 1024)
    session = MagicMock(spec=aiohttp.ClientSession)
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.post.return_value = response
    session.get.return_value = response
    return session, response


@pytest.mark.parametrize(
    "text", ["hello " * 1800, "😀" * 4001, "字" * 8001, "a" * 5000]
)
def test_text_split_preserves_all_characters(text: str) -> None:
    chunks = list(split_inworld_text(text))
    assert "".join(chunks) == text
    assert all(0 < len(chunk.encode("utf-16-le")) // 2 <= 4000 for chunk in chunks)


def test_factory_and_status_preserve_independent_defaults() -> None:
    row = VoiceProvider(
        provider_type="Inworld", tts_model="inworld-tts-2-flash", api_key="test-key"
    )
    assert isinstance(get_voice_provider(row), InworldVoiceProvider)
    with (
        patch(
            "onyx.server.manage.voice.user_api.fetch_default_stt_provider",
            return_value=None,
        ),
        patch(
            "onyx.server.manage.voice.user_api.fetch_default_tts_provider",
            return_value=row,
        ),
    ):
        status = get_voice_status(MagicMock(), MagicMock())
    assert not status.stt_enabled and status.tts_enabled
    assert status.tts_max_speed == 1.5


@pytest.mark.asyncio
async def test_fragmented_audio_stream_and_final_line() -> None:
    body = b'{"result":{"audioContent":"YWJj"}}\n\n{"result":{"usage":{}}}\n{"result":{"audioContent":"ZGVm"}}'
    session, response = mock_session(body)

    async def feed() -> None:
        for offset in range(0, len(body), 7):
            response.content.feed_data(body[offset : offset + 7])
            await asyncio.sleep(0)
        response.content.feed_eof()

    with patch(
        "onyx.voice.providers.inworld.aiohttp.ClientSession", return_value=session
    ) as constructor:
        feeder = asyncio.create_task(feed())
        provider = InworldVoiceProvider("test-key")
        audio = [chunk async for chunk in provider.synthesize_stream("Hello")]
        await feeder
    assert audio == [b"abc", b"def"]
    assert constructor.call_args.kwargs["headers"] == {
        "Authorization": "Basic test-key"
    }
    assert (
        session.post.call_args.kwargs["json"]["audioConfig"]["audioEncoding"] == "MP3"
    )
    assert session.post.call_args.kwargs["allow_redirects"] is False
    response.__aexit__.assert_awaited_once()
    session.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tail",
    [
        b'{"error":{"message":"private upstream text"}}',
        b'{"result":{"audioContent":"%%%"}}',
        b"not-json",
        b"{}",
    ],
)
async def test_stream_error_after_audio_is_not_success(tail: bytes) -> None:
    session, response = mock_session(b"")
    response.content.feed_data(b'{"result":{"audioContent":"YWJj"}}\n' + tail)
    response.content.feed_eof()
    with patch(
        "onyx.voice.providers.inworld.aiohttp.ClientSession", return_value=session
    ):
        stream = InworldVoiceProvider("test-key").synthesize_stream("Hello")
        assert await anext(stream) == b"abc"
        with pytest.raises(OnyxError) as exc:
            await anext(stream)
        assert "private upstream text" not in str(exc.value)
    session.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_pcm_fallback_gets_wav_container() -> None:
    session, _ = mock_session(b'{"transcription":{"transcript":"hello"}}')
    with patch(
        "onyx.voice.providers.inworld.aiohttp.ClientSession", return_value=session
    ):
        assert (
            await InworldVoiceProvider("test-key").transcribe(
                b"\x00\x00" * 100, "pcm16"
            )
            == "hello"
        )
    payload = session.post.call_args.kwargs["json"]
    with wave.open(
        io.BytesIO(base64.b64decode(payload["audioData"]["content"]))
    ) as wav:
        assert wav.getframerate() == 24000
        assert wav.getnchannels() == 1
        assert wav.readframes(100) == b"\x00\x00" * 100
    assert payload["transcribeConfig"]["modelId"] == "inworld/inworld-stt-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 302])
async def test_credential_failure_does_not_forward_body(status: int) -> None:
    session, _ = mock_session(b"private details", status)
    with patch(
        "onyx.voice.providers.inworld.aiohttp.ClientSession", return_value=session
    ):
        with pytest.raises(OnyxError, match=f"HTTP {status}"):
            await InworldVoiceProvider("test-key").validate_credentials()


@pytest.mark.asyncio
async def test_limits_fail_before_network() -> None:
    provider = InworldVoiceProvider("test-key")
    with patch("onyx.voice.providers.inworld.aiohttp.ClientSession") as constructor:
        for speed in (0.4, 1.6, float("nan")):
            with pytest.raises(OnyxError, match="playback speed"):
                await anext(provider.synthesize_stream("Hello", speed=speed))
        with pytest.raises(OnyxError, match="10 MiB"):
            await provider.transcribe(bytes(MAX_AUDIO_BYTES + 1), "wav")
        constructor.assert_not_called()


@pytest.mark.asyncio
async def test_cancellation_closes_response_and_session() -> None:
    session, response = mock_session(b"")
    with patch(
        "onyx.voice.providers.inworld.aiohttp.ClientSession", return_value=session
    ):
        stream = InworldVoiceProvider("test-key").synthesize_stream("Hello")
        task = asyncio.ensure_future(anext(stream))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    response.__aexit__.assert_awaited_once()
    session.__aexit__.assert_awaited_once()
