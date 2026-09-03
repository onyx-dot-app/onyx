"""Shared PCM16 audio helpers for voice providers."""

import io
import struct
import wave


class Pcm16Resampler:
    """Resamples little-endian PCM16 mono audio with linear interpolation.

    The resampler keeps an exact integer phase and the last input sample between
    calls, so streamed chunks join without lost or shifted samples. Call `flush`
    at the end of a stream to emit the samples that the final chunk holds back.
    """

    def __init__(self, input_sample_rate: int, target_sample_rate: int) -> None:
        if input_sample_rate <= 0 or target_sample_rate <= 0:
            raise ValueError("Sample rates must be positive")

        self._input_sample_rate = input_sample_rate
        self._target_sample_rate = target_sample_rate
        self._passthrough = input_sample_rate == target_sample_rate
        # Number of output samples produced and input samples consumed so far.
        # Output sample n reads input position n * input_rate / target_rate.
        self._output_count = 0
        self._input_count = 0
        self._previous_sample = 0

    def _source_position(self) -> tuple[int, float]:
        """Absolute input index and fraction for the next output sample."""
        offset = self._output_count * self._input_sample_rate
        index, remainder = divmod(offset, self._target_sample_rate)
        return index, remainder / self._target_sample_rate

    def resample(self, data: bytes) -> bytes:
        """Resample one chunk. Output samples are clamped to the int16 range."""
        if self._passthrough:
            return data

        num_samples = len(data) // 2
        if num_samples == 0:
            return b""

        samples = struct.unpack(f"<{num_samples}h", data)
        first_index = self._input_count
        last_index = first_index + num_samples - 1

        resampled: list[int] = []
        # An output sample needs the input samples on both sides of its read
        # position, so stop when the right side is in the next chunk.
        while True:
            index, frac = self._source_position()
            if index + 1 > last_index:
                break
            left = (
                samples[index - first_index]
                if index >= first_index
                else self._previous_sample
            )
            right = samples[index + 1 - first_index]
            resampled.append(_clamp_int16(left * (1 - frac) + right * frac))
            self._output_count += 1

        self._input_count += num_samples
        self._previous_sample = samples[-1]

        return struct.pack(f"<{len(resampled)}h", *resampled)

    def flush(self) -> bytes:
        """Emit the trailing output samples that read past the last input sample."""
        if self._passthrough or self._input_count == 0:
            return b""

        last_index = self._input_count - 1
        resampled: list[int] = []
        while True:
            index, _ = self._source_position()
            if index > last_index:
                break
            resampled.append(_clamp_int16(self._previous_sample))
            self._output_count += 1

        return struct.pack(f"<{len(resampled)}h", *resampled)


def _clamp_int16(value: float) -> int:
    return max(-32768, min(32767, int(round(value))))


def resample_pcm16(
    data: bytes, input_sample_rate: int, target_sample_rate: int
) -> bytes:
    """Resample one standalone PCM16 buffer. Use `Pcm16Resampler` for streams."""
    resampler = Pcm16Resampler(input_sample_rate, target_sample_rate)
    return resampler.resample(data) + resampler.flush()


def pcm16_to_wav(pcm_data: bytes, sample_rate: int = 24000) -> bytes:
    """Wrap raw PCM16 mono bytes in a WAV container."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_data)
    return buffer.getvalue()
