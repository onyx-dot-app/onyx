import io
import math
import struct
import wave

import pytest

from onyx.voice.audio_utils import (
    Pcm16Resampler,
    _clamp_int16,
    pcm16_to_wav,
    resample_pcm16,
)


def test_resample_pcm16_passthrough_when_same_rate() -> None:
    data = struct.pack("<4h", 100, 200, 300, 400)
    assert resample_pcm16(data, 16000, 16000) == data


def test_resample_pcm16_downsamples() -> None:
    """24kHz -> 16kHz should produce fewer samples (ratio 3:2)."""
    input_samples = [1000, 2000, 3000, 4000, 5000, 6000]
    data = struct.pack(f"<{len(input_samples)}h", *input_samples)

    result = resample_pcm16(data, 24000, 16000)
    output_samples = struct.unpack(f"<{len(result) // 2}h", result)

    # Output sample n reads input position 1.5n, interpolated linearly.
    assert output_samples == (1000, 2500, 4000, 5500)


@pytest.mark.parametrize(
    "value,expected",
    [(40000.0, 32767), (-40000.0, -32768), (1000.4, 1000), (-1000.6, -1001)],
)
def test_clamp_int16(value: float, expected: int) -> None:
    assert _clamp_int16(value) == expected


def test_resample_pcm16_rejects_partial_sample() -> None:
    with pytest.raises(ValueError):
        resample_pcm16(b"\x00\x00\x01", 24000, 16000)


def test_resample_pcm16_empty_data() -> None:
    assert resample_pcm16(b"", 24000, 16000) == b""


@pytest.mark.parametrize(
    "input_sample_rate,target_sample_rate",
    [(0, 16000), (16000, 0), (-1, 16000), (16000, -1)],
)
def test_resample_pcm16_rejects_non_positive_rates(
    input_sample_rate: int, target_sample_rate: int
) -> None:
    with pytest.raises(ValueError):
        resample_pcm16(b"\x00\x00", input_sample_rate, target_sample_rate)


@pytest.mark.parametrize(
    "input_sample_rate,target_sample_rate",
    [(24000, 16000), (16000, 24000), (44100, 16000)],
)
def test_streaming_resampler_matches_single_buffer(
    input_sample_rate: int, target_sample_rate: int
) -> None:
    """Chunks that hold a fractional number of output samples keep phase."""
    samples = [int(10000 * math.sin(i / 7)) for i in range(300)]
    data = struct.pack(f"<{len(samples)}h", *samples)

    expected_bytes = resample_pcm16(data, input_sample_rate, target_sample_rate)
    expected = struct.unpack(f"<{len(expected_bytes) // 2}h", expected_bytes)

    resampler = Pcm16Resampler(input_sample_rate, target_sample_rate)
    streamed = b""
    # 17 samples per chunk, so no chunk aligns with an output sample.
    for offset in range(0, len(data), 34):
        streamed += resampler.resample(data[offset : offset + 34])
    streamed += resampler.flush()
    streamed_samples = struct.unpack(f"<{len(streamed) // 2}h", streamed)

    assert streamed_samples == expected


def test_streaming_resampler_passthrough_when_same_rate() -> None:
    resampler = Pcm16Resampler(16000, 16000)
    data = struct.pack("<4h", 100, 200, 300, 400)
    assert resampler.resample(data) == data
    assert resampler.flush() == b""


def test_streaming_resampler_flush_emits_trailing_samples() -> None:
    """Upsampling holds back samples that read past the last input sample."""
    samples = [1000, 2000, 3000, 4000]
    data = struct.pack(f"<{len(samples)}h", *samples)

    resampler = Pcm16Resampler(16000, 24000)
    streamed = resampler.resample(data)
    trailing = resampler.flush()

    assert trailing
    assert len(streamed + trailing) // 2 == 6
    assert resampler.flush() == b""


def test_pcm16_to_wav_wraps_raw_audio() -> None:
    pcm_data = struct.pack("<4h", 1, 2, 3, 4)
    wav_bytes = pcm16_to_wav(pcm_data, sample_rate=16000)

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.readframes(wav_file.getnframes()) == pcm_data
