from collections.abc import AsyncIterator
from typing import Any

from onyx.voice.interface import VoiceProviderInterface


class AzureVoiceProvider(VoiceProviderInterface):
    """Azure Speech Services voice provider (placeholder - to be implemented)."""

    def __init__(
        self,
        api_key: str | None,
        custom_config: dict[str, Any],
        stt_model: str | None = None,
        tts_model: str | None = None,
        default_voice: str | None = None,
    ):
        self.api_key = api_key
        self.custom_config = custom_config
        self.speech_region = custom_config.get("speech_region", "")
        self.stt_model = stt_model
        self.tts_model = tts_model
        self.default_voice = default_voice or "en-US-JennyNeural"

    async def transcribe(self, _audio_data: bytes, _audio_format: str) -> str:
        raise NotImplementedError("Azure STT not yet implemented")

    async def synthesize_stream(
        self, _text: str, _voice: str | None = None, _speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        raise NotImplementedError("Azure TTS not yet implemented")
        yield b""  # Required for async generator

    def get_available_voices(self) -> list[dict[str, str]]:
        # Azure has many voices - return common ones
        return [
            {"id": "en-US-JennyNeural", "name": "Jenny (US)"},
            {"id": "en-US-GuyNeural", "name": "Guy (US)"},
            {"id": "en-GB-SoniaNeural", "name": "Sonia (UK)"},
            {"id": "en-GB-RyanNeural", "name": "Ryan (UK)"},
        ]

    def get_available_stt_models(self) -> list[dict[str, str]]:
        return [
            {"id": "default", "name": "Azure Speech Recognition"},
        ]

    def get_available_tts_models(self) -> list[dict[str, str]]:
        return [
            {"id": "neural", "name": "Neural TTS"},
        ]
