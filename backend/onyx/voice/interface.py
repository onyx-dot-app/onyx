from abc import ABC
from abc import abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class TranscriptResult:
    """Result from streaming transcription."""

    text: str
    """The accumulated transcript text."""

    is_vad_end: bool = False
    """True if VAD detected end of speech (silence). Use for auto-send."""


class StreamingTranscriberProtocol(Protocol):
    """Protocol for streaming transcription sessions."""

    async def send_audio(self, chunk: bytes) -> None:
        """Send an audio chunk for transcription."""
        ...

    async def receive_transcript(self) -> TranscriptResult | None:
        """
        Receive next transcript update.

        Returns:
            TranscriptResult with accumulated text and VAD status, or None when stream ends.
        """
        ...

    async def close(self) -> str:
        """Close the session and return final transcript."""
        ...

    def reset_transcript(self) -> None:
        """Reset accumulated transcript. Call after auto-send to start fresh."""
        ...


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

    def supports_streaming_stt(self) -> bool:
        """Returns True if this provider supports streaming STT."""
        return False

    async def create_streaming_transcriber(
        self, audio_format: str = "webm"
    ) -> StreamingTranscriberProtocol:
        """
        Create a streaming transcription session.

        Args:
            audio_format: Audio format being sent (e.g., "webm", "pcm16")

        Returns:
            A streaming transcriber that can send audio chunks and receive transcripts

        Raises:
            NotImplementedError: If streaming STT is not supported
        """
        raise NotImplementedError("Streaming STT not supported by this provider")
