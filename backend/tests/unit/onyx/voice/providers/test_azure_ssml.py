import io
import struct
import wave

import pytest

from onyx.voice.providers.azure import AzureVoiceProvider


# --- _is_azure_cloud_url ---


def test_is_azure_cloud_url_speech_microsoft() -> None:
    assert AzureVoiceProvider._is_azure_cloud_url(
        "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
    )


def test_is_azure_cloud_url_cognitive_microsoft() -> None:
    assert AzureVoiceProvider._is_azure_cloud_url(
        "https://westus.api.cognitive.microsoft.com/"
    )


def test_is_azure_cloud_url_rejects_custom_host() -> None:
    assert not AzureVoiceProvider._is_azure_cloud_url("https://my-custom-host.com/")


def test_is_azure_cloud_url_rejects_none() -> None:
    assert not AzureVoiceProvider._is_azure_cloud_url(None)


# --- _extract_speech_region_from_uri ---


def test_extract_region_from_tts_url() -> None:
    assert (
        AzureVoiceProvider._extract_speech_region_from_uri(
            "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
        )
        == "eastus"
    )


def test_extract_region_from_cognitive_api_url() -> None:
    assert (
        AzureVoiceProvider._extract_speech_region_from_uri(
            "https://eastus.api.cognitive.microsoft.com/"
        )
        == "eastus"
    )


def test_extract_region_returns_none_for_custom_domain() -> None:
    """Custom domains use resource name, not region — must use speech_region config."""
    assert (
        AzureVoiceProvider._extract_speech_region_from_uri(
            "https://myresource.cognitiveservices.azure.com/"
        )
        is None
    )


def test_extract_region_returns_none_for_none() -> None:
    assert AzureVoiceProvider._extract_speech_region_from_uri(None) is None


# --- _validate_speech_region ---


def test_validate_region_normalizes_to_lowercase() -> None:
    assert AzureVoiceProvider._validate_speech_region("WestUS2") == "westus2"


def test_validate_region_accepts_hyphens() -> None:
    assert AzureVoiceProvider._validate_speech_region("us-east-1") == "us-east-1"


def test_validate_region_rejects_path_traversal() -> None:
    with pytest.raises(ValueError, match="Invalid Azure speech_region"):
        AzureVoiceProvider._validate_speech_region("westus/../../etc")


def test_validate_region_rejects_dots() -> None:
    with pytest.raises(ValueError, match="Invalid Azure speech_region"):
        AzureVoiceProvider._validate_speech_region("west.us")


# --- _pcm16_to_wav ---


def test_pcm16_to_wav_produces_valid_wav() -> None:
    samples = [32767, -32768, 0, 1234]
    pcm_data = struct.pack(f"<{len(samples)}h", *samples)
    wav_bytes = AzureVoiceProvider._pcm16_to_wav(pcm_data, sample_rate=16000)

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        frames = wav_file.readframes(4)
        recovered = struct.unpack(f"<{len(samples)}h", frames)
        assert list(recovered) == samples


# --- URL Construction ---


def test_get_tts_url_cloud() -> None:
    provider = AzureVoiceProvider(
        api_key="key", api_base=None, custom_config={"speech_region": "eastus"}
    )
    assert (
        provider._get_tts_url()
        == "https://eastus.tts.speech.microsoft.com/cognitiveservices/v1"
    )


def test_get_stt_url_cloud() -> None:
    provider = AzureVoiceProvider(
        api_key="key", api_base=None, custom_config={"speech_region": "westus2"}
    )
    assert "westus2.stt.speech.microsoft.com" in provider._get_stt_url()


def test_get_tts_url_self_hosted() -> None:
    provider = AzureVoiceProvider(
        api_key="key", api_base="http://localhost:5000", custom_config={}
    )
    assert provider._get_tts_url() == "http://localhost:5000/cognitiveservices/v1"


def test_get_tts_url_self_hosted_strips_trailing_slash() -> None:
    provider = AzureVoiceProvider(
        api_key="key", api_base="http://localhost:5000/", custom_config={}
    )
    assert provider._get_tts_url() == "http://localhost:5000/cognitiveservices/v1"


# --- _is_self_hosted ---


def test_is_self_hosted_true_for_custom_endpoint() -> None:
    provider = AzureVoiceProvider(
        api_key="key", api_base="http://localhost:5000", custom_config={}
    )
    assert provider._is_self_hosted() is True


def test_is_self_hosted_false_for_azure_cloud() -> None:
    provider = AzureVoiceProvider(
        api_key="key",
        api_base="https://eastus.api.cognitive.microsoft.com/",
        custom_config={},
    )
    assert provider._is_self_hosted() is False


# --- Resampling ---


def test_resample_pcm16_passthrough() -> None:
    from onyx.voice.providers.azure import AzureStreamingTranscriber

    t = AzureStreamingTranscriber.__new__(AzureStreamingTranscriber)
    t.input_sample_rate = 16000
    t.target_sample_rate = 16000

    data = struct.pack("<4h", 100, 200, 300, 400)
    assert t._resample_pcm16(data) == data


def test_resample_pcm16_downsamples() -> None:
    from onyx.voice.providers.azure import AzureStreamingTranscriber

    t = AzureStreamingTranscriber.__new__(AzureStreamingTranscriber)
    t.input_sample_rate = 24000
    t.target_sample_rate = 16000

    input_samples = [1000, 2000, 3000, 4000, 5000, 6000]
    data = struct.pack(f"<{len(input_samples)}h", *input_samples)

    result = t._resample_pcm16(data)
    assert len(result) // 2 == 4


def test_resample_pcm16_empty_data() -> None:
    from onyx.voice.providers.azure import AzureStreamingTranscriber

    t = AzureStreamingTranscriber.__new__(AzureStreamingTranscriber)
    t.input_sample_rate = 24000
    t.target_sample_rate = 16000

    assert t._resample_pcm16(b"") == b""
