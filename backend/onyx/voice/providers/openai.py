"""OpenAI voice provider for STT and TTS.

OpenAI supports:
- **STT**: Whisper (batch transcription via REST) and Realtime API (streaming
  transcription via WebSocket with server-side VAD). Audio is sent as base64-encoded
  PCM16 at 24kHz mono. The Realtime API returns transcript deltas and completed
  transcription events per VAD-detected utterance.
- **TTS**: HTTP streaming endpoint that returns audio chunks progressively.
  Supported models: tts-1 (standard) and tts-1-hd (high quality).

See https://platform.openai.com/docs for API reference.
"""

import asyncio
import base64
import io
import json
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import TYPE_CHECKING

import aiohttp

from onyx.voice.interface import StreamingSynthesizerProtocol
from onyx.voice.interface import StreamingTranscriberProtocol
from onyx.voice.interface import TranscriptResult
from onyx.voice.interface import VoiceProviderInterface

if TYPE_CHECKING:
    from openai import AsyncOpenAI

# Default OpenAI API base URL
DEFAULT_OPENAI_API_BASE = "https://api.openai.com"


class OpenAIRealtimeMessageType(StrEnum):
    """Message types from OpenAI Realtime transcription API."""

    ERROR = "error"
    SPEECH_STARTED = "input_audio_buffer.speech_started"
    SPEECH_STOPPED = "input_audio_buffer.speech_stopped"
    BUFFER_COMMITTED = "input_audio_buffer.committed"
    TRANSCRIPTION_DELTA = "conversation.item.input_audio_transcription.delta"
    TRANSCRIPTION_COMPLETED = "conversation.item.input_audio_transcription.completed"
    SESSION_CREATED = "transcription_session.created"
    SESSION_UPDATED = "transcription_session.updated"
    ITEM_CREATED = "conversation.item.created"


def _http_to_ws_url(http_url: str) -> str:
    """Convert http(s) URL to ws(s) URL for WebSocket connections."""
    if http_url.startswith("https://"):
        return "wss://" + http_url[8:]
    elif http_url.startswith("http://"):
        return "ws://" + http_url[7:]
    return http_url


class OpenAIStreamingTranscriber(StreamingTranscriberProtocol):
    """Streaming transcription using OpenAI Realtime API."""

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
        api_base: str | None = None,
    ):
        # Import logger first
        from onyx.utils.logger import setup_logger

        self._logger = setup_logger()

        self._logger.info(
            f"OpenAIStreamingTranscriber: initializing with model {model}"
        )
        self.api_key = api_key
        self.model = model
        self.api_base = api_base or DEFAULT_OPENAI_API_BASE
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._transcript_queue: asyncio.Queue[TranscriptResult | None] = asyncio.Queue()
        self._current_turn_transcript = ""  # Transcript for current VAD turn
        self._accumulated_transcript = ""  # Accumulated across all turns
        self._receive_task: asyncio.Task | None = None
        self._closed = False

    async def connect(self) -> None:
        """Establish WebSocket connection to OpenAI Realtime API."""
        self._session = aiohttp.ClientSession()

        # OpenAI Realtime transcription endpoint
        ws_base = _http_to_ws_url(self.api_base.rstrip("/"))
        url = f"{ws_base}/v1/realtime?intent=transcription"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        try:
            self._ws = await self._session.ws_connect(url, headers=headers)
            self._logger.info("Connected to OpenAI Realtime API")
        except Exception as e:
            self._logger.error(f"Failed to connect to OpenAI Realtime API: {e}")
            raise

        # Configure the session for transcription
        # Enable server-side VAD (Voice Activity Detection) for automatic speech detection
        config_message = {
            "type": "transcription_session.update",
            "session": {
                "input_audio_format": "pcm16",  # 16-bit PCM at 24kHz mono
                "input_audio_transcription": {
                    "model": self.model,
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500,
                },
            },
        }
        await self._ws.send_str(json.dumps(config_message))
        self._logger.info(f"Sent config for model: {self.model} with server VAD")

        # Start receiving transcripts
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        """Background task to receive transcripts."""
        if not self._ws:
            return

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_type = data.get("type", "")
                    self._logger.debug(f"Received message type: {msg_type}")

                    # Handle errors
                    if msg_type == OpenAIRealtimeMessageType.ERROR:
                        error = data.get("error", {})
                        self._logger.error(f"OpenAI error: {error}")
                        continue

                    # Handle VAD events
                    if msg_type == OpenAIRealtimeMessageType.SPEECH_STARTED:
                        self._logger.info("OpenAI: Speech started")
                        # Reset current turn transcript for new speech
                        self._current_turn_transcript = ""
                        continue
                    elif msg_type == OpenAIRealtimeMessageType.SPEECH_STOPPED:
                        self._logger.info(
                            "OpenAI: Speech stopped (VAD detected silence)"
                        )
                        continue
                    elif msg_type == OpenAIRealtimeMessageType.BUFFER_COMMITTED:
                        self._logger.info("OpenAI: Audio buffer committed")
                        continue

                    # Handle transcription events
                    if msg_type == OpenAIRealtimeMessageType.TRANSCRIPTION_DELTA:
                        delta = data.get("delta", "")
                        if delta:
                            self._logger.info(f"OpenAI: Transcription delta: {delta}")
                            self._current_turn_transcript += delta
                            # Show accumulated + current turn transcript
                            full_transcript = self._accumulated_transcript
                            if full_transcript and self._current_turn_transcript:
                                full_transcript += " "
                            full_transcript += self._current_turn_transcript
                            await self._transcript_queue.put(
                                TranscriptResult(text=full_transcript, is_vad_end=False)
                            )
                    elif msg_type == OpenAIRealtimeMessageType.TRANSCRIPTION_COMPLETED:
                        transcript = data.get("transcript", "")
                        if transcript:
                            self._logger.info(
                                f"OpenAI: Transcription completed (VAD turn end): {transcript[:50]}..."
                            )
                            # This is the final transcript for this VAD turn
                            self._current_turn_transcript = transcript
                            # Accumulate this turn's transcript
                            if self._accumulated_transcript:
                                self._accumulated_transcript += " " + transcript
                            else:
                                self._accumulated_transcript = transcript
                            # Send with is_vad_end=True to trigger auto-send
                            await self._transcript_queue.put(
                                TranscriptResult(
                                    text=self._accumulated_transcript,
                                    is_vad_end=True,
                                )
                            )
                    elif msg_type not in (
                        OpenAIRealtimeMessageType.SESSION_CREATED,
                        OpenAIRealtimeMessageType.SESSION_UPDATED,
                        OpenAIRealtimeMessageType.ITEM_CREATED,
                    ):
                        # Log any other message types we might be missing
                        self._logger.info(
                            f"OpenAI: Unhandled message type '{msg_type}': {data}"
                        )

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self._logger.error(f"WebSocket error: {self._ws.exception()}")
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    self._logger.info("WebSocket closed by server")
                    break
        except Exception as e:
            self._logger.error(f"Error in receive loop: {e}")
        finally:
            await self._transcript_queue.put(None)

    async def send_audio(self, chunk: bytes) -> None:
        """Send audio chunk to OpenAI."""
        if self._ws and not self._closed:
            # OpenAI expects base64-encoded PCM16 audio at 24kHz mono
            # PCM16 at 24kHz: 24000 samples/sec * 2 bytes/sample = 48000 bytes/sec
            # So chunk_bytes / 48000 = duration in seconds
            duration_ms = (len(chunk) / 48000) * 1000
            self._logger.debug(
                f"Sending {len(chunk)} bytes ({duration_ms:.1f}ms) of audio to OpenAI. "
                f"First 10 bytes: {chunk[:10].hex() if len(chunk) >= 10 else chunk.hex()}"
            )
            message = {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(chunk).decode("utf-8"),
            }
            await self._ws.send_str(json.dumps(message))

    def reset_transcript(self) -> None:
        """Reset accumulated transcript. Call after auto-send to start fresh."""
        self._logger.info("OpenAI: Resetting accumulated transcript")
        self._accumulated_transcript = ""
        self._current_turn_transcript = ""

    async def receive_transcript(self) -> TranscriptResult | None:
        """Receive next transcript."""
        try:
            return await asyncio.wait_for(self._transcript_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return TranscriptResult(text="", is_vad_end=False)

    async def close(self) -> str:
        """Close session and return final transcript."""
        self._closed = True
        if self._ws:
            # With server VAD, the buffer is auto-committed when speech stops.
            # But we should still commit any remaining audio and wait for transcription.
            try:
                await self._ws.send_str(
                    json.dumps({"type": "input_audio_buffer.commit"})
                )
            except Exception as e:
                self._logger.debug(f"Error sending commit (may be expected): {e}")

            # Wait for *new* transcription to arrive (up to 5 seconds)
            self._logger.info("Waiting for transcription to complete...")
            transcript_before_commit = self._accumulated_transcript
            for _ in range(50):  # 50 * 100ms = 5 seconds max
                await asyncio.sleep(0.1)
                if self._accumulated_transcript != transcript_before_commit:
                    self._logger.info(
                        f"Got final transcript: {self._accumulated_transcript[:50]}..."
                    )
                    break
            else:
                self._logger.warning("Timed out waiting for transcription")

            await self._ws.close()
        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
        if self._session:
            await self._session.close()
        return self._accumulated_transcript


# OpenAI available voices for TTS
OPENAI_VOICES = [
    {"id": "alloy", "name": "Alloy"},
    {"id": "echo", "name": "Echo"},
    {"id": "fable", "name": "Fable"},
    {"id": "onyx", "name": "Onyx"},
    {"id": "nova", "name": "Nova"},
    {"id": "shimmer", "name": "Shimmer"},
]

# OpenAI available STT models (all support streaming via Realtime API)
OPENAI_STT_MODELS = [
    {"id": "whisper-1", "name": "Whisper v1"},
    {"id": "gpt-4o-transcribe", "name": "GPT-4o Transcribe"},
    {"id": "gpt-4o-mini-transcribe", "name": "GPT-4o Mini Transcribe"},
]

# OpenAI available TTS models
OPENAI_TTS_MODELS = [
    {"id": "tts-1", "name": "TTS-1 (Standard)"},
    {"id": "tts-1-hd", "name": "TTS-1 HD (High Quality)"},
]


def _create_wav_header(
    data_length: int,
    sample_rate: int = 24000,
    channels: int = 1,
    bits_per_sample: int = 16,
) -> bytes:
    """Create a WAV file header for PCM audio data."""
    import struct

    byte_rate = sample_rate * channels * bits_per_sample // 8
    block_align = channels * bits_per_sample // 8

    # WAV header is 44 bytes
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",  # ChunkID
        36 + data_length,  # ChunkSize
        b"WAVE",  # Format
        b"fmt ",  # Subchunk1ID
        16,  # Subchunk1Size (PCM)
        1,  # AudioFormat (1 = PCM)
        channels,  # NumChannels
        sample_rate,  # SampleRate
        byte_rate,  # ByteRate
        block_align,  # BlockAlign
        bits_per_sample,  # BitsPerSample
        b"data",  # Subchunk2ID
        data_length,  # Subchunk2Size
    )
    return header


class OpenAIStreamingSynthesizer(StreamingSynthesizerProtocol):
    """Streaming TTS using OpenAI HTTP TTS API with streaming responses."""

    def __init__(
        self,
        api_key: str,
        voice: str = "alloy",
        model: str = "tts-1",
        speed: float = 1.0,
        api_base: str | None = None,
    ):
        from onyx.utils.logger import setup_logger

        self._logger = setup_logger()
        self.api_key = api_key
        self.voice = voice
        self.model = model
        self.speed = max(0.25, min(4.0, speed))
        self.api_base = api_base or DEFAULT_OPENAI_API_BASE
        self._session: aiohttp.ClientSession | None = None
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._text_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._synthesis_task: asyncio.Task | None = None
        self._closed = False
        self._flushed = False

    async def connect(self) -> None:
        """Initialize HTTP session for TTS requests."""
        self._logger.info("OpenAIStreamingSynthesizer: connecting")
        self._session = aiohttp.ClientSession()
        # Start background task to process text queue
        self._synthesis_task = asyncio.create_task(self._process_text_queue())
        self._logger.info("OpenAIStreamingSynthesizer: connected")

    async def _process_text_queue(self) -> None:
        """Background task to process queued text for synthesis."""
        while not self._closed:
            try:
                text = await asyncio.wait_for(self._text_queue.get(), timeout=0.1)
                if text is None:
                    break
                await self._synthesize_text(text)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error(f"Error processing text queue: {e}")

    async def _synthesize_text(self, text: str) -> None:
        """Make HTTP TTS request and stream audio to queue."""
        if not self._session or self._closed:
            return

        url = f"{self.api_base.rstrip('/')}/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "voice": self.voice,
            "input": text,
            "speed": self.speed,
            "response_format": "mp3",
        }

        try:
            async with self._session.post(
                url, headers=headers, json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    self._logger.error(f"OpenAI TTS error: {error_text}")
                    return

                # Use 8192 byte chunks for smoother streaming
                # (larger chunks = more complete MP3 frames, better playback)
                async for chunk in response.content.iter_chunked(8192):
                    if self._closed:
                        break
                    if chunk:
                        await self._audio_queue.put(chunk)
        except Exception as e:
            self._logger.error(f"OpenAIStreamingSynthesizer synthesis error: {e}")

    async def send_text(self, text: str) -> None:
        """Queue text to be synthesized via HTTP streaming."""
        if not text.strip() or self._closed:
            return
        await self._text_queue.put(text)

    async def receive_audio(self) -> bytes | None:
        """Receive next audio chunk (MP3 format)."""
        try:
            return await asyncio.wait_for(self._audio_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return b""  # No audio yet, but not done

    async def flush(self) -> None:
        """Signal end of text input - wait for synthesis to complete."""
        if self._flushed:
            return
        self._flushed = True

        # Signal end of text input
        await self._text_queue.put(None)

        # Wait for synthesis task to complete processing all text
        if self._synthesis_task and not self._synthesis_task.done():
            try:
                await asyncio.wait_for(self._synthesis_task, timeout=60.0)
            except asyncio.TimeoutError:
                self._logger.warning("OpenAIStreamingSynthesizer: flush timeout")
                self._synthesis_task.cancel()
                try:
                    await self._synthesis_task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass

        # Signal end of audio stream
        await self._audio_queue.put(None)

    async def close(self) -> None:
        """Close the session."""
        if self._closed:
            return
        self._closed = True

        # Signal end of queues only if flush wasn't already called
        if not self._flushed:
            await self._text_queue.put(None)
            await self._audio_queue.put(None)

        if self._synthesis_task and not self._synthesis_task.done():
            self._synthesis_task.cancel()
            try:
                await self._synthesis_task
            except asyncio.CancelledError:
                pass

        if self._session:
            await self._session.close()


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

        # Use with_streaming_response for proper async streaming
        # Using 8192 byte chunks for better streaming performance
        # (larger chunks = fewer round-trips, more complete MP3 frames)
        async with client.audio.speech.with_streaming_response.create(
            model=self.tts_model,
            voice=voice or self.default_voice,
            input=text,
            speed=speed,
            response_format="mp3",
        ) as response:
            async for chunk in response.iter_bytes(chunk_size=8192):
                yield chunk

    async def validate_credentials(self) -> None:
        """Validate OpenAI API key by listing models."""
        from openai import AuthenticationError
        from openai import PermissionDeniedError

        client = self._get_client()
        try:
            await client.models.list()
        except AuthenticationError:
            raise RuntimeError("Invalid OpenAI API key.")
        except PermissionDeniedError:
            raise RuntimeError("OpenAI API key does not have sufficient permissions.")

    def get_available_voices(self) -> list[dict[str, str]]:
        """Get available OpenAI TTS voices."""
        return OPENAI_VOICES.copy()

    def get_available_stt_models(self) -> list[dict[str, str]]:
        """Get available OpenAI STT models."""
        return OPENAI_STT_MODELS.copy()

    def get_available_tts_models(self) -> list[dict[str, str]]:
        """Get available OpenAI TTS models."""
        return OPENAI_TTS_MODELS.copy()

    def supports_streaming_stt(self) -> bool:
        """OpenAI supports streaming via Realtime API for all STT models."""
        return True

    def supports_streaming_tts(self) -> bool:
        """OpenAI supports real-time streaming TTS via Realtime API."""
        return True

    async def create_streaming_transcriber(  # ty: ignore[invalid-method-override]
        self, _audio_format: str = "webm"
    ) -> OpenAIStreamingTranscriber:
        """Create a streaming transcription session using Realtime API."""
        if not self.api_key:
            raise ValueError("API key required for streaming transcription")
        transcriber = OpenAIStreamingTranscriber(
            api_key=self.api_key,
            model=self.stt_model,
            api_base=self.api_base,
        )
        await transcriber.connect()
        return transcriber

    async def create_streaming_synthesizer(
        self, voice: str | None = None, speed: float = 1.0
    ) -> OpenAIStreamingSynthesizer:
        """Create a streaming TTS session using HTTP streaming API."""
        if not self.api_key:
            raise ValueError("API key required for streaming TTS")
        synthesizer = OpenAIStreamingSynthesizer(
            api_key=self.api_key,
            voice=voice or self.default_voice or "alloy",
            model=self.tts_model or "tts-1",
            speed=speed,
            api_base=self.api_base,
        )
        await synthesizer.connect()
        return synthesizer
