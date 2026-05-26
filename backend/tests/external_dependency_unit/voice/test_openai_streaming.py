"""Live regression tests for OpenAI STT against the GA Realtime API.

Skipped via `@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)` when the key
is absent. Single short API call each, so safe to run on every PR.
"""

import asyncio
import math
import struct

import pytest

from onyx.voice.providers.openai import OPENAI_REALTIME_STT_MODEL
from onyx.voice.providers.openai import OpenAIStreamingTranscriber
from onyx.voice.providers.openai import OpenAIVoiceProvider
from tests.utils.secret_names import TestSecret

# 24kHz mono PCM16 — matches the browser's voice WS format.
_SAMPLE_RATE_HZ = 24000
_BYTES_PER_SAMPLE = 2


def _silence_pcm16(duration_s: float) -> bytes:
    return b"\x00\x00" * int(_SAMPLE_RATE_HZ * duration_s)


def _tone_pcm16(duration_s: float, freq_hz: int = 440) -> bytes:
    samples = []
    for n in range(int(_SAMPLE_RATE_HZ * duration_s)):
        value = int(0.3 * 32767 * math.sin(2 * math.pi * freq_hz * n / _SAMPLE_RATE_HZ))
        samples.append(struct.pack("<h", value))
    return b"".join(samples)


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_streaming_connect_uses_ga_realtime_shape(
    test_secrets: dict[TestSecret, str],
) -> None:
    """`session.update` handshake must not produce an `error` event.

    Must check `_last_error`, not `_ws.closed` — OpenAI keeps the socket
    open on protocol errors, so checking `closed` silently false-passes
    against a poisoned session.
    """

    async def run() -> None:
        transcriber = OpenAIStreamingTranscriber(
            api_key=test_secrets[TestSecret.OPENAI_API_KEY],
            model=OPENAI_REALTIME_STT_MODEL,
        )
        try:
            await transcriber.connect()
            await asyncio.sleep(1.5)  # let session.created / .updated arrive
            assert transcriber._last_error is None, (
                f"OpenAI returned an error during handshake: {transcriber._last_error}"
            )
            assert not transcriber._closed, "transcriber closed early"
            assert transcriber._ws is not None and not transcriber._ws.closed
        finally:
            await transcriber.close()

    asyncio.run(run())


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_streaming_accepts_pcm16_audio_chunks(
    test_secrets: dict[TestSecret, str],
) -> None:
    """PCM16 round-trip through the streaming WS produces no error event."""

    async def run() -> None:
        transcriber = OpenAIStreamingTranscriber(
            api_key=test_secrets[TestSecret.OPENAI_API_KEY],
            model=OPENAI_REALTIME_STT_MODEL,
        )
        await transcriber.connect()
        try:
            tone = _tone_pcm16(duration_s=2.0)
            chunk_size = _SAMPLE_RATE_HZ * _BYTES_PER_SAMPLE // 10  # 100ms
            for offset in range(0, len(tone), chunk_size):
                await transcriber.send_audio(tone[offset : offset + chunk_size])
                await asyncio.sleep(0.05)
        finally:
            final = await transcriber.close()
        assert transcriber._last_error is None, (
            f"OpenAI returned an error during the audio round-trip: "
            f"{transcriber._last_error}"
        )
        # Whisper may transcribe a pure tone as empty — we only assert the
        # protocol round-tripped (close() returned without a hung receive).
        assert isinstance(final, str)

    asyncio.run(run())


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_chunked_transcribe_accepts_pcm16(
    test_secrets: dict[TestSecret, str],
) -> None:
    """`transcribe()` must wrap PCM16 in WAV before posting — without the
    wrap, `/v1/audio/transcriptions` returns `Invalid file format`."""

    async def run() -> str:
        provider = OpenAIVoiceProvider(
            api_key=test_secrets[TestSecret.OPENAI_API_KEY],
            stt_model="whisper-1",
        )
        return await provider.transcribe(_silence_pcm16(duration_s=1.0), "pcm16")

    transcript = asyncio.run(run())
    assert isinstance(transcript, str)
