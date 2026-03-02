import asyncio
import base64
import io
import json
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

import aiohttp

from onyx.voice.interface import StreamingTranscriberProtocol
from onyx.voice.interface import TranscriptResult
from onyx.voice.interface import VoiceProviderInterface

if TYPE_CHECKING:
    from openai import AsyncOpenAI


class OpenAIStreamingTranscriber(StreamingTranscriberProtocol):
    """Streaming transcription using OpenAI Realtime API."""

    def __init__(self, api_key: str, model: str = "whisper-1"):
        # Import logger first
        from onyx.utils.logger import setup_logger

        self._logger = setup_logger()

        self._logger.info(
            f"OpenAIStreamingTranscriber: initializing with model {model}"
        )
        self.api_key = api_key
        self.model = model
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
        url = "wss://api.openai.com/v1/realtime?intent=transcription"
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
                    if msg_type == "error":
                        error = data.get("error", {})
                        self._logger.error(f"OpenAI error: {error}")
                        continue

                    # Handle VAD events
                    if msg_type == "input_audio_buffer.speech_started":
                        self._logger.info("OpenAI: Speech started")
                        # Reset current turn transcript for new speech
                        self._current_turn_transcript = ""
                        continue
                    elif msg_type == "input_audio_buffer.speech_stopped":
                        self._logger.info(
                            "OpenAI: Speech stopped (VAD detected silence)"
                        )
                        continue
                    elif msg_type == "input_audio_buffer.committed":
                        self._logger.info("OpenAI: Audio buffer committed")
                        continue

                    # Handle transcription events
                    if msg_type == "conversation.item.input_audio_transcription.delta":
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
                    elif (
                        msg_type
                        == "conversation.item.input_audio_transcription.completed"
                    ):
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
                        "transcription_session.created",
                        "transcription_session.updated",
                        "conversation.item.created",
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

            # Wait for transcription to arrive (up to 5 seconds)
            self._logger.info("Waiting for transcription to complete...")
            for _ in range(50):  # 50 * 100ms = 5 seconds max
                await asyncio.sleep(0.1)
                if self._accumulated_transcript:
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
        async with client.audio.speech.with_streaming_response.create(
            model=self.tts_model,
            voice=voice or self.default_voice,
            input=text,
            speed=speed,
            response_format="mp3",
        ) as response:
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

    def supports_streaming_stt(self) -> bool:
        """OpenAI supports streaming via Realtime API for all STT models."""
        return True

    async def create_streaming_transcriber(
        self, _audio_format: str = "webm"
    ) -> OpenAIStreamingTranscriber:
        """Create a streaming transcription session using Realtime API."""
        if not self.api_key:
            raise ValueError("API key required for streaming transcription")
        transcriber = OpenAIStreamingTranscriber(
            api_key=self.api_key,
            model=self.stt_model,
        )
        await transcriber.connect()
        return transcriber
