from collections.abc import AsyncIterator

from onyx.voice.interface import VoiceProviderInterface


class ElevenLabsVoiceProvider(VoiceProviderInterface):
    """ElevenLabs voice provider (placeholder - to be implemented)."""

    def __init__(
        self,
        api_key: str | None,
        api_base: str | None = None,
        stt_model: str | None = None,
        tts_model: str | None = None,
        default_voice: str | None = None,
    ):
        self.api_key = api_key
        self.api_base = api_base or "https://api.elevenlabs.io"
        self.stt_model = stt_model
        self.tts_model = tts_model or "eleven_multilingual_v2"
        self.default_voice = default_voice

    async def transcribe(self, _audio_data: bytes, _audio_format: str) -> str:
        raise NotImplementedError("ElevenLabs STT not yet implemented")

    async def synthesize_stream(
        self, _text: str, _voice: str | None = None, _speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        raise NotImplementedError("ElevenLabs TTS not yet implemented")
        yield b""  # Required for async generator

    def get_available_voices(self) -> list[dict[str, str]]:
        # ElevenLabs voices are fetched dynamically via API
        # Return empty list - frontend should fetch from /voices endpoint
        return []

    def get_available_stt_models(self) -> list[dict[str, str]]:
        return [
            {"id": "scribe_v1", "name": "Scribe v1"},
        ]

    def get_available_tts_models(self) -> list[dict[str, str]]:
        return [
            {"id": "eleven_multilingual_v2", "name": "Multilingual v2"},
            {"id": "eleven_turbo_v2_5", "name": "Turbo v2.5"},
            {"id": "eleven_monolingual_v1", "name": "Monolingual v1"},
        ]
