"""Shared PCM16 audio helpers for voice providers."""

import struct


def resample_pcm16(
    data: bytes, input_sample_rate: int, target_sample_rate: int
) -> bytes:
    """Resample little-endian PCM16 mono audio via linear interpolation.

    Passes through unchanged when the rates match. Output samples are
    clamped to the int16 range.
    """
    if input_sample_rate <= 0 or target_sample_rate <= 0:
        raise ValueError("Sample rates must be positive")

    if input_sample_rate == target_sample_rate:
        return data

    num_samples = len(data) // 2
    if num_samples == 0:
        return b""

    samples = list(struct.unpack(f"<{num_samples}h", data))
    ratio = input_sample_rate / target_sample_rate
    new_length = int(num_samples / ratio)

    resampled: list[int] = []
    for i in range(new_length):
        src_idx = i * ratio
        idx_floor = int(src_idx)
        idx_ceil = min(idx_floor + 1, num_samples - 1)
        frac = src_idx - idx_floor
        sample = int(samples[idx_floor] * (1 - frac) + samples[idx_ceil] * frac)
        sample = max(-32768, min(32767, sample))
        resampled.append(sample)

    return struct.pack(f"<{len(resampled)}h", *resampled)
