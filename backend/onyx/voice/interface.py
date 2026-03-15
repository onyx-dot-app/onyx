from abc import ABC
from abc import abstractmethod
from collections.abc import AsyncIterator
from typing import Protocol

from pydantic import BaseModel


class TranscriptResult(BaseModel):
    """Result from streaming transcription."""

    text: str
    """The accumulated transcript text."""

    is_vad_end: bool = False
    """True if VAD detected end of speech (silence). Use for auto-send."""

    error: str | None = None
    """Provider error message to forward to the client, if any."""


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


class StreamingSynthesizerProtocol(Protocol):
    """Protocol for streaming TTS sessions (real-time text-to-speech)."""

    async def connect(self) -> None:
        """Establish connection to TTS provider."""
        ...

    async def send_text(self, text: str) -> None:
        """Send text to be synthesized."""
        ...

    async def receive_audio(self) -> bytes | None:
        """
        Receive next audio chunk.

        Returns:
            Audio bytes, or None when stream ends.
        """
        ...

    async def flush(self) -> None:
        """Signal end of text input and wait for pending audio."""
        ...

    async def close(self) -> None:
        """Close the session."""
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
    def synthesize_stream(
        self, text: str, voice: str | None = None, speed: float = 1.0
    ) -> AsyncIterator[bytes]:
        """
        Convert text to audio stream (Text-to-Speech).

        Streams audio chunks progressively for lower latency playback.

        Args:
            text: Text to convert to speech
            voice: Voice identifier (e.g., "alloy", "echo"), or None for default
            speed: Playback speed multiplier (0.25 to 4.0)

        Yields:
            Audio data chunks
        """

    @abstractmethod
    async def validate_credentials(self) -> None:
        """
        Validate that the provider credentials are correct by making a
        lightweight API call. Raises on failure.
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

    def supports_streaming_tts(self) -> bool:
        """Returns True if this provider supports real-time streaming TTS."""
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

    async def create_streaming_synthesizer(
        self, voice: str | None = None, speed: float = 1.0
    ) -> "StreamingSynthesizerProtocol":
        """
        Create a streaming TTS session for real-time audio synthesis.

        Args:
            voice: Voice identifier
            speed: Playback speed multiplier

        Returns:
            A streaming synthesizer that can send text and receive audio chunks

        Raises:
            NotImplementedError: If streaming TTS is not supported
        """
        raise NotImplementedError("Streaming TTS not supported by this provider")
