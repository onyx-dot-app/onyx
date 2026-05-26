"""Live regression tests for OpenAI STT against the GA Realtime API.

These tests guard the handshake and audio-format details that broke when
OpenAI deprecated the Realtime Beta API shape. They exercise the real
endpoint and are skipped via `@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)`
when the key is absent.

Each test makes a single short API call (~1-3s of audio), so they're
cheap enough to run on every PR rather than gating behind `nightly`.
"""

import asyncio
import math
import struct

import pytest

from onyx.voice.providers.openai import OPENAI_REALTIME_STT_MODEL
from onyx.voice.providers.openai import OpenAIStreamingTranscriber
from onyx.voice.providers.openai import OpenAIVoiceProvider
from tests.utils.secret_names import TestSecret

# 24kHz mono PCM16, matching the format Onyx's voice WebSocket emits from
# the browser. Generated programmatically so the test has no audio fixture
# dependency — the connect/handshake path doesn't care about content,
# and the chunked path only needs OpenAI to accept the bytes (an empty
# transcript on silence is a valid outcome).
_SAMPLE_RATE_HZ = 24000
_BYTES_PER_SAMPLE = 2


def _silence_pcm16(duration_s: float) -> bytes:
    return b"\x00\x00" * int(_SAMPLE_RATE_HZ * duration_s)


def _tone_pcm16(duration_s: float, freq_hz: int = 440) -> bytes:
    """Single-tone PCM16. Whisper transcribes this as empty string most of
    the time, but the bytes are well-formed audio that OpenAI accepts."""
    samples = []
    for n in range(int(_SAMPLE_RATE_HZ * duration_s)):
        value = int(0.3 * 32767 * math.sin(2 * math.pi * freq_hz * n / _SAMPLE_RATE_HZ))
        samples.append(struct.pack("<h", value))
    return b"".join(samples)


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_streaming_connect_uses_ga_realtime_shape(
    test_secrets: dict[TestSecret, str],
) -> None:
    """Connecting to the Realtime API with our session.update payload must
    NOT produce an `error` event from OpenAI. Catches re-introduction of
    the Beta header / message shape, wrong session.type, wrong audio
    format field, or any future endpoint-side deprecation.

    Note: OpenAI does *not* close the WebSocket when it rejects a
    session.update — it sends an `error` event and leaves the socket
    open. So we must check `_last_error`, not `_ws.closed`. (An earlier
    version of this test only checked `_ws.closed` and silently passed
    against a poisoned session.)
    """

    async def run() -> None:
        transcriber = OpenAIStreamingTranscriber(
            api_key=test_secrets[TestSecret.OPENAI_API_KEY],
            model=OPENAI_REALTIME_STT_MODEL,
        )
        try:
            await transcriber.connect()
            # Give OpenAI a moment to send session.created / session.updated
            # (or an error event for a bad handshake).
            await asyncio.sleep(1.5)
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
    """Send PCM16 audio through the streaming WS and confirm OpenAI returns
    a `conversation.item.input_audio_transcription.completed` event (or at
    least does not return an error). Catches audio-format mismatches in
    the session config (e.g. `audio.input.format` vs `input_audio_format`).
    """

    async def run() -> None:
        transcriber = OpenAIStreamingTranscriber(
            api_key=test_secrets[TestSecret.OPENAI_API_KEY],
            model=OPENAI_REALTIME_STT_MODEL,
        )
        await transcriber.connect()
        try:
            # 2 seconds of tone is enough audio for the model to finish a
            # turn after we commit. Send in 100ms chunks like the browser.
            tone = _tone_pcm16(duration_s=2.0)
            chunk_size = _SAMPLE_RATE_HZ * _BYTES_PER_SAMPLE // 10
            for offset in range(0, len(tone), chunk_size):
                await transcriber.send_audio(tone[offset : offset + chunk_size])
                await asyncio.sleep(0.05)
        finally:
            final = await transcriber.close()
        assert transcriber._last_error is None, (
            f"OpenAI returned an error during the audio round-trip: "
            f"{transcriber._last_error}"
        )
        # We don't assert on transcript content — Whisper may return an
        # empty string for a pure tone. The fact that `close()` returned
        # without timing out on a hung receive loop proves the protocol
        # round-trip works.
        assert isinstance(final, str)

    asyncio.run(run())


@pytest.mark.secrets(TestSecret.OPENAI_API_KEY)
def test_chunked_transcribe_accepts_pcm16(
    test_secrets: dict[TestSecret, str],
) -> None:
    """`OpenAIVoiceProvider.transcribe()` must wrap raw PCM16 in a WAV
    container before posting; without that wrap, `/v1/audio/transcriptions`
    rejects the file with `Invalid file format`. Guards the chunked
    fallback used when streaming is unavailable.
    """

    async def run() -> str:
        provider = OpenAIVoiceProvider(
            api_key=test_secrets[TestSecret.OPENAI_API_KEY],
            stt_model="whisper-1",
        )
        # 1 second of silence is enough for the HTTP endpoint to accept the
        # file and return an empty transcript. The bug we're guarding is a
        # 400 from OpenAI, not an empty string.
        return await provider.transcribe(_silence_pcm16(duration_s=1.0), "pcm16")

    transcript = asyncio.run(run())
    assert isinstance(transcript, str)
