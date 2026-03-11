import io
import struct
import wave

from onyx.voice.providers.openai import _create_wav_header
from onyx.voice.providers.openai import _http_to_ws_url
from onyx.voice.providers.openai import OpenAIRealtimeMessageType
from onyx.voice.providers.openai import OpenAIVoiceProvider


# --- _http_to_ws_url ---


def test_http_to_ws_url_converts_https_to_wss() -> None:
    assert _http_to_ws_url("https://api.openai.com") == "wss://api.openai.com"


def test_http_to_ws_url_converts_http_to_ws() -> None:
    assert _http_to_ws_url("http://localhost:9090") == "ws://localhost:9090"


def test_http_to_ws_url_passes_through_ws() -> None:
    assert _http_to_ws_url("wss://already.ws") == "wss://already.ws"


# --- StrEnum comparison ---


def test_realtime_message_type_compares_as_string() -> None:
    assert OpenAIRealtimeMessageType.ERROR == "error"
    assert (
        OpenAIRealtimeMessageType.TRANSCRIPTION_DELTA
        == "conversation.item.input_audio_transcription.delta"
    )
    assert isinstance(OpenAIRealtimeMessageType.ERROR, str)


# --- _create_wav_header ---


def test_wav_header_is_44_bytes() -> None:
    assert len(_create_wav_header(1000)) == 44


def test_wav_header_chunk_size_matches_data_length() -> None:
    data_length = 2000
    header = _create_wav_header(data_length)
    chunk_size = struct.unpack_from("<I", header, 4)[0]
    assert chunk_size == 36 + data_length


def test_wav_header_byte_rate() -> None:
    header = _create_wav_header(100, sample_rate=24000, channels=1, bits_per_sample=16)
    byte_rate = struct.unpack_from("<I", header, 28)[0]
    assert byte_rate == 24000 * 1 * 16 // 8


def test_wav_header_produces_valid_wav() -> None:
    """Header + PCM data should parse as valid WAV."""
    data_length = 100
    pcm_data = b"\x00" * data_length
    header = _create_wav_header(data_length, sample_rate=24000)

    with wave.open(io.BytesIO(header + pcm_data), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 24000
        assert wav_file.getnframes() == data_length // 2


# --- Provider Defaults ---


def test_provider_default_models() -> None:
    provider = OpenAIVoiceProvider(api_key="test")
    assert provider.stt_model == "whisper-1"
    assert provider.tts_model == "tts-1"
    assert provider.default_voice == "alloy"


def test_provider_custom_models() -> None:
    provider = OpenAIVoiceProvider(
        api_key="test",
        stt_model="gpt-4o-transcribe",
        tts_model="tts-1-hd",
        default_voice="nova",
    )
    assert provider.stt_model == "gpt-4o-transcribe"
    assert provider.tts_model == "tts-1-hd"
    assert provider.default_voice == "nova"


def test_provider_get_available_voices_returns_copy() -> None:
    provider = OpenAIVoiceProvider(api_key="test")
    voices = provider.get_available_voices()
    voices.clear()
    assert len(provider.get_available_voices()) > 0
