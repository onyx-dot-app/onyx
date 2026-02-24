from abc import ABC
from abc import abstractmethod
from collections.abc import AsyncIterator


class VoiceProviderInterface(ABC):
    """Abstract base class for voice providers (STT and TTS)."""

    @abstractmethod
    async def transcribe(self, audio_data: bytes, audio_format: str) -> str:
        """
        Convert audio to text (Speech-to-Text).

        Args:
            audio_data: Raw audio bytes
            audio_format: Audio format (e.g., "webm", "wav", "mp3")

        Returns:
            Transcribed text
        """

    @abstractmethod
    async def synthesize_stream(
        self, text: str, voice: str, speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        """
        Convert text to audio stream (Text-to-Speech).

        Streams audio chunks progressively for lower latency playback.

        Args:
            text: Text to convert to speech
            voice: Voice identifier (e.g., "alloy", "echo")
            speed: Playback speed multiplier (0.25 to 4.0)

        Yields:
            Audio data chunks
        """

    @abstractmethod
    def get_available_voices(self) -> list[dict[str, str]]:
        """
        Get list of available voices for this provider.

        Returns:
            List of voice dictionaries with 'id' and 'name' keys
        """

    @abstractmethod
    def get_available_stt_models(self) -> list[dict[str, str]]:
        """
        Get list of available STT models for this provider.

        Returns:
            List of model dictionaries with 'id' and 'name' keys
        """

    @abstractmethod
    def get_available_tts_models(self) -> list[dict[str, str]]:
        """
        Get list of available TTS models for this provider.

        Returns:
            List of model dictionaries with 'id' and 'name' keys
        """
