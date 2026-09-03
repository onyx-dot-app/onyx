"""Shared PCM16 audio helpers for voice providers."""

import math
import struct


class Pcm16Resampler:
    """Resamples little-endian PCM16 mono audio with linear interpolation.

    The resampler keeps the read position and the last input sample between
    calls, so streamed chunks join without lost or shifted samples.
    """

    def __init__(self, input_sample_rate: int, target_sample_rate: int) -> None:
        if input_sample_rate <= 0 or target_sample_rate <= 0:
            raise ValueError("Sample rates must be positive")

        self._ratio = input_sample_rate / target_sample_rate
        self._passthrough = input_sample_rate == target_sample_rate
        # Read position in the current chunk. A negative value points into the
        # previous chunk's final sample.
        self._position: float = 0.0
        self._previous_sample = 0

    def resample(self, data: bytes) -> bytes:
        """Resample one chunk. Output samples are clamped to the int16 range."""
        if self._passthrough:
            return data

        num_samples = len(data) // 2
        if num_samples == 0:
            return b""

        samples = struct.unpack(f"<{num_samples}h", data)

        resampled: list[int] = []
        position = self._position
        # An output sample needs the input samples on both sides of its read
        # position, so stop when the right side is in the next chunk.
        while position < num_samples - 1:
            index = math.floor(position)
            frac = position - index
            left = samples[index] if index >= 0 else self._previous_sample
            right = samples[index + 1]
            sample = int(round(left * (1 - frac) + right * frac))
            resampled.append(max(-32768, min(32767, sample)))
            position += self._ratio

        self._position = position - num_samples
        self._previous_sample = samples[-1]

        return struct.pack(f"<{len(resampled)}h", *resampled)


def resample_pcm16(
    data: bytes, input_sample_rate: int, target_sample_rate: int
) -> bytes:
    """Resample one standalone PCM16 buffer. Use `Pcm16Resampler` for streams."""
    return Pcm16Resampler(input_sample_rate, target_sample_rate).resample(data)
