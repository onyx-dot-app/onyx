import struct

from onyx.voice.providers.elevenlabs import _http_to_ws_url
from onyx.voice.providers.elevenlabs import DEFAULT_ELEVENLABS_API_BASE
from onyx.voice.providers.elevenlabs import ElevenLabsSTTMessageType
from onyx.voice.providers.elevenlabs import ElevenLabsVoiceProvider


# --- _http_to_ws_url ---


def test_http_to_ws_url_converts_https_to_wss() -> None:
    assert _http_to_ws_url("https://api.elevenlabs.io") == "wss://api.elevenlabs.io"


def test_http_to_ws_url_converts_http_to_ws() -> None:
    assert _http_to_ws_url("http://localhost:8080") == "ws://localhost:8080"


def test_http_to_ws_url_passes_through_other_schemes() -> None:
    assert _http_to_ws_url("wss://already.ws") == "wss://already.ws"


def test_http_to_ws_url_preserves_path() -> None:
    assert (
        _http_to_ws_url("https://api.elevenlabs.io/v1/tts")
        == "wss://api.elevenlabs.io/v1/tts"
    )


# --- StrEnum comparison ---


def test_stt_message_type_compares_as_string() -> None:
    """StrEnum members should work in string comparisons (e.g. from JSON)."""
    assert str(ElevenLabsSTTMessageType.COMMITTED_TRANSCRIPT) == "committed_transcript"
    assert isinstance(ElevenLabsSTTMessageType.ERROR, str)


# --- Resampling ---


def test_resample_pcm16_passthrough_when_same_rate() -> None:
    from onyx.voice.providers.elevenlabs import ElevenLabsStreamingTranscriber

    t = ElevenLabsStreamingTranscriber.__new__(ElevenLabsStreamingTranscriber)
    t.input_sample_rate = 16000
    t.target_sample_rate = 16000

    data = struct.pack("<4h", 100, 200, 300, 400)
    assert t._resample_pcm16(data) == data


def test_resample_pcm16_downsamples() -> None:
    """24kHz -> 16kHz should produce fewer samples (ratio 3:2)."""
    from onyx.voice.providers.elevenlabs import ElevenLabsStreamingTranscriber

    t = ElevenLabsStreamingTranscriber.__new__(ElevenLabsStreamingTranscriber)
    t.input_sample_rate = 24000
    t.target_sample_rate = 16000

    input_samples = [1000, 2000, 3000, 4000, 5000, 6000]
    data = struct.pack(f"<{len(input_samples)}h", *input_samples)

    result = t._resample_pcm16(data)
    output_samples = struct.unpack(f"<{len(result) // 2}h", result)

    assert len(output_samples) == 4


def test_resample_pcm16_clamps_to_int16_range() -> None:
    from onyx.voice.providers.elevenlabs import ElevenLabsStreamingTranscriber

    t = ElevenLabsStreamingTranscriber.__new__(ElevenLabsStreamingTranscriber)
    t.input_sample_rate = 24000
    t.target_sample_rate = 16000

    input_samples = [32767, -32768, 32767, -32768, 32767, -32768]
    data = struct.pack(f"<{len(input_samples)}h", *input_samples)

    result = t._resample_pcm16(data)
    output_samples = struct.unpack(f"<{len(result) // 2}h", result)
    for s in output_samples:
        assert -32768 <= s <= 32767


# --- Provider Model Defaulting ---


def test_provider_defaults_invalid_stt_model() -> None:
    provider = ElevenLabsVoiceProvider(api_key="test", stt_model="invalid_model")
    assert provider.stt_model == "scribe_v1"


def test_provider_defaults_invalid_tts_model() -> None:
    provider = ElevenLabsVoiceProvider(api_key="test", tts_model="invalid_model")
    assert provider.tts_model == "eleven_multilingual_v2"


def test_provider_accepts_valid_models() -> None:
    provider = ElevenLabsVoiceProvider(
        api_key="test", stt_model="scribe_v2_realtime", tts_model="eleven_turbo_v2_5"
    )
    assert provider.stt_model == "scribe_v2_realtime"
    assert provider.tts_model == "eleven_turbo_v2_5"


def test_provider_defaults_api_base() -> None:
    provider = ElevenLabsVoiceProvider(api_key="test")
    assert provider.api_base == DEFAULT_ELEVENLABS_API_BASE


def test_provider_get_available_voices_returns_copy() -> None:
    provider = ElevenLabsVoiceProvider(api_key="test")
    voices = provider.get_available_voices()
    voices.clear()
    assert len(provider.get_available_voices()) > 0
