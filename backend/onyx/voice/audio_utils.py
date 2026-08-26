import io
import struct


def create_wav_header(
    data_length: int,
    sample_rate: int = 24000,
    channels: int = 1,
    bits_per_sample: int = 16,
) -> bytes:
    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_length,
        b"WAVE",
        b"fmt ",
        16,
        1,
        channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        data_length,
    )


def audio_bytes_to_file(audio_data: bytes, audio_format: str) -> io.BytesIO:
    if audio_format == "pcm16":
        audio_data = create_wav_header(len(audio_data)) + audio_data
        audio_format = "wav"

    audio_file = io.BytesIO(audio_data)
    audio_file.name = f"audio.{audio_format}"
    return audio_file
