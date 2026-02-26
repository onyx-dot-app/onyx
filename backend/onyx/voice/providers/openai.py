import io
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from onyx.voice.interface import VoiceProviderInterface

if TYPE_CHECKING:
    from openai import AsyncOpenAI


# OpenAI available voices for TTS
OPENAI_VOICES = [
    {"id": "alloy", "name": "Alloy"},
    {"id": "echo", "name": "Echo"},
    {"id": "fable", "name": "Fable"},
    {"id": "onyx", "name": "Onyx"},
    {"id": "nova", "name": "Nova"},
    {"id": "shimmer", "name": "Shimmer"},
]

# OpenAI available STT models
OPENAI_STT_MODELS = [
    {"id": "whisper-1", "name": "Whisper v1"},
]

# OpenAI available TTS models
OPENAI_TTS_MODELS = [
    {"id": "tts-1", "name": "TTS-1 (Standard)"},
    {"id": "tts-1-hd", "name": "TTS-1 HD (High Quality)"},
]


class OpenAIVoiceProvider(VoiceProviderInterface):
    """OpenAI voice provider using Whisper for STT and TTS API for speech synthesis."""

    def __init__(
        self,
        api_key: str | None,
        api_base: str | None = None,
        stt_model: str | None = None,
        tts_model: str | None = None,
        default_voice: str | None = None,
    ):
        self.api_key = api_key
        self.api_base = api_base
        self.stt_model = stt_model or "whisper-1"
        self.tts_model = tts_model or "tts-1"
        self.default_voice = default_voice or "alloy"

        self._client: "AsyncOpenAI | None" = None

    def _get_client(self) -> "AsyncOpenAI":
        if self._client is None:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.api_base,
            )
        return self._client

    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        """
        Transcribe audio using OpenAI Whisper.

        Args:
            audio_data: Raw audio bytes
            audio_format: Audio format (e.g., "webm", "wav", "mp3")

        Returns:
            Transcribed text
        """
        client = self._get_client()

        # Create a file-like object from the audio bytes
        audio_file = io.BytesIO(audio_data)
        audio_file.name = f"audio.{audio_format}"

        response = await client.audio.transcriptions.create(
            model=self.stt_model,
            file=audio_file,
        )

        return response.text

    async def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        """
        Convert text to audio using OpenAI TTS with streaming.

        Args:
            text: Text to convert to speech
            voice: Voice identifier (defaults to provider's default voice)
            speed: Playback speed multiplier (0.25 to 4.0)

        Yields:
            Audio data chunks (mp3 format)
        """
        client = self._get_client()

        # Clamp speed to valid range
        speed = max(0.25, min(4.0, speed))

        response = await client.audio.speech.create(
            model=self.tts_model,
            voice=voice or self.default_voice,
            input=text,
            speed=speed,
            response_format="mp3",
        )

        # Stream the response content
        async for chunk in response.iter_bytes(chunk_size=4096):
            yield chunk

    def get_available_voices(self) -> list[dict[str, str]]:
        """Get available OpenAI TTS voices."""
        return OPENAI_VOICES.copy()

    def get_available_stt_models(self) -> list[dict[str, str]]:
        """Get available OpenAI STT models."""
        return OPENAI_STT_MODELS.copy()

    def get_available_tts_models(self) -> list[dict[str, str]]:
        """Get available OpenAI TTS models."""
        return OPENAI_TTS_MODELS.copy()
