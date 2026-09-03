import struct

import pytest

from onyx.voice.audio_utils import resample_pcm16


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
