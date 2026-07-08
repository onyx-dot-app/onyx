"""Tests for ChunkedTranscriber silence gating and PCM windowing.

STT models hallucinate training-data boilerplate on silent audio instead of
returning an empty transcript, so silent audio must never reach the provider.
"""

import math
from unittest.mock import AsyncMock

import pytest

from onyx.server.manage.voice.websocket_api import ChunkedTranscriber
from onyx.server.manage.voice.websocket_api import pcm16_rms
from onyx.server.manage.voice.websocket_api import PCM_BYTES_PER_SECOND
from onyx.server.manage.voice.websocket_api import PCM_SAMPLE_RATE
from onyx.server.manage.voice.websocket_api import SILENCE_RMS_THRESHOLD
from onyx.server.manage.voice.websocket_api import trim_pcm16_silence


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(PCM_SAMPLE_RATE * seconds)


def _tone(seconds: float, amplitude: int = 8000, freq_hz: float = 440.0) -> bytes:
    n_samples = int(PCM_SAMPLE_RATE * seconds)
    samples = bytearray()
    for i in range(n_samples):
        value = int(amplitude * math.sin(2 * math.pi * freq_hz * i / PCM_SAMPLE_RATE))
        samples += value.to_bytes(2, "little", signed=True)
    return bytes(samples)


def _chunks(audio: bytes, chunk_seconds: float = 0.25) -> list[bytes]:
    chunk_bytes = int(PCM_BYTES_PER_SECOND * chunk_seconds)
    return [audio[i : i + chunk_bytes] for i in range(0, len(audio), chunk_bytes)]


def _make_transcriber(transcript: str = "hello world") -> ChunkedTranscriber:
    provider = AsyncMock()
    provider.transcribe = AsyncMock(return_value=transcript)
    return ChunkedTranscriber(provider, audio_format="pcm16")


def test_pcm16_rms() -> None:
    assert pcm16_rms(b"") == 0.0
    assert pcm16_rms(_silence(1.0)) == 0.0
    tone_rms = pcm16_rms(_tone(1.0))
    # RMS of a sine wave is amplitude / sqrt(2)
    assert tone_rms == pytest.approx(8000 / math.sqrt(2), rel=0.01)
    assert tone_rms > SILENCE_RMS_THRESHOLD


@pytest.mark.asyncio
async def test_silent_audio_never_reaches_provider() -> None:
    transcriber = _make_transcriber()

    for chunk in _chunks(_silence(10.0)):
        result = await transcriber.add_chunk(chunk)
        assert result is None

    transcriber.provider.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_flush_of_silent_recording_returns_empty() -> None:
    transcriber = _make_transcriber()

    for chunk in _chunks(_silence(2.0)):
        await transcriber.add_chunk(chunk)

    assert await transcriber.flush() == ""
    transcriber.provider.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_speech_is_transcribed_in_multi_second_windows() -> None:
    transcriber = _make_transcriber()

    results = [await transcriber.add_chunk(chunk) for chunk in _chunks(_tone(6.0))]

    transcripts = [r for r in results if r is not None]
    # 6s of speech at a 3s window = exactly 2 provider calls
    assert transcriber.provider.transcribe.await_count == 2
    assert transcripts[-1] == "hello world hello world"


@pytest.mark.asyncio
async def test_window_with_brief_speech_is_transcribed() -> None:
    transcriber = _make_transcriber()

    audio = _silence(1.0) + _tone(0.5) + _silence(1.5)
    results = [await transcriber.add_chunk(chunk) for chunk in _chunks(audio)]

    assert transcriber.provider.transcribe.await_count == 1
    assert [r for r in results if r is not None] == ["hello world"]


@pytest.mark.asyncio
async def test_flush_trims_leading_and_trailing_silence() -> None:
    transcriber = _make_transcriber()

    for chunk in _chunks(_silence(2.0) + _tone(1.0) + _silence(4.0)):
        await transcriber.add_chunk(chunk)

    assert await transcriber.flush() == "hello world"

    sent_audio = transcriber.provider.transcribe.await_args.args[0]
    # 1s of tone + at most 0.5s padding on each side
    assert PCM_BYTES_PER_SECOND * 1.0 <= len(sent_audio) <= PCM_BYTES_PER_SECOND * 2.0


@pytest.mark.asyncio
async def test_non_pcm_format_keeps_legacy_byte_threshold() -> None:
    provider = AsyncMock()
    provider.transcribe = AsyncMock(return_value="hi")
    transcriber = ChunkedTranscriber(provider, audio_format="webm")

    result = await transcriber.add_chunk(b"\x00" * 1500)

    provider.transcribe.assert_awaited_once()
    assert result == "hi"


def test_trim_pcm16_silence() -> None:
    assert trim_pcm16_silence(b"") == b""
    assert trim_pcm16_silence(_silence(5.0)) == b""

    tone = _tone(1.0)
    trimmed = trim_pcm16_silence(_silence(3.0) + tone + _silence(3.0))
    assert len(tone) <= len(trimmed) <= len(tone) + PCM_BYTES_PER_SECOND
    # Trimmed audio still contains the speech energy
    assert pcm16_rms(trimmed) >= SILENCE_RMS_THRESHOLD


@pytest.mark.asyncio
async def test_flush_recovers_quiet_speech_below_absolute_threshold() -> None:
    """Low-gain mic: speech never crosses the absolute RMS threshold, but it
    stands well out of the noise floor, so flush must still transcribe it."""
    transcriber = _make_transcriber()

    quiet_tone = _tone(1.0, amplitude=100)  # RMS ~71, below the 150 threshold
    assert pcm16_rms(quiet_tone) < SILENCE_RMS_THRESHOLD

    for chunk in _chunks(_silence(2.0) + quiet_tone + _silence(2.0)):
        await transcriber.add_chunk(chunk)
    # Live windows are gated by the conservative absolute threshold
    transcriber.provider.transcribe.assert_not_awaited()

    assert await transcriber.flush() == "hello world"
    transcriber.provider.transcribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_flush_recovers_quiet_speech_over_steady_noise_floor() -> None:
    """Quiet speech over a constant noise floor: speech peaks stand ~3x above
    the floor, which must count as speech-like dynamics."""
    transcriber = _make_transcriber()

    floor = _tone(2.0, amplitude=45)  # RMS ~32 noise floor
    speech = _tone(1.0, amplitude=130)  # RMS ~92, still below the 150 threshold
    assert pcm16_rms(speech) < SILENCE_RMS_THRESHOLD

    for chunk in _chunks(floor + speech + floor):
        await transcriber.add_chunk(chunk)
    transcriber.provider.transcribe.assert_not_awaited()

    assert await transcriber.flush() == "hello world"
    transcriber.provider.transcribe.assert_awaited_once()


@pytest.mark.asyncio
async def test_flush_of_uniform_low_noise_returns_empty() -> None:
    """Steady low-level noise has no speech-like dynamics and must not be
    transcribed even though it is above the low-gain speech floor."""
    transcriber = _make_transcriber()

    noise = _tone(6.0, amplitude=50)  # RMS ~35, uniform across the recording
    for chunk in _chunks(noise):
        await transcriber.add_chunk(chunk)

    assert await transcriber.flush() == ""
    transcriber.provider.transcribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_flush_falls_back_to_window_transcripts() -> None:
    """If silence trimming leaves nothing, earlier window transcripts must
    not be discarded."""
    transcriber = _make_transcriber()
    transcriber.transcripts = ["hello", "world"]

    for chunk in _chunks(_silence(1.0)):
        await transcriber.add_chunk(chunk)

    assert await transcriber.flush() == "hello world"
    transcriber.provider.transcribe.assert_not_awaited()
