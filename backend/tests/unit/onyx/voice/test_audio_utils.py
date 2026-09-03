import math
import struct

import pytest

from onyx.voice.audio_utils import Pcm16Resampler, resample_pcm16


def test_resample_pcm16_passthrough_when_same_rate() -> None:
    data = struct.pack("<4h", 100, 200, 300, 400)
    assert resample_pcm16(data, 16000, 16000) == data


def test_resample_pcm16_downsamples() -> None:
    """24kHz -> 16kHz should produce fewer samples (ratio 3:2)."""
    input_samples = [1000, 2000, 3000, 4000, 5000, 6000]
    data = struct.pack(f"<{len(input_samples)}h", *input_samples)

    result = resample_pcm16(data, 24000, 16000)
    output_samples = struct.unpack(f"<{len(result) // 2}h", result)

    assert len(output_samples) == 4


def test_resample_pcm16_clamps_to_int16_range() -> None:
    input_samples = [32767, -32768, 32767, -32768, 32767, -32768]
    data = struct.pack(f"<{len(input_samples)}h", *input_samples)

    result = resample_pcm16(data, 24000, 16000)
    output_samples = struct.unpack(f"<{len(result) // 2}h", result)
    for s in output_samples:
        assert -32768 <= s <= 32767


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
    streamed_samples = struct.unpack(f"<{len(streamed) // 2}h", streamed)

    assert len(streamed_samples) == len(expected)
    # Float position accumulation can differ by one quantization step.
    for streamed_sample, expected_sample in zip(
        streamed_samples, expected, strict=True
    ):
        assert abs(streamed_sample - expected_sample) <= 1


def test_streaming_resampler_passthrough_when_same_rate() -> None:
    resampler = Pcm16Resampler(16000, 16000)
    data = struct.pack("<4h", 100, 200, 300, 400)
    assert resampler.resample(data) == data
